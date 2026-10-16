#!/usr/bin/env python3
"""Build a self-contained, interactive HTML viewer from exported research data."""

import argparse
import json
import posixpath
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit(
        "Pillow is required to convert the game's TGA images: "
        "python3 -m pip install Pillow"
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "research_export"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "research_tree_html"

# Required files, relative to the game resource directory supplied on the
# command line. Localization lives beside resource/, hence the parent segment.
REQUIRED_GAME_FILES = {
    "vehicle_archive": Path("entity/-vehicle.pak"),
    "gamelogic_archive": Path("gamelogic.pak"),
    "localization_archive": Path("../localizations/default.pak"),
    "properties_archive": Path("properties.pak"),
}

# Normalized research branches shown in the viewer. The game provides broad
# source sections; roots within SQUADS and Trucks need a little refinement.
BRANCH_TYPES = {
    "command": ("Infantry", "Command"),
    "infantry-formations": ("Infantry", "Infantry formations"),
    "engineers": ("Infantry", "Engineers"),
    "infantry-at": ("Infantry", "Infantry anti-tank"),
    "machine-guns": ("Support weapons", "Machine guns"),
    "mortars": ("Support weapons", "Mortars"),
    "anti-air": ("Support weapons", "Anti-air"),
    "anti-tank-guns": ("Support weapons", "Anti-tank guns"),
    "logistics": ("Vehicles", "Logistics"),
    "transport": ("Vehicles", "Transport"),
    "recon-vehicles": ("Vehicles", "Recon vehicles"),
    "tanks": ("Vehicles", "Tanks"),
}

# Soldier icons are the game's most consistent indication of weapon role.
# The "tech" icon is deliberately omitted because it describes support staff,
# not a weapon.
WEAPON_ROLE_BY_ICON = {
    "rifle": "rifle",
    "smg": "submachine-gun",
    "autorifle": "automatic-rifle",
    "stg": "assault-rifle",
    "mg": "machine-gun",
    "bazooka": "at-launcher",
    "atrifle": "at-rifle",
    "flamer": "flamethrower",
    "sniper": "sniper-rifle",
    "pistol": "pistol",
    "shotgun": "shotgun",
    "riflegrenade": "rifle-grenade",
}

# Useful carried-equipment categories. Ordinary weapons and ammunition are
# covered by the weapon-role filter, while ubiquitous bandages add little value.
INVENTORY_TYPES = (
    "shovel",
    "binoculars",
    "mine-detector",
    "wire-cutters",
    "pickaxe",
    "demolition-charge",
    "anti-tank-grenade",
    "anti-personnel-grenade",
    "anti-personnel-mine",
    "anti-tank-mine",
    "smoke",
    "incendiary-wp",
    "molotov-cocktail",
    "body-armour",
    "radio",
    "flare-gun",
    "knife-bayonet",
)


@dataclass(frozen=True)
class GameFiles:
    """Game archives needed to enrich the exported research data."""

    vehicle_archive: Path
    game_logic_archive: Path
    localization_archive: Path
    properties_archive: Path

    @classmethod
    def from_game_directory(cls, game_directory: Path) -> "GameFiles":
        paths = {
            name: (game_directory / relative_path).resolve()
            for name, relative_path in REQUIRED_GAME_FILES.items()
        }
        return cls(
            vehicle_archive=paths["vehicle_archive"],
            game_logic_archive=paths["gamelogic_archive"],
            localization_archive=paths["localization_archive"],
            properties_archive=paths["properties_archive"],
        )

    def missing(self) -> list[Path]:
        return [
            path
            for path in (
                self.vehicle_archive,
                self.game_logic_archive,
                self.localization_archive,
                self.properties_archive,
            )
            if not path.is_file()
        ]


def log(message: str) -> None:
    print(f"[research-tree-html] {message}", flush=True)


def safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return cleaned or "node"


def load_trees(input_dir: Path) -> list[dict]:
    """Load and validate every faction JSON file from the exporter."""
    json_paths = sorted(input_dir.glob("*.json"))
    if not json_paths:
        raise RuntimeError(f"No faction JSON files found in {input_dir}")

    trees = []
    for path in json_paths:
        try:
            tree = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not read {path}: {exc}") from exc

        faction = tree.get("faction")
        nodes = tree.get("nodes")
        if not faction or not isinstance(nodes, list) or not nodes:
            raise RuntimeError(f"Invalid or empty research tree in {path}")

        node_ids = [node.get("id") for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise RuntimeError(f"Duplicate node IDs found in {path}")

        tree["source_json"] = path.name
        trees.append(tree)
        log(f"Loaded {faction}: {len(nodes)} nodes")

    return trees


def classify_research_root(node: dict) -> str | None:
    """Translate a root's source section and identity into a viewer branch."""
    node_id = str(node.get("id") or "").lower()
    section = str(node.get("research_section") or "").lower()
    if node_id == "conquest_blank":
        return None

    if section == "squads":
        if "officer" in node_id:
            return "command"
        if "engineer" in node_id:
            return "engineers"
        if node_id.startswith("single_at") or "riflegrenade" in node_id:
            return "infantry-at"
        return "infantry-formations"
    if section == "mg":
        return "machine-guns"
    if section == "mortar":
        return "mortars"
    if section == "aa":
        return "anti-air"
    if section == "at guns":
        return "anti-tank-guns"
    if section == "trucks":
        if node_id.startswith("inf_crate_"):
            return "logistics"
        # The German tree places this armored scout car in the Trucks section.
        if node_id == "kfz13":
            return "recon-vehicles"
        return "transport"
    if section == "armored cars":
        return "recon-vehicles"
    if section in {"light tanks", "medium tanks", "heavy tanks"}:
        return "tanks"
    return None


def annotate_research_branches(trees: list[dict]) -> tuple[int, int]:
    """Assign root branch types and propagate all root ancestry to descendants."""
    typed_roots = 0
    nodes_with_branches = 0
    branch_order = {branch_type: index for index, branch_type in enumerate(BRANCH_TYPES)}

    for tree in trees:
        by_id = {node["id"]: node for node in tree["nodes"]}
        root_types = {}
        for node in tree["nodes"]:
            node["branch_type"] = None
            node["branch_label"] = None
            node["branch_group"] = None
            if node.get("requires"):
                continue
            branch_type = classify_research_root(node)
            if not branch_type:
                continue
            group, label = BRANCH_TYPES[branch_type]
            node["branch_type"] = branch_type
            node["branch_label"] = label
            node["branch_group"] = group
            root_types[node["id"]] = branch_type
            typed_roots += 1

        ancestry_cache: dict[str, dict[str, str]] = {}

        def root_ancestry(node_id: str, visiting: set[str] | None = None) -> dict[str, str]:
            if node_id in ancestry_cache:
                return ancestry_cache[node_id]
            if node_id in root_types:
                result = {node_id: root_types[node_id]}
                ancestry_cache[node_id] = result
                return result

            visiting = set() if visiting is None else visiting
            if node_id in visiting:
                return {}
            visiting.add(node_id)
            result = {}
            node = by_id.get(node_id)
            for required_id in (node or {}).get("requires", []):
                result.update(root_ancestry(required_id, visiting))
            visiting.remove(node_id)
            ancestry_cache[node_id] = result
            return result

        for node in tree["nodes"]:
            ancestry = root_ancestry(node["id"])
            node["branch_roots"] = sorted(ancestry)
            node["branch_types"] = sorted(
                set(ancestry.values()), key=lambda value: branch_order[value]
            )
            if node["branch_types"]:
                nodes_with_branches += 1

    return typed_roots, nodes_with_branches


def _po_value(lines: list[str], key: str) -> str | None:
    """Read one possibly multi-line string from a gettext PO block."""
    def decode_quoted(value: str) -> str:
        body = value[1:-1]
        escapes = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}
        return re.sub(r'\\([\\"nrt])', lambda match: escapes[match.group(1)], body)

    for index, line in enumerate(lines):
        if not line.startswith(key + " "):
            continue
        parts = [line[len(key) + 1 :].strip()]
        for continuation in lines[index + 1 :]:
            if not continuation.startswith('"'):
                break
            parts.append(continuation.strip())
        if any(
            len(part) < 2 or not part.startswith('"') or not part.endswith('"')
            for part in parts
        ):
            return None
        return "".join(decode_quoted(part) for part in parts)
    return None


def load_localizations(localization_archive: Path) -> dict[str, str]:
    """Read the game's English names once for units, soldiers, and weapons."""
    if not localization_archive.is_file():
        raise RuntimeError(f"Localization archive not found: {localization_archive}")

    localized: dict[str, str] = {}
    with ZipFile(localization_archive) as archive:
        for path in archive.namelist():
            if not path.endswith(".pot"):
                continue
            text = archive.read(path).decode("utf-8", errors="replace")
            for block in re.split(r"\r?\n\s*\r?\n", text):
                lines = block.splitlines()
                context = _po_value(lines, "msgctxt")
                message = _po_value(lines, "msgid")
                if context and message:
                    localized.setdefault(context, message)
    return localized


def annotate_localized_names(trees: list[dict], localized: dict[str, str]) -> tuple[int, int, int]:
    """Replace internal identifiers with localized names and infantry levels."""
    # A few soldier localization keys capitalize aliases (for example Officer).
    human_contexts = {
        context.casefold(): context
        for context in localized
        if context.startswith("desc/human/")
    }
    name_count = 0
    level_count = 0
    member_name_count = 0
    color_tag = re.compile(r"<c\([^)]*\)>(.*?)</c>", re.IGNORECASE)
    level_prefix = re.compile(
        r"^\s*<c\([^)]*\)>\(\s*([0-9]+(?:\+)?)\s*\)</c>\s*",
        re.IGNORECASE,
    )
    for tree in trees:
        for node in tree["nodes"]:
            unit = node.get("unit") or {}
            # The actual breed is authoritative: declaration aliases can point
            # at a different period or nation than the soldier in this roster.
            for member in node.get("members") or []:
                breed_path = (member.get("breed_file") or {}).get("path")
                declaration_id = (member.get("declaration") or {}).get("id")
                member_contexts = []
                if breed_path:
                    breed_id = str(PurePosixPath(breed_path).with_suffix(""))
                    member_contexts.append(
                        "desc/human/" + breed_id.removeprefix("set/breed/")
                    )
                if declaration_id:
                    member_contexts.append(f"desc/human/{declaration_id}")
                context = next(
                    (human_contexts[key.casefold()] for key in member_contexts
                     if key.casefold() in human_contexts), None
                )
                member["display_name"] = member.get("alias") or "Unknown soldier"
                member["localization_context"] = context
                if context:
                    member["display_name"] = color_tag.sub(
                        lambda match: match.group(1), localized[context]
                    ).strip()
                    member_name_count += 1
                for item in (member.get("breed_file") or {}).get("inventory_items") or []:
                    item_id = re.sub(
                        r"\s+(?:weapon|grenade)$", "", str(item.get("item") or ""),
                        flags=re.IGNORECASE,
                    )
                    weapon_name = localized.get(f"desc/weapon/{item_id}")
                    if weapon_name:
                        item["display_name"] = color_tag.sub(
                            lambda match: match.group(1), weapon_name
                        ).strip()

            vehicle_message = localized.get(f"desc/entity/{unit.get('vehicle')}")
            node["vehicle_display_name"] = (
                color_tag.sub(lambda match: match.group(1), vehicle_message).strip()
                if vehicle_message else None
            )
            definition_type = str(unit.get("definition_type") or "")
            node_id = node["id"]
            plain_id = re.sub(r"\([^)]+\)$", "", node_id)
            squad_contexts = [f"desc/squad/{node_id}"]
            if unit.get("name_token") and unit.get("side"):
                squad_contexts.append(f"desc/squad/{unit['name_token']}({unit['side']})")
            entity_contexts = [f"desc/entity/{node_id}", f"desc/entity/{plain_id}"]
            if definition_type.startswith("squad") and definition_type != "squad_vehicle":
                candidates = squad_contexts + entity_contexts
            else:
                candidates = entity_contexts + squad_contexts
            candidates.extend(
                [
                    f"main_menu2/dynamic_campaign/{node_id}",
                    f"main_menu2/dynamic_campaign/{plain_id}",
                ]
            )
            message = next(
                (localized[context] for context in candidates if context in localized),
                None,
            )
            node["localization_context"] = next(
                (context for context in candidates if context in localized), None
            )
            node["unit_level"] = None
            node["unit_level_label"] = None
            if not message:
                continue

            level_match = level_prefix.match(message)
            if level_match:
                node["unit_level_label"] = level_match.group(1)
                node["unit_level"] = int(re.match(r"\d+", level_match.group(1)).group())
                message = message[level_match.end() :]
                level_count += 1
            display_name = color_tag.sub(lambda match: match.group(1), message).strip()
            if display_name:
                node["display_name"] = display_name
                name_count += 1

    return name_count, level_count, member_name_count


def _named_parenthesized_blocks(text: str, prefix: str) -> dict[str, str]:
    """Extract balanced parenthesized blocks following a named prefix."""
    blocks = {}
    for match in re.finditer(re.escape(prefix) + r'"([^"]+)"', text):
        start = match.start()
        depth = 0
        for index in range(start, len(text)):
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    blocks[match.group(1)] = text[start : index + 1]
                    break
    return blocks


def vehicle_speed(definition_text: str) -> float | None:
    """Return road speed in km/h from the first vehicle mobility block."""
    # Parentheses in semicolon comments are prose, not part of the game syntax.
    definition_text = re.sub(r";[^\r\n]*", "", definition_text)
    for match in re.finditer(r'\("mobility_[^"]+"', definition_text):
        depth = 0
        for index in range(match.start(), len(definition_text)):
            if definition_text[index] == "(":
                depth += 1
            elif definition_text[index] == ")":
                depth -= 1
                if depth == 0:
                    block = definition_text[match.start() : index + 1]
                    speed_match = re.search(
                        r"\bspeed\s*\(\s*([0-9.]+)\s*\)", block, re.IGNORECASE
                    )
                    if speed_match:
                        return float(speed_match.group(1))
                    break
    return None


def brace_section(text: str, name: str) -> str:
    """Read a balanced named section from a game definition."""
    match = re.search(r'\{' + re.escape(name) + r'\b', text, re.IGNORECASE)
    if not match:
        return ""
    depth = 0
    for index in range(match.start(), len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.start():index + 1]
    return ""


def annotate_unit_speeds(trees: list[dict], game_files: GameFiles) -> None:
    """Use vehicle road speed or the slowest soldier's maximum sprint speed."""
    with ZipFile(game_files.properties_archive) as properties:
        human = properties.read("properties/human.ext").decode("utf-8", errors="replace")
    human = re.sub(r";[^\r\n]*", "", human)
    running = brace_section(brace_section(human, "Chassis"), "Run")
    fast = re.search(r'\{Fast\s+([0-9.]+)', running, re.IGNORECASE)
    if not fast:
        raise RuntimeError("Could not resolve infantry sprint speed from properties/human.ext")
    base_speed = float(fast.group(1))

    with ZipFile(game_files.game_logic_archive) as archive:
        presets = {}
        for path in archive.namelist():
            if path.startswith("set/breed/presets/perks/") and path.endswith(".inc"):
                text = archive.read(path).decode("utf-8", errors="replace")
                text = re.sub(r";[^\r\n]*", "", text)
                presets.update(_named_parenthesized_blocks(text, '(define '))

        def expand_perks(text: str, active: frozenset = frozenset()) -> str:
            def replace(match: re.Match) -> str:
                name = match.group(1)
                if name not in presets or name in active:
                    return match.group(0)
                return expand_perks(presets[name], active | {name})
            return re.sub(r'\("([^"\n]+)"\)', replace, text)

        speeds = {}
        for tree in trees:
            for node in tree["nodes"]:
                member_speeds = []
                for member in node.get("members") or []:
                    path = (member.get("breed_file") or {}).get("path")
                    if path and path not in speeds:
                        text = archive.read(path).decode("utf-8", errors="replace")
                        perks = expand_perks(brace_section(re.sub(r";[^\r\n]*", "", text), "perks"))
                        modifiers = re.findall(r'\{\s*"?speed"?\s+([0-9.]+)\s*\}', perks)
                        multiplier = float(modifiers[-1]) if modifiers else 1.0
                        speeds[path] = round(base_speed * multiplier, 2)
                    member["unit_speed_kmh"] = speeds.get(path)
                    if member.get("count", 0) > 0 and member["unit_speed_kmh"] is not None:
                        member_speeds.append(member["unit_speed_kmh"])

                node["unit_speed_kmh"] = node.get("vehicle_speed_kmh")
                node["unit_speed_basis"] = "Road speed" if node["unit_speed_kmh"] is not None else None
                unit = node.get("unit") or {}
                definition_type = str(unit.get("definition_type") or "")
                on_foot = (
                    definition_type.startswith("squad")
                    and not definition_type.startswith("squad_vehicle")
                    and not unit.get("vehicle")
                )
                if node["unit_speed_kmh"] is None and on_foot and member_speeds:
                    node["unit_speed_kmh"] = min(member_speeds)
                    node["unit_speed_basis"] = "Sprint speed (slowest member)"


def armor_thickness(definition_text: str) -> tuple[float | None, float | None]:
    """Return the best front-armor estimate and maximum armor value."""
    front = [
        float(value)
        for value in re.findall(
            r"\{front\s+([0-9.]+)\s*\}", definition_text, re.IGNORECASE
        )
    ]
    thickness = [
        float(value)
        for value in re.findall(
            r"\{thickness\s+([0-9.]+)", definition_text, re.IGNORECASE
        )
    ]
    shields = [
        float(value)
        for value in re.findall(
            r'\("shield(?:_group)?"\s+args\s+"[^"]+"\s+([0-9.]+)',
            definition_text,
            re.IGNORECASE,
        )
    ]
    fallback_front = max(thickness + shields, default=None)
    return (
        max(front) if front else fallback_front,
        max(front + thickness + shields, default=None),
    )


def classify_unit(
    unit: dict,
    definition_paths: list[str],
    *,
    indirect_fire: bool,
    at_cannon: bool,
) -> str:
    """Map game-specific definitions to the viewer's broad filter classes."""
    definition_type = str(unit.get("definition_type") or "")
    if at_cannon:
        return "at-cannon"
    if indirect_fire:
        return "artillery"
    if definition_type.startswith("squad") and definition_type != "squad_vehicle":
        return "infantry"
    if any("/tank_" in path for path in definition_paths):
        return "tanks"
    return "other"


def annotate_member_weapons(member: dict, weapon_categories: dict[str, str]) -> None:
    """List carried weapons, preferring the soldier's icon role as the main one."""
    breed = member.get("breed_file") or {}
    weapons = []
    seen = set()
    for item in breed.get("inventory_items") or []:
        item_id = re.sub(
            r"\s+weapon$", "", str(item.get("item") or ""), flags=re.IGNORECASE
        ).lower()
        category = weapon_categories.get(item_id)
        if category and item_id not in seen:
            weapons.append((item.get("display_name") or item["item"], category, item_id))
            seen.add(item_id)

    preferred_categories = {
        "rifle": {"rifle"}, "autorifle": {"rifle", "mgun"},
        "sniper": {"rifle"}, "riflegrenade": {"rifle"},
        "atrifle": {"rifle"}, "smg": {"smg"}, "stg": {"smg", "rifle"},
        "mg": {"mgun"}, "bazooka": {"bazooka"}, "flamer": {"flame"},
        "pistol": {"pistol"},
    }.get(breed.get("icon_id"), set())
    main_index = next(
        (index for index, (_, category, item_id) in enumerate(weapons)
         if category in preferred_categories and "grenade_launcher" not in item_id), 0
    )
    if weapons:
        weapons.insert(0, weapons.pop(main_index))
    member["main_weapon"] = weapons[0][0] if weapons else None
    member["secondary_weapon"] = weapons[1][0] if len(weapons) > 1 else None
    member["other_weapons"] = [name for name, _, _ in weapons[2:]]


def inventory_types(
    item_names: list[str],
    anti_tank_grenades: set[str],
    anti_personnel_grenades: set[str],
) -> list[str]:
    """Normalize faction-specific inventory IDs into useful filter categories."""
    found = set()
    for item_name in item_names:
        name = item_name.lower()
        normalized_name = re.sub(
            r"\s+(?:weapon|grenade)$", "", name, flags=re.IGNORECASE
        )
        words = set(re.findall(r"[a-z0-9]+", name))

        if name.startswith("shovel"):
            found.add("shovel")
        if name.startswith("binocular"):
            found.add("binoculars")
        if name == "mine_detector":
            found.add("mine-detector")
        if name == "wirecutters":
            found.add("wire-cutters")
        if name == "pickaxe":
            found.add("pickaxe")
        if re.search(r"(?:tnt|dynamite|satchel_charge|geballteladung_3kg)", name):
            found.add("demolition-charge")
        if normalized_name in anti_tank_grenades:
            found.add("anti-tank-grenade")
        if normalized_name in anti_personnel_grenades:
            found.add("anti-personnel-grenade")

        if name in {"s mine", "pmd mine", "mine m2"} or name.startswith("mine ap_"):
            found.add("anti-personnel-mine")
        if (
            name in {"m39 mine", "mine m1a1", "tm_41 mine", "tmd_b mine", "tmi_35 mine"}
            or name.startswith("mine at_")
            or name.startswith("at_gs_")
        ):
            found.add("anti-tank-mine")

        if "smoke" in words:
            found.add("smoke")
        if "wp" in words or name.startswith("no76_ic"):
            found.add("incendiary-wp")
        if name.startswith("molotov"):
            found.add("molotov-cocktail")
        if "body_armor" in name:
            found.add("body-armour")
        if "radio" in words:
            found.add("radio")
        if name.startswith("flaregun"):
            found.add("flare-gun")
        if "knife" in words or "bayonet" in words:
            found.add("knife-bayonet")

    return [inventory_type for inventory_type in INVENTORY_TYPES if inventory_type in found]


def annotate_infantry_capabilities(
    node: dict,
    at_hand_weapons: set[str],
    anti_tank_grenades: set[str],
    anti_personnel_grenades: set[str],
) -> None:
    """Detect equipment and specialist roles carried by an infantry unit."""
    node["anti_tank_weapon_count"] = 0
    node["has_shovel"] = False
    node["has_scout"] = False
    node["has_sniper"] = False
    node["weapon_roles"] = []
    node["infantry_weapons"] = []
    node["specialist_types"] = []
    node["inventory_types"] = []
    if node["unit_class"] != "infantry":
        return

    weapon_roles = set()
    infantry_weapons = set()
    specialist_types = set()
    carried_inventory = set()
    for member in node.get("members") or []:
        if int(member.get("count") or 0) > 0:
            infantry_weapons.update(
                weapon for weapon in [
                    member.get("main_weapon"), member.get("secondary_weapon"),
                    *(member.get("other_weapons") or []),
                ] if weapon
            )
        alias = str(member.get("alias") or "").lower()
        declaration = member.get("declaration") or {}
        breed = member.get("breed_file") or {}
        role_class = str(
            declaration.get("role_class")
            or member.get("command_point_role_class")
            or ""
        ).lower()
        icon_id = str(breed.get("icon_id") or "").lower()
        inventory = breed.get("inventory_items") or []
        perks = {
            str(perk).lower()
            for perk in breed.get("perks") or []
        }
        item_names = [str(item.get("item") or "") for item in inventory]
        carried_inventory.update(item_names)
        weapon_role = WEAPON_ROLE_BY_ICON.get(icon_id)
        if weapon_role:
            weapon_roles.add(weapon_role)

        if any(re.match(r"^shovel(?:_|$)", name, re.IGNORECASE) for name in item_names):
            node["has_shovel"] = True

        scout_alias = re.search(r"(?:^|_)(?:scout|recon|recce|pathfinder)(?:_|$)", alias)
        if scout_alias or any(re.fullmatch(r"tier\d+_recon", perk) for perk in perks):
            node["has_scout"] = True
            specialist_types.add("recon")

        true_sniper = (
            role_class == "inf_sniper"
            or icon_id == "sniper"
            or bool(re.search(r"(?:^|_)sniper(?:_|$)", alias))
        )
        if true_sniper:
            node["has_sniper"] = True
            specialist_types.add("sniper")
        elif "marksman" in perks or "sniper_vision" in perks:
            specialist_types.add("marksman")

        if "engineer" in perks or "engineer_heavy_fin" in perks:
            specialist_types.add("engineer")
        if role_class == "inf_medic" or "medic" in perks:
            specialist_types.add("medic")
        if role_class == "inf_officer":
            specialist_types.add("officer")
        if role_class == "inf_tankman" or "tankman" in perks:
            specialist_types.add("tank-crew")
        if "tank_commander" in perks:
            specialist_types.update(("tank-crew", "tank-commander"))
        if "skilled_repair" in perks:
            specialist_types.add("repair-specialist")
        if re.search(r"(?:^|_)(?:radio|signal|signaller)(?:_|$)", alias):
            specialist_types.add("radio-operator")

        normalized_items = {
            re.sub(r"\s+(?:weapon|grenade)$", "", name, flags=re.IGNORECASE).lower()
            for name in item_names
        }
        if normalized_items & at_hand_weapons:
            node["anti_tank_weapon_count"] += int(member.get("count") or 0)

    node["weapon_roles"] = sorted(weapon_roles)
    node["infantry_weapons"] = sorted(infantry_weapons)
    node["specialist_types"] = sorted(specialist_types)
    node["inventory_types"] = inventory_types(
        sorted(carried_inventory), anti_tank_grenades, anti_personnel_grenades
    )


def annotate_unit_metadata(
    trees: list[dict], vehicle_archive: Path, gamelogic_archive: Path,
    localized: dict[str, str],
) -> tuple[int, int, int, int, int]:
    """Add indirect fire, primary reload time, and broad unit class metadata."""
    if not vehicle_archive.is_file():
        raise RuntimeError(f"Vehicle archive not found: {vehicle_archive}")
    if not gamelogic_archive.is_file():
        raise RuntimeError(f"Game-logic archive not found: {gamelogic_archive}")

    marker = re.compile(
        r"(?:artillery|indirect)_minimap|abm_dymamic_mortar|\{props[^}]*\"mortar\"",
        re.IGNORECASE,
    )
    at_cannon_marker = re.compile(r'\"(?:detect_atgun|sq_at_gun)\"', re.IGNORECASE)
    indirect_count = 0
    reload_count = 0
    armor_count = 0
    caliber_count = 0
    speed_count = 0
    with ZipFile(vehicle_archive) as archive, ZipFile(gamelogic_archive) as gamelogic:
        archive_names = set(archive.namelist())
        definitions: dict[str, list[str]] = defaultdict(list)
        for name in archive_names:
            if name.endswith(".def"):
                definitions[PurePosixPath(name).stem.lower()].append(name)

        expanded_cache: dict[str, str] = {}

        def expanded_definition(name: str, active: set[str] | None = None) -> str:
            if name in expanded_cache:
                return expanded_cache[name]
            if name not in archive_names:
                return ""
            active = set() if active is None else active
            if name in active:
                return ""
            active.add(name)
            text = archive.read(name).decode("utf-8", errors="replace")
            parts = [text]
            for include in re.findall(r'\(include\s+"([^"]+)"', text):
                if include.startswith("/"):
                    continue
                child = posixpath.normpath(str(PurePosixPath(name).parent / include))
                parts.append(expanded_definition(child, active))
            active.remove(name)
            expanded_cache[name] = "\n".join(parts)
            return expanded_cache[name]

        weapon_files: dict[str, list[str]] = defaultdict(list)
        handheld_weapon_categories: dict[str, str] = {}
        infantry_at_hand_weapons: set[str] = set()
        anti_tank_grenades: set[str] = set()
        anti_personnel_grenades: set[str] = set()
        for name in gamelogic.namelist():
            if not name.startswith("set/stuff/") or name.endswith("/"):
                continue
            basename = PurePosixPath(name).name
            for suffix in (".weapon", ".grenade"):
                if basename.endswith(suffix):
                    basename = basename[: -len(suffix)]
            weapon_files[basename.lower()].append(name)
            category = name.split("/")[2]
            is_weapon_file = PurePosixPath(name).suffix in {"", ".weapon"}
            is_handheld_category = category in {
                "rifle", "mgun", "smg", "pistol", "bazooka", "flame"
            }
            is_melee_weapon = category == "melee" and basename.startswith(("knife", "bayonet"))
            if is_weapon_file and (is_handheld_category or is_melee_weapon):
                handheld_weapon_categories[basename.lower()] = category
            if name.startswith(("set/stuff/bazooka/", "set/stuff/grenade/anti-tank grenade/")):
                infantry_at_hand_weapons.add(basename.lower())
            if name.startswith("set/stuff/grenade/anti-tank grenade/"):
                anti_tank_grenades.add(basename.lower())
            if name.startswith("set/stuff/grenade/anti-personnel grenade/"):
                anti_personnel_grenades.add(basename.lower())

        preset_blocks: dict[str, str] = {}
        for name in gamelogic.namelist():
            if name.startswith("set/stuff/") and name.endswith("/.presets"):
                preset_text = gamelogic.read(name).decode("utf-8", errors="replace")
                preset_blocks.update(_named_parenthesized_blocks(preset_text, '(define '))

        reload_pattern = re.compile(r'\("reload time"\s+seconds\(([0-9.]+)\)\)', re.IGNORECASE)

        weapon_metadata_cache: dict[str, tuple[float | None, float | None]] = {}

        def ammo_id(value: str) -> str:
            return " ".join(word for word in value.lower().split() if word != "ammo")

        ammo_names = {
            ammo_id(PurePosixPath(path).name.removesuffix(".ammo").replace(".", " "))
            for path in gamelogic.namelist() if path.endswith(".ammo")
        }
        filling_cache: dict[str, tuple[str, int | None]] = {}

        def weapon_filling(reference: str, active: frozenset = frozenset()) -> tuple[str, int | None]:
            """Resolve inherited ammo family and magazine size from the weapon."""
            if reference in filling_cache:
                return filling_cache[reference]
            if reference in active:
                return "", None
            for path in weapon_files.get(reference.lower(), []):
                text = re.sub(r";[^\r\n]*", "", gamelogic.read(path).decode(errors="replace"))
                filling = re.search(r'\{filling\s+"([^"]+)"(?:\s+(\d+))?\s*\}', text)
                parent = re.search(r'\{from\s+"([^"]+)"', text)
                inherited = ("", None)
                if parent:
                    parent_id = parent.group(1)
                    if parent_id.startswith("pattern "):
                        parent_id = parent_id.removeprefix("pattern ") + ".pattern"
                    inherited = weapon_filling(parent_id, active | {reference})
                result = (
                    ammo_id(filling.group(1)),
                    int(filling.group(2)) if filling.group(2) else inherited[1],
                ) if filling else inherited
                filling_cache[reference] = result
                return result
            return "", None

        def vehicle_ammunition(text: str, reference: str) -> list[dict]:
            """Match carried ammo to a gun, keeping loaded and spare counts apart."""
            family, capacity = weapon_filling(reference)
            loaded: dict[str, int] = defaultdict(int)
            for match in re.finditer(
                r'\{(?:weapon|item)\s+"' + re.escape(reference)
                + r'"\s+(?:filling\s+"([^"]+)"\s+(\d+)|(filled)\b)', text
            ):
                if match.group(1):
                    loaded[ammo_id(match.group(1))] += int(match.group(2))
                elif family and capacity is not None:
                    loaded[family] += capacity

            families = {family} if family else set()
            # Explicit ammunition also handles weapons whose default filling
            # is defined by an engine pattern rather than a readable file.
            for value in loaded:
                if not any(value == key or value.startswith(key + " ") for key in families):
                    families.add(value)
            spare = {}
            for match in re.finditer(r'\{item\s+"([^"]+)"\s+(\d+)\s*\}', text):
                key = ammo_id(match.group(1))
                is_ammo = key in ammo_names or "ammo" in match.group(1).lower().split()
                if is_ammo and any(key == f or key.startswith(f + " ") for f in families):
                    # Expanded includes follow the concrete definition; retain
                    # its explicit count when a base definition repeats it.
                    spare.setdefault(key, int(match.group(2)))

            result = []
            for key in dict.fromkeys([*spare, *loaded]):
                name = localized.get(f"desc/ammo/{key}") or localized.get(f"desc/stuff/{key}") or key
                name = re.sub(r"<c\([^)]*\)>(.*?)</c>", r"\1", name)
                result.append({
                    "id": key, "display_name": name,
                    "spare_count": spare.get(key, 0), "loaded_count": loaded.get(key, 0),
                    "total_count": spare.get(key, 0) + loaded.get(key, 0),
                })
            return result

        def weapon_metadata(
            reference: str, active: set[str] | None = None
        ) -> tuple[float | None, float | None]:
            reference = re.sub(r"^weapon\s+", "", reference.strip(), flags=re.IGNORECASE)
            cache_key = reference.lower()
            if cache_key in weapon_metadata_cache:
                return weapon_metadata_cache[cache_key]
            active = set() if active is None else active
            if cache_key in active:
                return None, None
            active.add(cache_key)

            for weapon_path in weapon_files.get(reference.lower(), []):
                text = gamelogic.read(weapon_path).decode("utf-8", errors="replace")
                direct = reload_pattern.search(text)
                reload_time = float(direct.group(1)) if direct else None
                calibre_match = re.search(r"\{calibre\s+([0-9.]+)\s*\}", text, re.IGNORECASE)
                calibre = float(calibre_match.group(1)) if calibre_match else None

                if reload_time is None:
                    for invocation in re.findall(r'\("([^"]+)"\)', text):
                        preset = preset_blocks.get(invocation)
                        preset_reload = reload_pattern.search(preset or "")
                        if preset_reload:
                            reload_time = float(preset_reload.group(1))
                            break
                from_match = re.search(r'\{from\s+"([^"]+)"', text)
                if from_match:
                    parent_reference = from_match.group(1)
                    if parent_reference.startswith("pattern "):
                        parent_reference = parent_reference.removeprefix("pattern ") + ".pattern"
                    parent_reload, parent_calibre = weapon_metadata(parent_reference, active)
                    reload_time = reload_time if reload_time is not None else parent_reload
                    calibre = calibre if calibre is not None else parent_calibre
                result = (reload_time, calibre)
                weapon_metadata_cache[cache_key] = result
                active.remove(cache_key)
                return result

            active.remove(cache_key)
            weapon_metadata_cache[cache_key] = (None, None)
            return None, None

        for tree in trees:
            for node in tree["nodes"]:
                unit = node.get("unit") or {}
                for member in node.get("members") or []:
                    annotate_member_weapons(member, handheld_weapon_categories)
                    for item in (member.get("breed_file") or {}).get("inventory_items") or []:
                        item_id = re.sub(
                            r"\s+grenade$", "", str(item.get("item") or ""),
                            flags=re.IGNORECASE,
                        ).lower()
                        item["is_anti_tank_grenade"] = item_id in anti_tank_grenades
                lookup_ids = []
                if unit.get("vehicle"):
                    lookup_ids.append(unit["vehicle"])
                lookup_ids.append(re.sub(r"\([^)]+\)$", "", node["id"]))

                definition_paths = []
                for lookup_id in lookup_ids:
                    definition_paths.extend(definitions.get(lookup_id.lower(), []))
                definition_paths = list(dict.fromkeys(definition_paths))
                definition_text = "\n".join(expanded_definition(path) for path in definition_paths)
                node["indirect_fire"] = bool(marker.search(definition_text))
                node["at_cannon"] = bool(at_cannon_marker.search(definition_text))
                if node["indirect_fire"]:
                    indirect_count += 1

                weapon_text = re.sub(r";[^\r\n]*", "", definition_text)
                weapon_references = re.findall(r'\{weapon\s+"([^"]+)"', weapon_text)
                # Some vehicles mount inventory weapons rather than naming
                # them directly in a weaponry slot (for example the Dingo).
                weapon_references.extend(re.findall(
                    r'\{item\s+"([^"]+)"[^{}]*\{user\s+"[^"]+"\}', weapon_text
                ))
                weapon_references = list(dict.fromkeys(
                    reference for reference in weapon_references
                    if any(
                        not path.startswith("set/stuff/special/")
                        for path in weapon_files.get(reference.lower(), [])
                    )
                ))
                weapon_options = [
                    (reference, *weapon_metadata(reference)) for reference in weapon_references
                ]
                caliber_options = [option for option in weapon_options if option[2] is not None]
                selected_weapon = (
                    max(caliber_options, key=lambda option: option[2])
                    if caliber_options
                    else (weapon_options[0] if weapon_options else (None, None, None))
                )
                ordered_weapons = sorted(
                    weapon_options, key=lambda option: option[0] != selected_weapon[0]
                )
                node["vehicle_weapons"] = []
                for reference, reload_time, caliber in ordered_weapons:
                    name = localized.get(f"desc/weapon/{reference}", reference)
                    name = re.sub(r"<c\([^)]*\)>(.*?)</c>", r"\1", name)
                    node["vehicle_weapons"].append({
                        "id": reference, "display_name": name,
                        "caliber_mm": caliber, "reload_time_seconds": reload_time,
                        "ammunition": vehicle_ammunition(weapon_text, reference),
                    })
                for weapon in node["vehicle_weapons"]:
                    for ammo in weapon["ammunition"]:
                        ammo["shared_reserve"] = ammo["spare_count"] > 0 and sum(
                            any(other_ammo["id"] == ammo["id"] for other_ammo in other["ammunition"])
                            for other in node["vehicle_weapons"]
                        ) > 1
                node["primary_weapon"] = (
                    node["vehicle_weapons"][0]["display_name"]
                    if node["vehicle_weapons"] else None
                )
                node["reload_time"] = selected_weapon[1]
                node["main_gun_caliber_mm"] = selected_weapon[2]
                if node["reload_time"] is not None:
                    reload_count += 1
                if node["main_gun_caliber_mm"] is not None:
                    caliber_count += 1

                node["vehicle_speed_kmh"] = vehicle_speed(definition_text)
                if node["vehicle_speed_kmh"] is not None:
                    speed_count += 1

                (
                    node["front_armor_thickness_mm"],
                    node["maximum_armor_thickness_mm"],
                ) = armor_thickness(definition_text)
                if node["front_armor_thickness_mm"] is not None:
                    armor_count += 1

                node["unit_class"] = classify_unit(
                    unit,
                    definition_paths,
                    indirect_fire=node["indirect_fire"],
                    at_cannon=node["at_cannon"],
                )

                node["infantry_level"] = (
                    node.get("unit_level") if node["unit_class"] == "infantry" else None
                )
                node["infantry_level_label"] = (
                    node.get("unit_level_label") if node["unit_class"] == "infantry" else None
                )
                annotate_infantry_capabilities(
                    node,
                    infantry_at_hand_weapons,
                    anti_tank_grenades,
                    anti_personnel_grenades,
                )

    return indirect_count, reload_count, armor_count, caliber_count, speed_count


def convert_images(trees: list[dict], input_dir: Path, output_dir: Path) -> tuple[int, list[str]]:
    """Convert exported TGA/PNG assets into browser-compatible PNG files."""
    assets_dir = output_dir / "assets"
    converted = 0
    missing = []

    for tree in trees:
        faction = tree["faction"]
        faction_dir = assets_dir / safe_filename(faction)
        faction_dir.mkdir(parents=True, exist_ok=True)

        for node in tree["nodes"]:
            node["web_image"] = None
            image_info = node.get("image")
            relative_source = image_info.get("path") if image_info else None
            if not relative_source:
                missing.append(f"{faction}/{node['id']} (no exported image)")
                continue

            source = (input_dir / relative_source).resolve()
            try:
                source.relative_to(input_dir.resolve())
            except ValueError:
                raise RuntimeError(f"Image path escapes the export directory: {relative_source}")
            if not source.is_file():
                missing.append(f"{faction}/{node['id']} ({relative_source})")
                continue

            target_name = f"{safe_filename(node['id'])}.png"
            target = faction_dir / target_name
            try:
                with Image.open(source) as image:
                    image.convert("RGBA").save(target, format="PNG", optimize=True)
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"Could not convert {source}: {exc}") from exc

            node["web_image"] = f"assets/{safe_filename(faction)}/{target_name}"
            converted += 1

    return converted, missing


def write_html(trees: list[dict], output_dir: Path) -> Path:
    """Embed all research data in a single portable HTML document."""
    # Prevent data from accidentally terminating its enclosing script element.
    embedded_json = json.dumps(trees, ensure_ascii=False, separators=(",", ":"))
    embedded_json = (
        embedded_json.replace("</", "<\\/")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    html = HTML_TEMPLATE.replace("__TREE_DATA__", embedded_json)
    target = output_dir / "index.html"
    target.write_text(html, encoding="utf-8")
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an interactive HTML view of exported Gates of Hell research trees.",
        epilog=(
            "Example: ./create_research_tree_html.py "
            "'/home/user/.local/share/Steam/steamapps/common/Call to Arms - Gates of Hell/resource'"
        ),
    )
    parser.add_argument(
        "game_path",
        type=Path,
        help=(
            "required path to the game's resource directory "
            "(the directory containing gamelogic.pak)"
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"directory containing faction JSON and images (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory to replace with the generated site (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    game_resource_dir = args.game_path.resolve()
    input_dir = args.input.resolve()
    output_dir = args.output.resolve()
    game_files = GameFiles.from_game_directory(game_resource_dir)
    missing_files = [str(path) for path in game_files.missing()]
    if missing_files:
        raise RuntimeError(f"Required game file(s) not found: {', '.join(missing_files)}")
    if not input_dir.is_dir():
        raise RuntimeError(
            f"Input directory does not exist: {input_dir}. "
            "Run export_research_trees.py first."
        )
    if output_dir in (input_dir, game_resource_dir, SCRIPT_DIR):
        raise RuntimeError(
            "Output directory must differ from the input and game resource directories"
        )

    trees = load_trees(input_dir)
    root_count, branch_node_count = annotate_research_branches(trees)
    log(
        f"Classified {root_count} research roots and propagated branch types "
        f"to {branch_node_count} nodes"
    )
    localized = load_localizations(game_files.localization_archive)
    localized_name_count, localized_level_count, member_name_count = annotate_localized_names(
        trees, localized
    )
    log(
        f"Resolved {localized_name_count} in-game unit names and "
        f"{localized_level_count} localized unit levels"
    )
    log(f"Resolved in-game names for {member_name_count} roster member entries")
    (
        indirect_count,
        reload_count,
        armor_count,
        caliber_count,
        speed_count,
    ) = annotate_unit_metadata(
        trees, game_files.vehicle_archive, game_files.game_logic_archive, localized
    )
    log(
        f"Detected indirect-fire capability on {indirect_count} research nodes "
        "from game entity definitions"
    )
    log(f"Resolved primary-weapon reload time for {reload_count} research nodes")
    log(f"Resolved frontal armor thickness for {armor_count} research nodes")
    log(f"Resolved main-gun caliber for {caliber_count} research nodes")
    log(f"Resolved vehicle road speed for {speed_count} research nodes")
    annotate_unit_speeds(trees, game_files)
    unit_speed_count = sum(
        node["unit_speed_kmh"] is not None for tree in trees for node in tree["nodes"]
    )
    log(f"Resolved unit movement speed for {unit_speed_count} research nodes")
    if output_dir.exists():
        old_files = sum(1 for path in output_dir.rglob("*") if path.is_file())
        log(f"Removing existing {output_dir} ({old_files} files)")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    converted, missing = convert_images(trees, input_dir, output_dir)
    log(f"Converted {converted} node images to browser-compatible PNG files")
    if missing:
        log(f"WARNING: {len(missing)} nodes have no usable image")
        for item in missing[:20]:
            log(f"  {item}")
        if len(missing) > 20:
            log(f"  ...and {len(missing) - 20} more")

    html_path = write_html(trees, output_dir)
    node_count = sum(len(tree["nodes"]) for tree in trees)
    log(f"Wrote {html_path} with {len(trees)} factions and {node_count} nodes")
    log(f"Open file://{html_path} in a browser")


HTML_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gates of Hell Research Trees</title>
<style>
:root { color-scheme: dark; --panel: #171b1d; --line: #6d7779; --accent: #e0ad4f; --required: #67c7f4; }
* { box-sizing: border-box; }
html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; background: #0c0f10; color: #e9ecea; font: 14px/1.4 system-ui, sans-serif; }
button, select, input { color: inherit; background: #252b2e; border: 1px solid #596164; border-radius: 5px; padding: 7px 10px; }
button { cursor: pointer; }
button:hover { background: #343c40; }
#toolbar { height: 54px; display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #171b1d; border-bottom: 1px solid #343a3d; }
#toolbar h1 { font-size: 17px; margin: 0 14px 0 0; white-space: nowrap; }
#search { width: min(260px, 24vw); }
#hint { margin-left: auto; color: #9ca6a8; font-size: 12px; }
#filter-panel { position: absolute; z-index: 12; left: 0; top: 54px; bottom: 0; width: 300px; padding: 14px 13px 24px; overflow-y: auto; background: #121617f7; border-right: 1px solid #343a3d; transition: transform .2s; }
body.filters-collapsed #filter-panel { transform: translateX(-100%); }
#filter-toggle { position: absolute; z-index: 13; left: 300px; top: 66px; width: 31px; padding: 7px 5px; border-left: 0; border-radius: 0 5px 5px 0; transition: left .2s; }
body.filters-collapsed #filter-toggle { left: 0; }
.filter-heading { margin: 0 0 10px; font-size: 16px; }
.filter-group { margin: 0 0 14px; padding: 10px; border: 1px solid #343a3d; border-radius: 6px; }
.filter-group > summary { color: #e0ad4f; font-weight: 700; cursor: pointer; }
.filter-group[open] > summary { margin-bottom: 10px; }
.filter-group > label { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 7px 0; color: #b8c0c2; }
.filter-group input[type="number"] { width: 92px; }
.filter-group input[type="checkbox"] { width: auto; accent-color: #36a96c; }
#filter-count { color: #75daa5; font-weight: 650; }
.multi-filter { margin: 8px 0; }
.multi-filter summary { padding: 7px 9px; border: 1px solid #596164; border-radius: 5px; background: #252b2e; cursor: pointer; }
.multi-options { max-height: 250px; overflow: auto; padding: 6px 4px 2px 12px; }
.multi-options label { display: flex; align-items: center; gap: 7px; padding: 4px; color: #b8c0c2; }
.branch-group { margin: 5px 0 2px; color: #e0ad4f; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.multi-options label:hover { background: #2b3336; border-radius: 3px; }
#clear-filters { width: 100%; margin: 2px 0 9px; }
#viewport { position: absolute; inset: 54px 0 0 300px; overflow: hidden; cursor: grab; background-color: #0d1112; background-image: radial-gradient(#303638 1px, transparent 1px); background-size: 24px 24px; transition: left .2s; }
body.stats-open #viewport { right: var(--stats-width, 560px); }
body.filters-collapsed #viewport { left: 0; }
#viewport.dragging { cursor: grabbing; }
#world { position: absolute; left: 0; top: 0; transform-origin: 0 0; }
#edges { position: absolute; inset: 0; overflow: visible; pointer-events: none; }
.edge { stroke: var(--line); stroke-width: 3; fill: none; opacity: .7; }
.edge.highlight { stroke: var(--required); stroke-width: 5; opacity: 1; }
.edge.dimmed { opacity: .12; }
.node { position: absolute; width: 150px; height: 184px; border: 2px solid #687174; border-radius: 7px; overflow: hidden; background: #22282a; box-shadow: 0 3px 8px #0009; cursor: pointer; user-select: none; transition: opacity .15s, border-color .15s, box-shadow .15s; }
.node:hover { border-color: #f0d28a; box-shadow: 0 0 12px #e0ad4f88; z-index: 3; }
.node.tech { border-color: #9a7d3d; }
.node img { width: 100%; height: 142px; object-fit: contain; display: block; background: #101314; }
.node .no-image { height: 142px; display: grid; place-items: center; color: #697174; font-size: 28px; }
.node-title { height: 40px; display: flex; align-items: center; padding: 3px 6px; font-size: 12px; font-weight: 650; line-height: 1.15; background: #1b2022; }
.badges { position: absolute; right: 4px; bottom: 44px; display: flex; gap: 3px; }
.badge { padding: 2px 5px; background: #111d; border: 1px solid #aaa8; border-radius: 4px; font-size: 11px; font-weight: 800; }
.badge-icon { width: 14px; height: 14px; margin-right: 3px; vertical-align: -3px; }
.badge.units { color: #aee4ff; }
.lower-left-badges { position: absolute; left: 4px; bottom: 44px; display: flex; gap: 3px; }
.cp-badge, .reload-badge, .at-count-badge { padding: 2px 5px; color: #ffe2a1; background: #111d; border: 1px solid #aaa8; border-radius: 4px; font-size: 11px; font-weight: 800; }
.cp-badge { color: #bde7ff; }
.at-count-badge { color: #ffb0a4; }
.infantry-level { position: absolute; left: 5px; top: 5px; padding: 3px 6px; color: #d9efff; background: #111d; border: 1px solid #8bcfffaa; border-radius: 5px; font-size: 11px; font-weight: 800; z-index: 1; }
.shovel-icon { position: absolute; left: 5px; top: 34px; width: 28px; height: 28px; display: grid; place-items: center; color: #d6e2c0; background: #111d; border: 1px solid #b7ce91aa; border-radius: 5px; z-index: 1; }
.shovel-icon svg { width: 20px; height: 20px; }
.indirect-icon { position: absolute; right: 5px; top: 5px; width: 31px; height: 27px; display: grid; place-items: center; color: #ffd36a; background: #111d; border: 1px solid #ffd36aaa; border-radius: 5px; z-index: 1; }
.indirect-icon svg { width: 24px; height: 20px; overflow: visible; }
.scout-icon, .sniper-icon { position: absolute; right: 5px; width: 31px; height: 27px; display: grid; place-items: center; background: #111d; border-radius: 5px; z-index: 1; }
.scout-icon { top: 36px; color: #8fe7c1; border: 1px solid #8fe7c1aa; }
.sniper-icon { top: 67px; color: #ff9fa4; border: 1px solid #ff9fa4aa; }
.scout-icon svg, .sniper-icon svg { width: 21px; height: 21px; }
.node.selected { border-color: var(--accent); box-shadow: 0 0 18px #e0ad4fcc; z-index: 4; }
.node.required { border-color: var(--required); box-shadow: 0 0 13px #67c7f499; z-index: 2; }
.node.dimmed { opacity: .2; }
.node.search-match { outline: 4px solid #d65cff; outline-offset: 2px; }
.node.filter-match { background: #24563d; border-color: #73e4aa; box-shadow: 0 0 15px #50d79499; }
.node.filter-match .node-title { background: #24563d; }
#details { position: absolute; z-index: 11; top: 54px; bottom: 0; right: 0; width: var(--stats-width, 560px); display: flex; flex-direction: column; padding: 0 0 0 7px; color: inherit; background: #171b1d; border-left: 1px solid #495154; box-shadow: -5px 0 18px #0006; overflow: hidden; }
#details[hidden] { display: none; }
#stats-resize { position: absolute; left: 0; top: 0; bottom: 0; width: 7px; cursor: col-resize; touch-action: none; background: #495154; }
#stats-resize:hover, #stats-resize:focus-visible { background: var(--accent); }
body.resizing-stats { cursor: col-resize; user-select: none; }
.stats-window-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 18px; border-bottom: 1px solid #495154; }
.stats-window-header h2 { margin: 0; font-size: 17px; }
#detail-content { min-height: 0; overflow: auto; padding: 10px 18px 24px; }
#close-details { font-size: 20px; padding: 2px 10px; }
.detail-head { display: flex; gap: 14px; align-items: flex-start; margin: 8px 0 14px; }
.detail-head img { width: 112px; height: 140px; object-fit: cover; border: 1px solid #626a6c; border-radius: 5px; }
.detail-head h2 { margin: 0 0 5px; font-size: 21px; }
.muted { color: #9ea7a9; overflow-wrap: anywhere; }
.totals { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin: 12px 0; }
.total { padding: 8px; background: #252b2e; border-radius: 5px; text-align: center; }
.total strong { display: block; font-size: 18px; color: #f0c873; }
.stat-section { margin-top: 18px; }
.stat-section > summary { cursor: pointer; font-size: 1.17em; font-weight: 700; padding-bottom: 4px; border-bottom: 1px solid #42494c; }
.stat-section[open] > summary { margin-bottom: 7px; }
.stats { display: grid; grid-template-columns: minmax(105px, .8fr) minmax(0, 1.2fr); gap: 1px; background: #343b3e; border: 1px solid #343b3e; }
.stats dt, .stats dd { margin: 0; padding: 5px 7px; background: #202527; overflow-wrap: anywhere; }
.stats dt { color: #aeb7b9; }
.comparison-scroll { max-width: 100%; overflow: auto; margin: 8px 0; border: 1px solid #495154; }
.comparison { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 12px; }
.comparison th, .comparison td { min-width: 175px; max-width: 260px; padding: 7px 9px; vertical-align: top; text-align: left; overflow-wrap: anywhere; background: #202527; border-right: 1px solid #42494c; border-bottom: 1px solid #42494c; }
.comparison thead th { background: #30383b; color: #9edcff; }
.comparison th:first-child { position: sticky; left: 0; z-index: 1; min-width: 155px; width: 175px; background: #272e30; }
.comparison .comparison-section th { position: static; background: #343e41; color: #f0c873; }
.comparison .chips { display: block; }
.comparison .chip { display: inline-block; margin: 0 3px 4px 0; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { background: #30383b; border-radius: 10px; padding: 2px 7px; font-size: 12px; }
.notice { padding: 9px; border-left: 3px solid #db9b45; background: #3b2d1c; margin: 10px 0; }
html[data-theme="light"] { color-scheme: light; --line: #697477; --accent: #9b6300; --required: #0879ac; }
html[data-theme="light"] body { background: #e9eeea; color: #182022; }
html[data-theme="light"] #toolbar { background: #f8faf7; border-color: #b9c1bd; }
html[data-theme="light"] #filter-panel { background: #f1f5f1f7; border-color: #b9c1bd; }
html[data-theme="light"] .filter-group { border-color: #b9c1bd; }
html[data-theme="light"] .filter-group > label, html[data-theme="light"] .multi-options label { color: #4f5b5d; }
html[data-theme="light"] .multi-filter summary { background: #fff; border-color: #8b9799; }
html[data-theme="light"] .multi-options label:hover { background: #e4e9e6; }
html[data-theme="light"] button, html[data-theme="light"] select, html[data-theme="light"] input { color: #182022; background: #fff; border-color: #8b9799; }
html[data-theme="light"] button:hover { background: #e4e9e6; }
html[data-theme="light"] #viewport { background-color: #e5ebe7; background-image: radial-gradient(#aeb9b5 1px, transparent 1px); }
html[data-theme="light"] .node { background: #fff; border-color: #687477; box-shadow: 0 3px 8px #3444; }
html[data-theme="light"] .node img, html[data-theme="light"] .node .no-image { background: #dce2de; }
html[data-theme="light"] .node-title { background: #f7f9f6; }
html[data-theme="light"] .badge, html[data-theme="light"] .cp-badge, html[data-theme="light"] .reload-badge, html[data-theme="light"] .at-count-badge, html[data-theme="light"] .infantry-level, html[data-theme="light"] .shovel-icon, html[data-theme="light"] .indirect-icon, html[data-theme="light"] .scout-icon, html[data-theme="light"] .sniper-icon { background: #fffE; border-color: #5e676a99; color: #4d642d; }
html[data-theme="light"] .cp-badge { color: #005b86; }
html[data-theme="light"] .badge.units { color: #005b86; }
html[data-theme="light"] .node.filter-match, html[data-theme="light"] .node.filter-match .node-title { background: #bcebcf; border-color: #16824a; }
html[data-theme="light"] #details { background: #f8faf7; border-color: #aab4b1; box-shadow: -5px 0 18px #4554; }
html[data-theme="light"] .stats-window-header { border-color: #aab4b1; }
html[data-theme="light"] .muted { color: #626e70; }
html[data-theme="light"] .total { background: #e4e9e6; }
html[data-theme="light"] .total strong { color: #754900; }
html[data-theme="light"] .stats { background: #b9c3c0; border-color: #b9c3c0; }
html[data-theme="light"] .stats dt, html[data-theme="light"] .stats dd { background: #f2f5f1; }
html[data-theme="light"] .stats dt { color: #596466; }
html[data-theme="light"] .comparison-scroll { border-color: #b8c1be; }
html[data-theme="light"] .comparison th, html[data-theme="light"] .comparison td { background: #f2f5f1; border-color: #b8c1be; }
html[data-theme="light"] .comparison thead th, html[data-theme="light"] .comparison th:first-child { background: #e4e9e6; color: #28546a; }
html[data-theme="light"] .comparison .comparison-section th { background: #dce3df; color: #754900; }
html[data-theme="light"] .chip { background: #dce3df; }
html[data-theme="light"] .notice { background: #fff0d4; }
@media (max-width: 1000px) { #hint { display: none; } }
@media (max-width: 760px) { #filter-panel { width: min(300px, 86vw); } #filter-toggle { left: min(300px, 86vw); } #viewport { left: 0; } #toolbar h1 { display: none; } }
</style>
</head>
<body>
<header id="toolbar">
  <h1>Research Trees</h1>
  <select id="faction" aria-label="Faction"></select>
  <input id="search" type="search" placeholder="Find a unit…" aria-label="Find a unit">
  <button id="zoom-out" title="Zoom out">−</button>
  <button id="zoom-in" title="Zoom in">+</button>
  <button id="fit">Fit tree</button>
  <button id="clear">Clear highlighting</button>
  <button id="theme" aria-label="Toggle light and dark mode">☀ Light mode</button>
  <span id="hint">Drag to pan · wheel to zoom · click a node for details</span>
</header>
<button id="filter-toggle" title="Collapse filters" aria-label="Collapse filters" aria-expanded="true">‹</button>
<aside id="filter-panel">
  <h2 class="filter-heading">Show</h2>
  <details class="filter-group" id="branch-filter">
    <summary id="branch-summary">Research branches: All</summary>
    <div class="multi-options" id="branch-options" role="group" aria-label="Research branches"></div>
  </details>
  <h2 class="filter-heading">Highlight filters</h2>
  <details class="filter-group" id="general-filter" open>
    <summary>General</summary>
    <label title="Minimum maximum movement speed: infantry sprint or vehicle road speed">Unit speed (km/h) <input id="min-unit-speed" type="number" min="0" step="1" placeholder="Any"></label>
    <label>Min unit size <input id="min-size" type="number" min="0" step="1" placeholder="Any"></label>
    <label>Max reload (s) <input id="max-reload" type="number" min="0" step="0.1" placeholder="Any"></label>
    <label>Max command points <input id="max-cp" type="number" min="0" step="1" placeholder="Any"></label>
  </details>
  <details class="filter-group" id="infantry-filter">
    <summary>Infantry</summary>
    <label>Min unit level <input id="min-level" type="number" min="0" step="1" placeholder="Any"></label>
    <label>Min AT weapons <input id="min-infantry-at" type="number" min="0" step="1" placeholder="Any"></label>
    <details class="multi-filter" id="inventory-filter">
      <summary id="inventory-summary">Inventory: All</summary>
      <div class="multi-options" id="inventory-options" role="group" aria-label="Inventory"></div>
    </details>
    <details class="multi-filter" id="weapon-role-filter">
      <summary id="weapon-role-summary">Weapon roles: All</summary>
      <div class="multi-options" id="weapon-role-options" role="group" aria-label="Weapon roles"></div>
    </details>
    <details class="multi-filter" id="infantry-weapon-filter">
      <summary id="infantry-weapon-summary">Infantry weapons: All</summary>
      <div class="multi-options" id="infantry-weapon-options" role="group" aria-label="Infantry weapons"></div>
    </details>
    <details class="multi-filter" id="specialist-filter">
      <summary id="specialist-summary">Specialist types: All</summary>
      <div class="multi-options" id="specialist-options" role="group" aria-label="Specialist types"></div>
    </details>
  </details>
  <details class="filter-group" id="vehicles-filter">
    <summary>Vehicles and guns</summary>
    <label>Min front armour (mm) <input id="min-front-armor" type="number" min="0" step="0.1" placeholder="Any"></label>
    <label>Min gun calibre (mm) <input id="min-caliber" type="number" min="0" step="0.1" placeholder="Any"></label>
    <label><span>Indirect fire</span><input id="has-indirect-fire" type="checkbox"></label>
  </details>
  <button id="clear-filters">Clear filters</button>
  <div id="filter-count"></div>
</aside>
<main id="viewport"><div id="world"><svg id="edges"></svg><div id="nodes"></div></div></main>
<aside id="details" aria-labelledby="stats-window-title" hidden>
  <div id="stats-resize" role="separator" aria-label="Resize statistics panel" aria-orientation="vertical" tabindex="0" aria-controls="details"></div>
  <header class="stats-window-header">
    <h2 id="stats-window-title">Unit statistics</h2>
    <button id="close-details" title="Close statistics (Esc)" aria-label="Close statistics">×</button>
  </header>
  <div id="detail-content"></div>
</aside>
<script id="tree-data" type="application/json">__TREE_DATA__</script>
<script>
(() => {
  const trees = JSON.parse(document.getElementById('tree-data').textContent);
  const NODE_W = 150, NODE_H = 184, STEP_X = 184, STEP_Y = 202, PAD = 50;
  const viewport = document.getElementById('viewport');
  const world = document.getElementById('world');
  const edgesLayer = document.getElementById('edges');
  const nodesLayer = document.getElementById('nodes');
  const details = document.getElementById('details');
  const detailContent = document.getElementById('detail-content');
  const statsResize = document.getElementById('stats-resize');
  let selectedNodeId = null, statsWidth = 560, statsDrag = null;
  const factionSelect = document.getElementById('faction');
  const themeButton = document.getElementById('theme');
  const minSizeInput = document.getElementById('min-size');
  const minLevelInput = document.getElementById('min-level');
  const minInfantryAtInput = document.getElementById('min-infantry-at');
  const minUnitSpeedInput = document.getElementById('min-unit-speed');
  const minFrontArmorInput = document.getElementById('min-front-armor');
  const minCaliberInput = document.getElementById('min-caliber');
  const maxReloadInput = document.getElementById('max-reload');
  const maxCpInput = document.getElementById('max-cp');
  const hasIndirectFireInput = document.getElementById('has-indirect-fire');
  const inventoryOptions = document.getElementById('inventory-options');
  const inventorySummary = document.getElementById('inventory-summary');
  const weaponRoleOptions = document.getElementById('weapon-role-options');
  const weaponRoleSummary = document.getElementById('weapon-role-summary');
  const infantryWeaponOptions = document.getElementById('infantry-weapon-options');
  const infantryWeaponSummary = document.getElementById('infantry-weapon-summary');
  const specialistOptions = document.getElementById('specialist-options');
  const specialistSummary = document.getElementById('specialist-summary');
  const branchOptions = document.getElementById('branch-options');
  const branchSummary = document.getElementById('branch-summary');
  const filterCount = document.getElementById('filter-count');
  let tree, byId, nodeElements, edgeElements, layoutPositions, worldWidth, worldHeight;
  let scale = 1, tx = 0, ty = 0, dragging = false, dragStart, panMoved = false;

  const esc = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const label = key => key.replaceAll('_', ' ').replace(/\b\w/g, ch => ch.toUpperCase());
  const shown = value => value !== null && value !== undefined && value !== '' && (!Array.isArray(value) || value.length);
  const number = value => Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));

  function sectionStorageKey(section, group) {
    return `research-tree-sections:${group}:${section.dataset.stateKey || section.id}`;
  }

  function saveSectionStates(container, group) {
    for (const section of container.querySelectorAll('details')) {
      try { localStorage.setItem(sectionStorageKey(section, group), String(section.open)); } catch (_) {}
    }
  }

  function restoreSectionStates(container, group) {
    for (const section of container.querySelectorAll('details')) {
      const key = sectionStorageKey(section, group);
      try {
        const saved = localStorage.getItem(key);
        if (saved === 'true' || saved === 'false') section.open = saved === 'true';
      } catch (_) {}
      section.addEventListener('toggle', () => {
        // Replacing the selected unit can leave a queued toggle on old markup.
        if (!section.isConnected) return;
        try { localStorage.setItem(key, String(section.open)); } catch (_) {}
      });
    }
  }
  restoreSectionStates(document.getElementById('filter-panel'), 'filters');

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    themeButton.textContent = theme === 'dark' ? '☀ Light mode' : '☾ Dark mode';
    try { localStorage.setItem('research-tree-theme', theme); } catch (_) {}
  }
  let initialTheme = 'dark';
  try { initialTheme = localStorage.getItem('research-tree-theme') || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'); } catch (_) {}
  applyTheme(initialTheme);

  for (const item of trees) {
    const option = document.createElement('option');
    option.value = item.faction;
    option.textContent = item.faction.toUpperCase();
    factionSelect.append(option);
  }

  const weaponRoleLabels = {
    'rifle': 'Rifle', 'submachine-gun': 'Submachine gun',
    'automatic-rifle': 'Automatic rifle', 'assault-rifle': 'Assault rifle',
    'machine-gun': 'Machine gun', 'at-launcher': 'AT launcher',
    'at-rifle': 'Anti-tank rifle', 'flamethrower': 'Flamethrower',
    'sniper-rifle': 'Sniper rifle', 'pistol': 'Pistol',
    'shotgun': 'Shotgun', 'rifle-grenade': 'Rifle grenade',
  };
  const specialistLabels = {
    'recon': 'Scout / recon', 'sniper': 'Sniper', 'marksman': 'Scoped marksman',
    'engineer': 'Engineer / sapper', 'medic': 'Medic', 'officer': 'Officer',
    'tank-crew': 'Tank crew', 'tank-commander': 'Tank commander',
    'repair-specialist': 'Repair specialist', 'radio-operator': 'Radio operator',
  };
  const inventoryLabels = {
    'shovel': 'Shovel', 'binoculars': 'Binoculars',
    'mine-detector': 'Mine detector', 'wire-cutters': 'Wire cutters',
    'pickaxe': 'Pickaxe', 'demolition-charge': 'Demolition charge',
    'anti-tank-grenade': 'Anti-tank grenade',
    'anti-personnel-grenade': 'Anti-personnel grenade',
    'anti-personnel-mine': 'Anti-personnel mine', 'anti-tank-mine': 'Anti-tank mine',
    'smoke': 'Smoke grenade', 'incendiary-wp': 'Incendiary / WP item',
    'molotov-cocktail': 'Molotov cocktail', 'body-armour': 'Body armour',
    'radio': 'Radio', 'flare-gun': 'Flare gun', 'knife-bayonet': 'Knife / bayonet',
  };

  function populateOptions(container, labels, property, sourceTrees = trees) {
    const available = new Set();
    for (const item of sourceTrees) for (const node of item.nodes) {
      for (const value of node[property] || []) available.add(value);
    }
    for (const [value, optionLabel] of Object.entries(labels)) {
      if (!available.has(value)) continue;
      const option = document.createElement('label');
      option.innerHTML = `<input type="checkbox" value="${esc(value)}"> ${esc(optionLabel)}`;
      container.append(option);
    }
  }
  populateOptions(inventoryOptions, inventoryLabels, 'inventory_types');
  populateOptions(weaponRoleOptions, weaponRoleLabels, 'weapon_roles');
  populateOptions(specialistOptions, specialistLabels, 'specialist_types');
  let infantryWeaponLabels = {};

  function updateInfantryWeaponOptions() {
    const selected = selectedValues(infantryWeaponOptions);
    const names = [...new Set(tree.nodes.flatMap(node => node.infantry_weapons || []))]
      .sort((a, b) => a.localeCompare(b));
    infantryWeaponLabels = Object.fromEntries(names.map(name => [name, name]));
    infantryWeaponOptions.replaceChildren();
    populateOptions(infantryWeaponOptions, infantryWeaponLabels, 'infantry_weapons', [tree]);
    for (const input of infantryWeaponOptions.querySelectorAll('input')) {
      input.checked = selected.has(input.value);
    }
    updateFilterSummaries();
  }

  const branchDefinitions = new Map();
  for (const item of trees) for (const node of item.nodes) {
    if (node.branch_type && !branchDefinitions.has(node.branch_type)) {
      branchDefinitions.set(node.branch_type, {
        type: node.branch_type,
        label: node.branch_label,
        group: node.branch_group,
      });
    }
  }
  const branchGroups = ['Infantry', 'Support weapons', 'Vehicles'];
  for (const group of branchGroups) {
    const definitions = [...branchDefinitions.values()].filter(item => item.group === group);
    if (!definitions.length) continue;
    const heading = document.createElement('div');
    heading.className = 'branch-group';
    heading.textContent = group;
    branchOptions.append(heading);
    for (const definition of definitions) {
      const option = document.createElement('label');
      option.innerHTML = `<input type="checkbox" value="${esc(definition.type)}"> ${esc(definition.label)}`;
      branchOptions.append(option);
    }
  }

  function selectedBranchTypes() {
    return selectedValues(branchOptions);
  }

  function selectedValues(container) {
    return new Set([...container.querySelectorAll('input:checked')].map(input => input.value));
  }

  function updateMultiSummary(container, summary, prefix, labels) {
    const selected = selectedValues(container);
    if (!selected.size) summary.textContent = `${prefix}: All`;
    else if (selected.size === 1) summary.textContent = labels[[...selected][0]];
    else summary.textContent = `${prefix}: ${selected.size} selected`;
  }

  function updateBranchSummary() {
    const selected = selectedBranchTypes();
    if (!selected.size) {
      branchSummary.textContent = 'Research branches: All';
    } else if (selected.size === 1) {
      branchSummary.textContent = branchDefinitions.get([...selected][0]).label;
    } else {
      branchSummary.textContent = `Research branches: ${selected.size} selected`;
    }
  }

  function updateFilterSummaries() {
    updateMultiSummary(infantryWeaponOptions, infantryWeaponSummary, 'Infantry weapons', infantryWeaponLabels);
    updateMultiSummary(inventoryOptions, inventorySummary, 'Inventory', inventoryLabels);
    updateMultiSummary(weaponRoleOptions, weaponRoleSummary, 'Weapon roles', weaponRoleLabels);
    updateMultiSummary(specialistOptions, specialistSummary, 'Specialist types', specialistLabels);
    updateBranchSummary();
  }

  function setTransform() { world.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`; }
  function originalNodePosition(node) { return { x: PAD + node.position.x * STEP_X, y: PAD + node.position.y * STEP_Y }; }
  function nodePosition(node) { return layoutPositions?.get(node.id) || originalNodePosition(node); }

  function renderTree(faction) {
    tree = trees.find(item => item.faction === faction);
    updateInfantryWeaponOptions();
    byId = new Map(tree.nodes.map(node => [node.id, node]));
    layoutPositions = new Map(
      tree.nodes.map(node => [node.id, originalNodePosition(node)])
    );
    nodeElements = new Map(); edgeElements = [];
    nodesLayer.replaceChildren(); edgesLayer.replaceChildren();
    const maxX = Math.max(...tree.nodes.map(n => n.position.x));
    const maxY = Math.max(...tree.nodes.map(n => n.position.y));
    worldWidth = PAD * 2 + maxX * STEP_X + NODE_W;
    worldHeight = PAD * 2 + maxY * STEP_Y + NODE_H;
    world.style.width = worldWidth + 'px'; world.style.height = worldHeight + 'px';
    edgesLayer.setAttribute('width', worldWidth); edgesLayer.setAttribute('height', worldHeight);
    edgesLayer.setAttribute('viewBox', `0 0 ${worldWidth} ${worldHeight}`);

    for (const node of tree.nodes) {
      const p = nodePosition(node);
      for (const requiredId of node.requires) {
        const required = byId.get(requiredId);
        if (!required) continue;
        const rp = nodePosition(required);
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        const x1 = rp.x + NODE_W / 2, y1 = rp.y + NODE_H / 2;
        const x2 = p.x + NODE_W / 2, y2 = p.y + NODE_H / 2;
        const mid = (y1 + y2) / 2;
        path.setAttribute('d', `M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`);
        path.setAttribute('class', 'edge');
        edgesLayer.append(path);
        edgeElements.push({ element: path, from: requiredId, to: node.id });
      }

      const card = document.createElement('article');
      card.className = `node ${node.node_type}`;
      card.style.left = p.x + 'px'; card.style.top = p.y + 'px';
      card.title = `${node.display_name}\nResearch: ${number(node.cost)}${shown(node.stats?.unit_count) ? `\nUnits: ${node.stats.unit_count}` : ''}`;
      const image = node.web_image ? `<img src="${esc(node.web_image)}" alt="">` : '<div class="no-image">?</div>';
      const unitBadge = shown(node.stats?.unit_count) ? `<span class="badge units" title="Amount of units">×${esc(node.stats.unit_count)}</span>` : '';
      const commandPoints = node.unit?.cp;
      const helmetIcon = '<svg class="badge-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 15a8 8 0 0 1 16 0v3H4z" fill="currentColor"/><path d="M3 18h18M12 7v8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
      const flaskIcon = '<svg class="badge-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6M10 3v6l-5.2 8.7A2.2 2.2 0 0 0 6.7 21h10.6a2.2 2.2 0 0 0 1.9-3.3L14 9V3M7.4 16h9.2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
      const cpBadge = shown(commandPoints) ? `<span class="cp-badge" title="Command points">${helmetIcon}${esc(number(commandPoints))}</span>` : '';
      const reloadBadge = shown(node.reload_time) ? `<span class="reload-badge" title="Primary weapon reload time">↻ ${esc(number(node.reload_time))}s</span>` : '';
      const infantryLevel = shown(node.infantry_level_label) ? `<span class="infantry-level" title="In-game infantry level">Lv ${esc(node.infantry_level_label)}</span>` : '';
      const shovelIcon = node.unit_class === 'infantry' && node.has_shovel ? '<span class="shovel-icon" title="Infantry carries a shovel" aria-label="Infantry carries a shovel"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3 Q12 0 16 3 L14 7 H10 Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 7 V17" stroke="currentColor" stroke-width="2"/><path d="M9 21 L12 17 L15 21 Z" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg></span>' : '';
      const scoutIcon = node.unit_class === 'infantry' && node.has_scout ? '<span class="scout-icon" title="Infantry unit includes scouts" aria-label="Infantry unit includes scouts"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg></span>' : '';
      const sniperIcon = node.unit_class === 'infantry' && node.has_sniper ? '<span class="sniper-icon" title="Infantry unit includes a sniper or scoped marksman" aria-label="Infantry unit includes a sniper"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 2v6m0 8v6M2 12h6m8 0h6" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="2" fill="currentColor"/></svg></span>' : '';
      const atWeaponBadge = node.anti_tank_weapon_count > 0 ? `<span class="at-count-badge" title="Infantry carrying AT launchers or AT hand grenades">AT ×${esc(node.anti_tank_weapon_count)}</span>` : '';
      const lowerLeftBadges = cpBadge || reloadBadge || atWeaponBadge ? `<div class="lower-left-badges">${cpBadge}${reloadBadge}${atWeaponBadge}</div>` : '';
      const indirectIcon = node.indirect_fire ? '<span class="indirect-icon" title="Indirect fire capability" aria-label="Indirect fire capability"><svg viewBox="0 0 24 20" aria-hidden="true"><path d="M2 17 Q8 2 18 7" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="2 2"/><path d="M15 4 L20 7 L16 11" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="3" cy="17" r="2" fill="currentColor"/></svg></span>' : '';
      card.innerHTML = `${image}${infantryLevel}${shovelIcon}${indirectIcon}${scoutIcon}${sniperIcon}${lowerLeftBadges}<div class="badges"><span class="badge" title="Research points needed">${flaskIcon}${esc(number(node.cost))}</span>${unitBadge}</div><div class="node-title">${esc(node.display_name)}</div>`;
      card.addEventListener('click', event => { event.stopPropagation(); selectNode(node.id); });
      nodesLayer.append(card); nodeElements.set(node.id, card);
    }
    clearHighlighting();
    applyFilters();
    requestAnimationFrame(startView);
  }

  function updateGraphLayout(visibleIds = null) {
    const visibleNodes = tree.nodes.filter(node => !visibleIds || visibleIds.has(node.id));
    const compact = visibleIds !== null;
    const visibleRows = [...new Set(visibleNodes.map(node => node.position.y))].sort((a, b) => a - b);
    const compactRow = new Map(visibleRows.map((row, index) => [row, index]));

    layoutPositions = new Map();
    for (const node of tree.nodes) {
      const visible = !visibleIds || visibleIds.has(node.id);
      nodeElements.get(node.id).style.display = visible ? '' : 'none';
      if (!visible) continue;
      const position = {
        x: PAD + node.position.x * STEP_X,
        y: PAD + (compact ? compactRow.get(node.position.y) : node.position.y) * STEP_Y,
      };
      layoutPositions.set(node.id, position);
      const element = nodeElements.get(node.id);
      element.style.left = position.x + 'px';
      element.style.top = position.y + 'px';
    }

    for (const edge of edgeElements) {
      const from = layoutPositions.get(edge.from);
      const to = layoutPositions.get(edge.to);
      edge.element.style.display = from && to ? '' : 'none';
      if (!from || !to) continue;
      const x1 = from.x + NODE_W / 2, y1 = from.y + NODE_H / 2;
      const x2 = to.x + NODE_W / 2, y2 = to.y + NODE_H / 2;
      const mid = (y1 + y2) / 2;
      edge.element.setAttribute('d', `M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2}`);
    }

    const positions = [...layoutPositions.values()];
    worldWidth = Math.max(PAD * 2 + NODE_W, ...positions.map(position => position.x + NODE_W + PAD));
    worldHeight = Math.max(PAD * 2 + NODE_H, ...positions.map(position => position.y + NODE_H + PAD));
    world.style.width = worldWidth + 'px'; world.style.height = worldHeight + 'px';
    edgesLayer.setAttribute('width', worldWidth); edgesLayer.setAttribute('height', worldHeight);
    edgesLayer.setAttribute('viewBox', `0 0 ${worldWidth} ${worldHeight}`);
  }

  function applyFilters() {
    if (!tree || !nodeElements) return;
    const hasMinSize = minSizeInput.value !== '';
    const hasMinLevel = minLevelInput.value !== '';
    const hasMinInfantryAt = minInfantryAtInput.value !== '';
    const hasMinUnitSpeed = minUnitSpeedInput.value !== '';
    const hasMinFrontArmor = minFrontArmorInput.value !== '';
    const hasMinCaliber = minCaliberInput.value !== '';
    const hasMaxReload = maxReloadInput.value !== '';
    const hasMaxCp = maxCpInput.value !== '';
    const indirectFireOnly = hasIndirectFireInput.checked;
    const selectedInventory = selectedValues(inventoryOptions);
    const selectedWeaponRoles = selectedValues(weaponRoleOptions);
    const selectedInfantryWeapons = selectedValues(infantryWeaponOptions);
    const selectedSpecialists = selectedValues(specialistOptions);
    const active = hasMinSize || hasMinLevel || hasMinInfantryAt || hasMinUnitSpeed || hasMinFrontArmor || hasMinCaliber || hasMaxReload || hasMaxCp || indirectFireOnly || selectedInventory.size || selectedWeaponRoles.size || selectedInfantryWeapons.size || selectedSpecialists.size;
    const minSize = Number(minSizeInput.value);
    const minLevel = Number(minLevelInput.value);
    const minInfantryAt = Number(minInfantryAtInput.value);
    const minUnitSpeed = Number(minUnitSpeedInput.value);
    const minFrontArmor = Number(minFrontArmorInput.value);
    const minCaliber = Number(minCaliberInput.value);
    const maxReload = Number(maxReloadInput.value);
    const maxCp = Number(maxCpInput.value);
    const matchingIds = new Set();
    for (const [id, element] of nodeElements) {
      const node = byId.get(id);
      const unitSize = node.stats?.unit_count;
      const unitLevel = node.unit_level;
      const infantryAt = node.anti_tank_weapon_count;
      const unitSpeed = node.unit_speed_kmh;
      const frontArmor = node.front_armor_thickness_mm;
      const caliber = node.main_gun_caliber_mm;
      const reload = node.reload_time;
      const commandPoints = node.unit?.cp;
      const match = active
        && (!hasMinSize || (unitSize !== null && unitSize !== undefined && unitSize >= minSize))
        && (!hasMinLevel || (unitLevel !== null && unitLevel !== undefined && unitLevel >= minLevel))
        && (!hasMinInfantryAt || (node.unit_class === 'infantry' && infantryAt >= minInfantryAt))
        && (!hasMinUnitSpeed || (unitSpeed !== null && unitSpeed !== undefined && unitSpeed >= minUnitSpeed))
        && (!hasMinFrontArmor || (frontArmor !== null && frontArmor !== undefined && frontArmor >= minFrontArmor))
        && (!hasMinCaliber || (caliber !== null && caliber !== undefined && caliber >= minCaliber))
        && (!hasMaxReload || (reload !== null && reload !== undefined && reload <= maxReload))
        && (!hasMaxCp || (commandPoints !== null && commandPoints !== undefined && commandPoints <= maxCp))
        && (!indirectFireOnly || node.indirect_fire)
        && (!selectedInventory.size || (node.inventory_types || []).some(type => selectedInventory.has(type)))
        && (!selectedWeaponRoles.size || (node.weapon_roles || []).some(role => selectedWeaponRoles.has(role)))
        && (!selectedInfantryWeapons.size || (node.infantry_weapons || []).some(weapon => selectedInfantryWeapons.has(weapon)))
        && (!selectedSpecialists.size || (node.specialist_types || []).some(type => selectedSpecialists.has(type)));
      element.classList.toggle('filter-match', match);
      if (match) matchingIds.add(id);
    }
    const selectedBranches = selectedBranchTypes();
    if (selectedBranches.size) {
      const branchNodes = tree.nodes.filter(node =>
        (node.branch_types || []).some(branchType => selectedBranches.has(branchType))
      );
      const visibleIds = new Set(branchNodes.map(node => node.id));
      for (const node of branchNodes) {
        const id = node.id;
        for (const requiredId of prerequisiteSet(id)) visibleIds.add(requiredId);
      }
      updateGraphLayout(visibleIds);
      const matchText = active ? `${matchingIds.size} matches · ` : '';
      filterCount.textContent = `${matchText}${visibleIds.size} branch nodes shown`;
    } else {
      updateGraphLayout();
      filterCount.textContent = active ? `${matchingIds.size} matching nodes` : '';
    }
  }

  function prerequisiteSet(nodeId) {
    const found = new Set(), visiting = new Set();
    function visit(id) {
      if (visiting.has(id)) return;
      visiting.add(id);
      const node = byId.get(id);
      if (node) for (const requiredId of node.requires) {
        if (byId.has(requiredId) && !found.has(requiredId)) { found.add(requiredId); visit(requiredId); }
      }
      visiting.delete(id);
    }
    visit(nodeId); return found;
  }

  function selectNode(nodeId) {
    selectedNodeId = nodeId;
    const node = byId.get(nodeId), required = prerequisiteSet(nodeId);
    const active = new Set(required); active.add(nodeId);
    for (const [id, element] of nodeElements) {
      element.classList.toggle('selected', id === nodeId);
      element.classList.toggle('required', required.has(id));
      element.classList.toggle('dimmed', !active.has(id));
    }
    for (const edge of edgeElements) {
      const highlighted = active.has(edge.from) && active.has(edge.to);
      edge.element.classList.toggle('highlight', highlighted);
      edge.element.classList.toggle('dimmed', !highlighted);
    }
    renderDetails(node, required);
    detailContent.scrollTop = 0;
    details.hidden = false;
    document.body.classList.add('stats-open');
    resizeStatsPanel(statsWidth);
  }

  function clearHighlighting() {
    selectedNodeId = null;
    for (const element of nodeElements?.values() || []) element.classList.remove('selected', 'required', 'dimmed');
    for (const edge of edgeElements || []) edge.element.classList.remove('highlight', 'dimmed');
    closeStatsPanel();
  }

  function closeStatsPanel() {
    details.hidden = true;
    document.body.classList.remove('stats-open');
  }

  const hiddenStatFields = new Set([
    'id', 'definition_type', 'cp_source', 'position_x', 'position_y',
    'source_asset', 'portrait_id', 'icon_id', 'path', 'skin'
  ]);

  function statRows(object, omitted = new Set()) {
    if (!object) return '<p class="muted">None</p>';
    return '<dl class="stats">' + Object.entries(object)
      .filter(([key, value]) => !hiddenStatFields.has(key) && !omitted.has(key) && shown(value))
      .map(([key, value]) => `<dt>${esc(label(key))}</dt><dd>${formatValue(value)}</dd>`).join('') + '</dl>';
  }

  function formatValue(value) {
    if (Array.isArray(value)) return `<div class="chips">${value.map(item => `<span class="chip">${typeof item === 'object' ? esc(JSON.stringify(item)) : esc(item)}</span>`).join('')}</div>`;
    if (typeof value === 'object' && value) return esc(JSON.stringify(value));
    return esc(value);
  }

  function comparisonTable(columns, sections) {
    const rows = sections.map(section => {
      const keys = [...new Set(section.values.flatMap(value => Object.keys(value || {})))];
      const visibleKeys = keys.filter(key => !hiddenStatFields.has(key)
        && section.values.some(value => shown(value?.[key])));
      if (!visibleKeys.length) return '';
      const heading = `<tr class="comparison-section"><th colspan="${columns.length + 1}">${esc(section.title)}</th></tr>`;
      return heading + visibleKeys.map(key => `<tr><th scope="row">${esc(label(key))}</th>${section.values.map(value =>
        `<td>${shown(value?.[key]) ? formatValue(value[key]) : '—'}</td>`
      ).join('')}</tr>`).join('');
    }).join('');
    return `<div class="comparison-scroll" tabindex="0" role="region" aria-label="Unit comparison"><table class="comparison"><thead><tr><th scope="col">Statistic</th>${columns.map(name => `<th scope="col">${esc(name)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  function inventoryRows(member) {
    const rows = {}, occurrences = new Map();
    for (const item of member.breed_file?.inventory_items || []) {
      const name = (item.display_name || item.item) + (item.is_anti_tank_grenade ? ' (AT)' : '');
      const occurrence = (occurrences.get(name) || 0) + 1;
      occurrences.set(name, occurrence);
      const key = name + (occurrence > 1 ? ` (${occurrence})` : '');
      rows[key] = shown(item.payload) ? item.payload : 'Carried';
    }
    return rows;
  }

  function statSection(title, content, expanded = true) {
    // Counts vary by unit; the section preference belongs to its stable name.
    const key = title.replace(/ \(\d+\)$/, '');
    return `<details class="stat-section" data-state-key="${esc(key)}"${expanded ? ' open' : ''}><summary>${esc(title)}</summary>${content}</details>`;
  }

  function memberTables(node) {
    const groups = new Map();
    for (const member of node.members || []) {
      const role = member.declaration?.role_class || member.command_point_role_class;
      const group = /^crew/.test(member.slot || '') || role === 'inf_tankman' ? 'Crew' : 'Infantry';
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(member);
    }
    return [...groups].map(([group, members]) => {
      const sections = [
        {title: 'Weapons (per soldier)', values: members.map(member => ({
          main_weapon: member.main_weapon,
          secondary_weapon: member.secondary_weapon,
          other_weapons: member.other_weapons,
        }))},
        {title: 'Inventory (per soldier)', values: members.map(inventoryRows)},
        {title: 'Composition', values: members.map(member => ({
          amount_of_units: member.count, slot: member.slot,
          sprint_speed_kmh: member.unit_speed_kmh,
          command_points_each: member.command_points_each,
          total_command_points: member.total_command_points, total_cost: member.total_cost,
        }))},
        {title: 'Soldier stats', values: members.map(member => {
          const {raw, alias, ...stats} = member.declaration || {};
          return stats;
        })},
        {title: 'Breed and abilities', values: members.map(member => {
          const {inventory_items, ...stats} = member.breed_file || {};
          return stats;
        })},
      ];
      const count = members.reduce((sum, member) => sum + Number(member.count || 0), 0);
      return statSection(`${group} (${count})`, comparisonTable(
        members.map(member => `${member.display_name || member.alias} ×${member.count}`), sections
      ));
    }).join('');
  }

  function vehicleWeaponRows(node) {
    const rows = {};
    for (const [index, weapon] of (node.vehicle_weapons || []).entries()) {
      const prefix = index === 0 ? 'primary_gun' : index === 1 ? 'secondary_gun' : `other_gun_${index - 1}`;
      rows[prefix] = weapon.display_name;
      rows[`${prefix}_caliber_mm`] = weapon.caliber_mm;
      rows[`${prefix}_reload_time_seconds`] = weapon.reload_time_seconds;
      rows[`${prefix}_ammunition`] = weapon.ammunition?.length
        ? weapon.ammunition.map(ammo => `${ammo.display_name}: ${ammo.total_count} rounds (${ammo.spare_count} spare + ${ammo.loaded_count} loaded${ammo.shared_reserve ? '; shared reserve' : ''})`)
        : 'Unknown';
    }
    return rows;
  }

  function renderDetails(node, required) {
    saveSectionStates(detailContent, 'stats');
    const allNodes = [node, ...[...required].map(id => byId.get(id)).filter(Boolean)];
    const totalCost = allNodes.reduce((sum, item) => sum + Number(item.cost || 0), 0);
    const missing = new Set();
    for (const item of allNodes) for (const id of item.requires) if (!byId.has(id)) missing.add(id);
    const image = node.web_image ? `<img src="${esc(node.web_image)}" alt="">` : '';
    const unit = node.unit;
    const {raw, members, ...unitStats} = unit || {};
    const hasVehicle = unit && (unit.vehicle || unit.definition_type?.startsWith('vehicle') || unit.definition_type?.startsWith('squad_vehicle'));
    const unitTable = unit ? comparisonTable([hasVehicle ? (node.vehicle_display_name || node.display_name) : node.display_name], [
      ...(hasVehicle ? [{title: 'Vehicle and gun stats', values: [{
        ...vehicleWeaponRows(node),
        vehicle_speed_kmh: node.vehicle_speed_kmh,
        front_armor_thickness_mm: node.front_armor_thickness_mm,
        maximum_armor_thickness_mm: node.maximum_armor_thickness_mm,
      }]}] : []),
      {title: 'Unit stats', values: [{
        unit_speed_kmh: node.unit_speed_kmh ?? 'Unknown',
        speed_basis: node.unit_speed_basis, ...unitStats,
      }]},
    ]) : '<p class="muted">No unit definition</p>';
    const requirementNames = [...required].map(id => byId.get(id)?.display_name || id);
    detailContent.innerHTML = `
      <div class="detail-head">${image}<div><h2>${esc(node.display_name)}</h2><div class="muted">${esc(node.node_type)}</div></div></div>
      <div class="totals"><div class="total"><strong>${esc(number(node.cost))}</strong>Own RP</div><div class="total"><strong>${esc(number(totalCost))}</strong>Total RP</div><div class="total"><strong>${shown(node.stats?.unit_count) ? esc(node.stats.unit_count) : '—'}</strong>Units</div></div>
      ${missing.size ? `<div class="notice">Missing prerequisite data: ${[...missing].map(esc).join(', ')}</div>` : ''}
      ${statSection('Research data', statRows({cost: node.cost}), false)}
      ${statSection('Aggregate unit stats', statRows({...node.stats, unit_class: node.unit_class, unit_level: node.unit_level_label, inventory: (node.inventory_types || []).map(type => inventoryLabels[type] || type), weapon_roles: (node.weapon_roles || []).map(role => weaponRoleLabels[role] || role), specialist_types: (node.specialist_types || []).map(type => specialistLabels[type] || type), carries_shovel: node.unit_class === 'infantry' ? (node.has_shovel ? 'Yes' : 'No') : null, includes_scout: node.unit_class === 'infantry' ? (node.has_scout ? 'Yes' : 'No') : null, includes_sniper: node.unit_class === 'infantry' ? (node.has_sniper ? 'Yes' : 'No') : null, anti_tank_equipped_infantry: node.anti_tank_weapon_count || null, at_cannon: node.at_cannon ? 'Yes' : 'No', vehicle_speed_kmh: node.vehicle_speed_kmh, front_armor_thickness_mm: node.front_armor_thickness_mm, maximum_armor_thickness_mm: node.maximum_armor_thickness_mm, primary_weapon: node.primary_weapon, main_gun_caliber_mm: node.main_gun_caliber_mm, reload_time_seconds: node.reload_time}), false)}
      ${statSection(`${hasVehicle ? 'Vehicle / gun' : 'Formation'} stats`, unitTable)}
      ${memberTables(node)}
      ${statSection('Other', statRows({indirect_fire_capability: node.indirect_fire ? 'Yes' : 'No'}))}
      ${statSection(`Unlock prerequisites (${required.size})`, requirementNames.length ? `<div class="chips">${requirementNames.map(name => `<span class="chip">${esc(name)}</span>`).join('')}</div>` : '<p class="muted">No prerequisites</p>')}`;
    restoreSectionStates(detailContent, 'stats');
  }

  function fitTree() {
    const availableWidth = viewport.clientWidth;
    const availableHeight = viewport.clientHeight;
    scale = Math.min(.8, availableWidth / worldWidth, availableHeight / worldHeight);
    scale = Math.max(.06, scale);
    tx = (availableWidth - worldWidth * scale) / 2;
    ty = Math.max(12, (availableHeight - worldHeight * scale) / 2);
    setTransform();
  }

  function startView() {
    scale = Math.max(.18, Math.min(.65, viewport.clientWidth * .92 / worldWidth));
    tx = (viewport.clientWidth - worldWidth * scale) / 2;
    ty = 20;
    setTransform();
  }

  function zoomAt(factor, cx = viewport.clientWidth / 2, cy = viewport.clientHeight / 2) {
    const next = Math.max(.05, Math.min(2.5, scale * factor));
    const wx = (cx - tx) / scale, wy = (cy - ty) / scale;
    tx = cx - wx * next; ty = cy - wy * next; scale = next; setTransform();
  }

  function keepSelectedNodeVisible() {
    if (!selectedNodeId || nodeElements.get(selectedNodeId)?.style.display === 'none') return;
    const node = byId.get(selectedNodeId);
    if (!node) return;
    const position = nodePosition(node), margin = 12;
    scale = Math.min(scale, Math.max(.05, (viewport.clientWidth - margin * 2) / NODE_W));
    const left = position.x * scale + tx, top = position.y * scale + ty;
    if (left < margin) tx += margin - left;
    else if (left + NODE_W * scale > viewport.clientWidth - margin) {
      tx -= left + NODE_W * scale - viewport.clientWidth + margin;
    }
    if (top < margin) ty += margin - top;
    else if (top + NODE_H * scale > viewport.clientHeight - margin) {
      ty -= top + NODE_H * scale - viewport.clientHeight + margin;
    }
    setTransform();
  }

  function resizeStatsPanel(width) {
    // Reserve graph space even when the filter panel is expanded.
    const max = Math.max(160, window.innerWidth - viewport.offsetLeft - 180);
    const min = Math.min(300, max);
    statsWidth = Math.max(min, Math.min(max, width));
    document.body.style.setProperty('--stats-width', `${statsWidth}px`);
    statsResize.setAttribute('aria-valuemin', min);
    statsResize.setAttribute('aria-valuemax', max);
    statsResize.setAttribute('aria-valuenow', Math.round(statsWidth));
    keepSelectedNodeVisible();
  }

  statsResize.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    statsDrag = {x: event.clientX, width: statsWidth};
    statsResize.setPointerCapture(event.pointerId);
    document.body.classList.add('resizing-stats');
    event.preventDefault();
  });
  statsResize.addEventListener('pointermove', event => {
    if (statsDrag) resizeStatsPanel(statsDrag.width + statsDrag.x - event.clientX);
  });
  function stopStatsResize() {
    statsDrag = null;
    document.body.classList.remove('resizing-stats');
  }
  statsResize.addEventListener('pointerup', stopStatsResize);
  statsResize.addEventListener('pointercancel', stopStatsResize);
  statsResize.addEventListener('lostpointercapture', stopStatsResize);
  statsResize.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    resizeStatsPanel(statsWidth + (event.key === 'ArrowLeft' ? 24 : -24));
  });

  viewport.addEventListener('wheel', event => { event.preventDefault(); const rect = viewport.getBoundingClientRect(); zoomAt(event.deltaY < 0 ? 1.12 : .89, event.clientX - rect.left, event.clientY - rect.top); }, {passive:false});
  viewport.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.target.closest('.node')) return;
    dragging = true;
    panMoved = false;
    dragStart = {x:event.clientX, y:event.clientY, tx, ty};
    viewport.classList.add('dragging');
    viewport.setPointerCapture(event.pointerId);
  });
  viewport.addEventListener('pointermove', event => {
    if (!dragging) return;
    const dx = event.clientX - dragStart.x, dy = event.clientY - dragStart.y;
    if (Math.hypot(dx, dy) > 4) panMoved = true;
    tx = dragStart.tx + dx; ty = dragStart.ty + dy; setTransform();
  });
  viewport.addEventListener('pointerup', () => {
    dragging = false;
    viewport.classList.remove('dragging');
  });
  viewport.addEventListener('pointercancel', () => {
    dragging = false;
    panMoved = false;
    viewport.classList.remove('dragging');
  });
  viewport.addEventListener('click', event => {
    if (panMoved) { panMoved = false; return; }
    if (event.target === viewport || event.target === world || event.target === nodesLayer) clearHighlighting();
  });
  factionSelect.addEventListener('change', () => renderTree(factionSelect.value));
  document.getElementById('clear').addEventListener('click', clearHighlighting);
  document.getElementById('close-details').addEventListener('click', closeStatsPanel);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !details.hidden) closeStatsPanel();
  });
  document.getElementById('fit').addEventListener('click', fitTree);
  document.getElementById('zoom-in').addEventListener('click', () => zoomAt(1.25));
  document.getElementById('zoom-out').addEventListener('click', () => zoomAt(.8));
  themeButton.addEventListener('click', () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  document.getElementById('filter-toggle').addEventListener('click', event => {
    const collapsed = document.body.classList.toggle('filters-collapsed');
    event.currentTarget.textContent = collapsed ? '›' : '‹';
    event.currentTarget.title = collapsed ? 'Expand filters' : 'Collapse filters';
    event.currentTarget.setAttribute('aria-label', event.currentTarget.title);
    event.currentTarget.setAttribute('aria-expanded', String(!collapsed));
    setTimeout(() => {
      if (details.hidden) fitTree();
      else resizeStatsPanel(statsWidth);
    }, 210);
  });
  const filterControls = [minSizeInput, minLevelInput, minInfantryAtInput, minUnitSpeedInput, minFrontArmorInput, minCaliberInput, maxReloadInput, maxCpInput, hasIndirectFireInput];
  for (const control of filterControls) control.addEventListener('input', () => {
    applyFilters();
    if (selectedBranchTypes().size) fitTree();
  });
  for (const options of [inventoryOptions, weaponRoleOptions, infantryWeaponOptions, specialistOptions]) {
    options.addEventListener('input', () => { updateFilterSummaries(); applyFilters(); });
  }
  branchOptions.addEventListener('input', () => { updateFilterSummaries(); applyFilters(); fitTree(); });
  document.getElementById('clear-filters').addEventListener('click', () => {
    for (const input of [minSizeInput, minLevelInput, minInfantryAtInput, minUnitSpeedInput, minFrontArmorInput, minCaliberInput, maxReloadInput, maxCpInput]) input.value = '';
    hasIndirectFireInput.checked = false;
    for (const input of document.querySelectorAll('.multi-options input')) input.checked = false;
    updateFilterSummaries(); applyFilters(); fitTree();
  });
  document.getElementById('search').addEventListener('input', event => {
    const query = event.target.value.trim().toLowerCase();
    for (const [id, element] of nodeElements) {
      const node = byId.get(id);
      element.classList.toggle('search-match', !!query && (id.toLowerCase().includes(query) || node.display_name.toLowerCase().includes(query)));
    }
  });
  window.addEventListener('resize', () => {
    if (details.hidden) fitTree();
    else resizeStatsPanel(statsWidth);
  });
  renderTree(trees[0].faction);
})();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print(f"[research-tree-html] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

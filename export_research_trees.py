#!/usr/bin/env python3
"""Export Gates of Hell conquest research trees from the installed game files."""

import json
import re
import shutil
import sys
from argparse import ArgumentParser
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "research_export"

# Required files, relative to the game resource directory supplied on the
# command line. Keeping these together makes game-version path changes obvious.
REQUIRED_GAME_FILES = {
    "gamelogic": Path("gamelogic.pak"),
    "interface_scene": Path("interface/scene.pak"),
    "interface_pages": Path("interface/pages.pak"),
}

RESEARCH_PATH_TEMPLATE = "set/dynamic_campaign/unit_research_{faction}.set"
ROSTER_INF_PATH_TEMPLATE = "set/multiplayer/units/conquest/inf_{faction}.set"
ROSTER_UNIT_PATH_TEMPLATE = "set/multiplayer/units/conquest/units_{faction}.set"
CONQUEST_INF_SETTINGS_PATH = "set/multiplayer/units/conquest/settings_inf.set"

# These aliases are referenced by current conquest rosters but have no matching
# declaration in their faction's inf_*.set file. Their breed perks and adjacent
# equivalent declarations identify the intended infantry role class.
INFANTRY_ROLE_CLASS_FALLBACKS = {
    "com_subsec_2ic_smg_s": "inf_tier3",
    "sapper_nco": "inf_tier2",
    "101st_eng_at_m1a1": "inf_tier4",
    "late_driver_m3": "inf_tier2",
}


@dataclass(frozen=True)
class ArchivePaths:
    """Absolute paths to the game archives used by the exporter."""

    game_logic: Path
    interface_scene: Path
    interface_pages: Path

    @classmethod
    def from_game_directory(cls, game_directory: Path) -> "ArchivePaths":
        paths = {
            name: (game_directory / relative_path).resolve()
            for name, relative_path in REQUIRED_GAME_FILES.items()
        }
        return cls(
            game_logic=paths["gamelogic"],
            interface_scene=paths["interface_scene"],
            interface_pages=paths["interface_pages"],
        )

    def all(self) -> tuple[Path, Path, Path]:
        return self.game_logic, self.interface_scene, self.interface_pages


def log(message: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(f"[research-export] {message}", flush=True)


def discover_factions(gamelogic_zip: ZipFile) -> list[str]:
    pattern = re.compile(r"set/dynamic_campaign/unit_research_([A-Za-z0-9_]+)\.set")
    return sorted(
        match.group(1)
        for name in gamelogic_zip.namelist()
        if (match := pattern.fullmatch(name))
    )


def read_text(zf: ZipFile, name: str) -> str:
    return zf.read(name).decode("utf-8", errors="replace")


def extract_named_blocks(text: str) -> dict[str, str]:
    """Return top-level brace blocks keyed by their first quoted value."""
    blocks: dict[str, str] = {}
    start = None
    depth = 0

    for idx, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                if idx + 1 < len(text) and text[idx + 1] == '"':
                    start = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    block = text[start : idx + 1]
                    match = re.match(r'\{"([^"]+)"', block)
                    if match:
                        blocks[match.group(1)] = block
                    start = None

    return blocks


def extract_named_tuples(text: str) -> dict[str, str]:
    """Return top-level unit tuples keyed by their name(...) token."""
    tuples: dict[str, str] = {}
    start = None
    depth = 0

    for idx, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                if idx + 1 < len(text) and text[idx + 1] == '"':
                    start = idx
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    chunk = text[start : idx + 1]
                    token_map = parse_token_map(chunk)
                    name_token = token_map.get("name", [None])[0]
                    if name_token:
                        tuples[name_token] = chunk
                    start = None

    return tuples


def parse_token_map(text: str) -> dict[str, list[str]]:
    """Collect the game's key(value) tokens while preserving repeated keys."""
    token_map: dict[str, list[str]] = defaultdict(list)
    for key, value in re.findall(r'([A-Za-z0-9_]+)\(([^()]*)\)', text):
        token_map[key].append(value.strip())
    return dict(token_map)


def parse_research_entries(text: str) -> list[dict]:
    """Parse the compact research-node records from a faction research file."""
    entries = []
    pattern = re.compile(
        r'\{\s*(tech\s+)?"([^"]+)"\s*requires\s*"([^"]*)"'
        r"\s*costs\s+([0-9.]+)\s+position\s+(-?\d+)\s+(-?\d+)\s*\}"
    )
    for match in pattern.finditer(text):
        entries.append(
            {
                "id": match.group(2),
                "node_type": "tech" if match.group(1) else "unit",
                "requires": [item for item in match.group(3).split() if item],
                "cost": float(match.group(4)),
                "position": {"x": int(match.group(5)), "y": int(match.group(6))},
            }
        )
    return entries


def parse_breed_declarations(text: str) -> dict[str, dict]:
    declarations: dict[str, dict] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('{"mp/'):
            continue

        # Some current-version declarations omit whitespace between the path and
        # role tuple, so accept both `"alias" (` and `"alias"(` forms.
        match = re.match(r'\{"([^"]+)"\s*\("([^"]+)"(.*?)\)\}\s*(?:;\s*(.*))?$', stripped)
        if not match:
            continue

        block_id = match.group(1)
        role_class = match.group(2)
        inner = match.group(3)
        comment = match.group(4).strip() if match.group(4) else None

        alias = block_id.rsplit("/", 1)[-1]
        token_map = parse_token_map(inner)
        declarations[alias] = {
            "id": block_id,
            "alias": alias,
            "role_class": role_class,
            "side": token_map.get("side", [None])[0],
            "levels": token_map.get("lvl", [""])[0].split(),
            "range_min": _maybe_number(token_map.get("r", [None])[0]),
            "range_max": _maybe_number(token_map.get("rm", [None])[0]),
            "cost": _maybe_number(token_map.get("cost", [None])[0]),
            "weapon_summary": comment,
            "raw": stripped,
        }
    return declarations


def parse_infantry_role_command_points(text: str) -> dict[str, int | float]:
    """Read the per-soldier CP values inherited by infantry roster declarations."""
    command_points: dict[str, int | float] = {}
    for match in re.finditer(r'\(define\s+"([^"]+)"', text):
        start = match.start()
        depth = 0
        in_string = False
        escaped = False
        end = None
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break

        if end is None:
            continue
        cp_match = re.search(r"\{cp\s+([0-9.]+)\}", text[start:end])
        if cp_match:
            command_points[match.group(1)] = _maybe_number(cp_match.group(1))
    return command_points


def _maybe_number(value):
    if value is None or value == "":
        return None
    try:
        if "." in str(value):
            return float(value)
        return int(value)
    except ValueError:
        return value


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def prettify_name(identifier: str) -> str:
    name = re.sub(r"\([^)]*\)", "", identifier)
    name = name.replace("_con", "")
    name = name.replace("_", " ").strip()
    return " ".join(word.capitalize() for word in name.split())


def normalize_node_lookup_id(identifier: str) -> str:
    return re.sub(r"\([^)]+\)$", "", identifier)


def sanitize_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def parse_breed_file(text: str) -> dict:
    """Extract the human-readable subset of a soldier breed definition."""
    result = {
        "skin": None,
        "portrait_id": None,
        "icon_id": None,
        "nationality": None,
        "inventory_items": [],
        "perks": [],
        "veterancy": [],
        "armor_parts": [],
    }

    result["skin"] = _first_regex_group(text, r'\{skin\s+"([^"]+)"\}')
    result["portrait_id"] = _first_regex_group(text, r'\{portrait\s+"?([^"}]+)"?\}')
    result["icon_id"] = _first_regex_group(text, r'\{icon\s+"([^"]+)"\}')
    result["nationality"] = _first_regex_group(text, r'\{nationality\s+([A-Za-z0-9_]+)\}')

    for item_name, payload in re.findall(r'\{item\s+"([^"]+)"([^}]*)\}', text):
        result["inventory_items"].append(
            {
                "item": item_name,
                "payload": _collapse_ws(payload) or None,
            }
        )

    result["perks"] = re.findall(r'\("([^"]+)"\)', _section_text(text, "perks"))
    result["veterancy"] = re.findall(r'\("([^"]+)"\)', _section_text(text, "veterancy"))
    result["armor_parts"] = [
        {"slot": slot, "item": item}
        for slot, item in re.findall(
            r"\{([A-Za-z0-9_]+)\s+([A-Za-z0-9_]+)\}",
            _section_text(text, "armors"),
        )
    ]
    return result


def _first_regex_group(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _section_text(text: str, section_name: str) -> str:
    marker = f"{{{section_name}"
    start = text.find(marker)
    if start == -1:
        return ""
    depth = 0
    for idx in range(start, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return text[start:]


def choose_image(
    scene_zip: ZipFile,
    pages_zip: ZipFile,
    available_scene: set[str],
    available_pages: set[str],
    node_id: str,
    breed_details: list[dict],
) -> tuple[str | None, bytes | None]:
    """Find the best available portrait or icon for a research node."""
    candidates = [
        f"scene/portrait_squad/{node_id}_00.png",
        f"scene/portrait_squad/{node_id}_00.tga",
        f"scene/unit_icon/{node_id}_00.png",
        f"scene/unit_icon/{node_id}_00.tga",
        f"scene/unit_icon_small/{node_id}_00.png",
        f"scene/unit_icon_small/{node_id}_00.tga",
    ]

    portrait_ids = [
        detail.get("portrait_id")
        for detail in breed_details
        if detail.get("portrait_id")
    ]
    icon_ids = [detail.get("icon_id") for detail in breed_details if detail.get("icon_id")]

    for portrait_id in portrait_ids:
        candidates.extend(
            [
                f"scene/portrait/{portrait_id}.png",
                f"scene/portrait/{portrait_id}.tga",
                f"scene/squad/{portrait_id}_00.tga",
            ]
        )

    for icon_id in icon_ids:
        candidates.extend(
            [
                f"scene/unit_icon/{icon_id}_00.tga",
                f"scene/unit_icon_small/{icon_id}_00.tga",
                f"pages/main/dynamic_campaign/icon_{icon_id}.tga",
            ]
        )

    for candidate in candidates:
        if candidate in available_scene:
            return candidate, scene_zip.read(candidate)
        if candidate in available_pages:
            return candidate, pages_zip.read(candidate)

    return None, None


def build_unit_lookup(
    faction: str, gamelogic_zip: ZipFile
) -> tuple[dict[str, str], dict[str, dict], dict[str, list[str]]]:
    """Load unit definitions, soldier declarations, and breed file locations."""
    inf_text = read_text(gamelogic_zip, ROSTER_INF_PATH_TEMPLATE.format(faction=faction))
    units_text = read_text(gamelogic_zip, ROSTER_UNIT_PATH_TEMPLATE.format(faction=faction))

    unit_blocks = {}
    unit_blocks.update(extract_named_blocks(inf_text))
    unit_blocks.update(extract_named_blocks(units_text))
    unit_blocks.update(extract_named_tuples(inf_text))
    unit_blocks.update(extract_named_tuples(units_text))

    breed_declarations = parse_breed_declarations(inf_text)

    breed_paths: dict[str, list[str]] = defaultdict(list)
    for name in gamelogic_zip.namelist():
        if name.startswith("set/breed/") and name.endswith(".set"):
            alias = Path(name).stem
            breed_paths[alias].append(name)

    return unit_blocks, breed_declarations, dict(breed_paths)


def parse_unit_block(node_id: str, block: str) -> dict:
    tuple_match = re.search(r'\("([^"]+)"', block)
    token_map = parse_token_map(block)

    members = []
    for key in sorted(token_map):
        if re.fullmatch(r"c\d+", key) or re.fullmatch(r"crew\d*", key):
            for value in token_map[key]:
                if ":" in value:
                    alias, count = value.split(":", 1)
                    members.append(
                        {
                            "slot": key,
                            "alias": alias.strip(),
                            "count": int(count.strip()),
                        }
                    )

    unit_count = sum(member["count"] for member in members) if members else None
    return {
        "id": node_id,
        "definition_type": tuple_match.group(1) if tuple_match else None,
        "side": token_map.get("side", [None])[0],
        "period": token_map.get("period", [None])[0],
        "group": token_map.get("g", [None])[0],
        "name_token": token_map.get("name", [None])[0],
        "bucket": token_map.get("b", [None])[0],
        "tags": token_map.get("t", [""])[0].split(),
        "cp": _maybe_number(token_map.get("cp", [None])[0]),
        "cw": _maybe_number(token_map.get("cw", [None])[0]),
        "ci": _maybe_number(token_map.get("ci", [None])[0]),
        "cd": _maybe_number(token_map.get("cd", [None])[0]),
        "min_stage": _maybe_number(token_map.get("min_stage", [None])[0]),
        "max_stage": _maybe_number(token_map.get("max_stage", [None])[0]),
        "vehicle": token_map.get("vehicle", [None])[0],
        "action": token_map.get("action", [None])[0],
        "members": members,
        "unit_count": unit_count,
        "raw": _collapse_ws(block),
    }


def resolve_breed_path(
    alias: str,
    unit_side: str | None,
    unit_period: str | None,
    breed_paths: dict[str, list[str]],
) -> str | None:
    """Prefer a breed file matching the unit's faction and time period."""
    candidates = breed_paths.get(alias, [])
    if not candidates:
        return None

    if unit_side and unit_period:
        preferred = f"/{unit_side}/{unit_period}/{alias}.set"
        for candidate in candidates:
            if preferred in candidate:
                return candidate

    if unit_side:
        for candidate in candidates:
            if f"/{unit_side}/" in candidate:
                return candidate

    return candidates[0]


def replace_output_directory(output_dir: Path, *, quiet: bool) -> None:
    """Create an empty output directory, replacing an earlier export."""
    if output_dir.exists():
        existing_files = sum(path.is_file() for path in output_dir.rglob("*"))
        log(
            f"Removing existing output directory {output_dir} "
            f"({existing_files} files) so all output is replaced",
            quiet=quiet,
        )
        shutil.rmtree(output_dir)
    else:
        log(f"Creating output directory {output_dir}", quiet=quiet)
    (output_dir / "images").mkdir(parents=True)


def describe_unit_members(
    unit: dict,
    declarations: dict[str, dict],
    breed_paths: dict[str, list[str]],
    infantry_role_cp: dict[str, int | float],
    gamelogic_zip: ZipFile,
) -> tuple[list[dict], float, int]:
    """Resolve a unit's members and calculate inherited command points."""
    details = []
    total_cost = 0.0
    total_command_points = 0.0
    all_command_points_known = True
    resolved_breed_count = 0

    for member in unit["members"]:
        alias = member["alias"]
        count = member["count"]
        declaration = declarations.get(alias)
        breed_path = resolve_breed_path(
            alias, unit["side"], unit["period"], breed_paths
        )
        breed = None
        if breed_path:
            breed = {
                "path": breed_path,
                **parse_breed_file(read_text(gamelogic_zip, breed_path)),
            }
            resolved_breed_count += 1

        cost = declaration.get("cost") if declaration else None
        member_cost = cost * count if cost is not None else None
        if member_cost is not None:
            total_cost += member_cost

        role_class = declaration.get("role_class") if declaration else None
        cp_source = "infantry_declaration" if role_class else None
        if role_class is None:
            role_class = INFANTRY_ROLE_CLASS_FALLBACKS.get(alias)
            if role_class:
                cp_source = "current_version_alias_fallback"

        command_points_each = infantry_role_cp.get(role_class) if role_class else None
        member_command_points = (
            command_points_each * count if command_points_each is not None else None
        )
        if member_command_points is None:
            all_command_points_known = False
        else:
            total_command_points += member_command_points

        details.append(
            {
                "alias": alias,
                "count": count,
                "slot": member["slot"],
                "declaration": declaration,
                "breed_file": breed,
                "total_cost": member_cost,
                "command_point_role_class": role_class,
                "command_points_source": cp_source,
                "command_points_each": command_points_each,
                "total_command_points": member_command_points,
            }
        )

    if unit["cp"] is not None:
        unit["cp_source"] = "unit_definition"
    elif details and all_command_points_known:
        unit["cp"] = (
            int(total_command_points)
            if total_command_points.is_integer()
            else total_command_points
        )
        unit["cp_source"] = "summed_member_role_classes"

    return details, total_cost, resolved_breed_count


def export(game_resource_dir: Path, output_dir: Path, *, quiet: bool = False) -> None:
    """Export every faction tree and its images into ``output_dir``."""
    game_resource_dir = game_resource_dir.resolve()
    output_dir = output_dir.resolve()
    archives = ArchivePaths.from_game_directory(game_resource_dir)
    required_archives = archives.all()
    missing_archives = [str(path) for path in required_archives if not path.is_file()]
    if missing_archives:
        raise FileNotFoundError(f"Required archive(s) not found: {', '.join(missing_archives)}")

    log(f"Game resource directory: {game_resource_dir}", quiet=quiet)
    log(f"Output directory: {output_dir}", quiet=quiet)
    for archive in required_archives:
        size_mib = archive.stat().st_size / (1024 * 1024)
        log(
            f"Using {archive.relative_to(game_resource_dir)} ({size_mib:.1f} MiB)",
            quiet=quiet,
        )

    if output_dir == game_resource_dir or output_dir == SCRIPT_DIR:
        raise RuntimeError("Output directory must not be the game resource or script directory")
    replace_output_directory(output_dir, quiet=quiet)

    with (
        ZipFile(archives.game_logic) as gamelogic_zip,
        ZipFile(archives.interface_scene) as scene_zip,
        ZipFile(archives.interface_pages) as pages_zip,
    ):
        scene_names = set(scene_zip.namelist())
        pages_names = set(pages_zip.namelist())
        gamelogic_names = set(gamelogic_zip.namelist())
        factions = discover_factions(gamelogic_zip)
        if not factions:
            raise RuntimeError("No dynamic-campaign research trees found in gamelogic.pak")

        log(
            f"Opened archives: {len(gamelogic_names):,} game-logic, "
            f"{len(scene_names):,} scene, and {len(pages_names):,} page assets",
            quiet=quiet,
        )
        log(f"Discovered {len(factions)} factions: {', '.join(factions)}", quiet=quiet)

        if CONQUEST_INF_SETTINGS_PATH not in gamelogic_names:
            raise RuntimeError(
                f"Required infantry settings not found: {CONQUEST_INF_SETTINGS_PATH}"
            )
        infantry_role_cp = parse_infantry_role_command_points(
            read_text(gamelogic_zip, CONQUEST_INF_SETTINGS_PATH)
        )
        if not infantry_role_cp:
            raise RuntimeError(
                "No infantry command-point values parsed from "
                f"{CONQUEST_INF_SETTINGS_PATH}"
            )
        log(
            f"Parsed command-point values for {len(infantry_role_cp)} infantry role classes",
            quiet=quiet,
        )

        total_nodes = 0
        total_images = 0

        for faction_index, faction in enumerate(factions, start=1):
            research_path = RESEARCH_PATH_TEMPLATE.format(faction=faction)
            roster_inf_path = ROSTER_INF_PATH_TEMPLATE.format(faction=faction)
            roster_unit_path = ROSTER_UNIT_PATH_TEMPLATE.format(faction=faction)
            missing_inputs = [
                path
                for path in (research_path, roster_inf_path, roster_unit_path)
                if path not in gamelogic_names
            ]
            if missing_inputs:
                raise RuntimeError(
                    f"Faction {faction!r} is missing required game data: {', '.join(missing_inputs)}"
                )

            log(f"[{faction_index}/{len(factions)}] Exporting {faction}", quiet=quiet)
            research_text = read_text(gamelogic_zip, research_path)
            unit_blocks, breed_declarations, breed_paths = build_unit_lookup(faction, gamelogic_zip)
            entries = parse_research_entries(research_text)
            if not entries:
                raise RuntimeError(f"No research nodes parsed from {research_path}")
            log(
                f"  Parsed {len(entries)} research nodes, {len(unit_blocks)} roster definitions, "
                f"and {len(breed_declarations)} breed declarations",
                quiet=quiet,
            )

            out = {
                "faction": faction,
                "source": {
                    "research_file": research_path,
                    "roster_inf_file": roster_inf_path,
                    "roster_unit_file": roster_unit_path,
                    "infantry_settings_file": CONQUEST_INF_SETTINGS_PATH,
                    "archives": [
                        archives.game_logic.name,
                        archives.interface_scene.name,
                        archives.interface_pages.name,
                    ],
                },
                "nodes": [],
            }

            resolved_units = 0
            resolved_breeds = 0
            exported_images = 0
            missing_unit_ids = []
            missing_image_ids = []

            for entry in entries:
                unit_info = None
                lookup_id = entry["id"]
                if lookup_id not in unit_blocks:
                    lookup_id = normalize_node_lookup_id(entry["id"])
                if lookup_id in unit_blocks:
                    unit_info = parse_unit_block(entry["id"], unit_blocks[lookup_id])
                    resolved_units += 1
                elif entry["node_type"] == "unit":
                    missing_unit_ids.append(entry["id"])

                member_details = []
                total_member_cost = 0.0
                if unit_info:
                    member_details, total_member_cost, breed_count = describe_unit_members(
                        unit_info,
                        breed_declarations,
                        breed_paths,
                        infantry_role_cp,
                        gamelogic_zip,
                    )
                    resolved_breeds += breed_count

                image_source, image_bytes = choose_image(
                    scene_zip,
                    pages_zip,
                    scene_names,
                    pages_names,
                    entry["id"],
                    [detail["breed_file"] for detail in member_details if detail.get("breed_file")],
                )

                image_ref = None
                if image_source and image_bytes:
                    ext = Path(image_source).suffix
                    filename = f"{sanitize_filename(entry['id'])}{ext}"
                    relative_path = Path("images") / faction / filename
                    target = output_dir / relative_path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(image_bytes)
                    image_ref = str(relative_path)
                    exported_images += 1
                else:
                    missing_image_ids.append(entry["id"])

                out["nodes"].append(
                    {
                        **entry,
                        "display_name": prettify_name(entry["id"]),
                        "image": {
                            "path": image_ref,
                            "source_asset": image_source,
                        }
                        if image_ref
                        else None,
                        "unit": unit_info,
                        "members": member_details or None,
                        "stats": {
                            "unit_count": unit_info["unit_count"] if unit_info else None,
                            "command_points": unit_info["cp"] if unit_info else None,
                            "member_cost_total": total_member_cost if member_details else None,
                            "member_cost_average": (
                                round(total_member_cost / unit_info["unit_count"], 2)
                                if member_details and unit_info and unit_info["unit_count"]
                                else None
                            ),
                        },
                    }
                )

            out["nodes"].sort(
                key=lambda node: (
                    node["position"]["y"],
                    node["position"]["x"],
                    node["id"],
                )
            )
            json_path = output_dir / f"{faction}.json"
            json_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
            total_nodes += len(entries)
            total_images += exported_images

            log(
                f"  Resolved {resolved_units}/{len(entries)} nodes to units, "
                f"{resolved_breeds} member breed files, and {exported_images}/{len(entries)} images",
                quiet=quiet,
            )
            if missing_unit_ids:
                log(
                    f"  WARNING: unit definitions not found: {', '.join(missing_unit_ids)}",
                    quiet=quiet,
                )
            if missing_image_ids:
                log(f"  WARNING: images not found: {', '.join(missing_image_ids)}", quiet=quiet)
            log(f"  Wrote {json_path} ({json_path.stat().st_size:,} bytes)", quiet=quiet)

    output_files = sum(1 for path in output_dir.rglob("*") if path.is_file())
    log(
        f"Done: exported {total_nodes:,} nodes and {total_images:,} images "
        f"across {len(factions)} factions ({output_files:,} files total)",
        quiet=quiet,
    )


def parse_args() -> object:
    parser = ArgumentParser(
        description="Export Gates of Hell dynamic-campaign research trees and images.",
        epilog=(
            "Example: ./export_research_trees.py "
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
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory to replace with exported JSON and images (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress progress messages")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        export(args.game_path, args.output, quiet=args.quiet)
    except (FileNotFoundError, KeyError, RuntimeError) as exc:
        print(f"[research-export] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

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
}


@dataclass(frozen=True)
class GameFiles:
    """Game archives needed to enrich the exported research data."""

    vehicle_archive: Path
    game_logic_archive: Path
    localization_archive: Path

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
        )

    def missing(self) -> list[Path]:
        return [
            path
            for path in (
                self.vehicle_archive,
                self.game_logic_archive,
                self.localization_archive,
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


def annotate_localized_names(trees: list[dict], localization_archive: Path) -> tuple[int, int]:
    """Replace internal identifiers with localized names and infantry levels."""
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

    name_count = 0
    level_count = 0
    color_tag = re.compile(r"<c\([^)]*\)>(.*?)</c>", re.IGNORECASE)
    level_prefix = re.compile(
        r"^\s*<c\([^)]*\)>\(\s*([0-9]+(?:\+)?)\s*\)</c>\s*",
        re.IGNORECASE,
    )
    for tree in trees:
        for node in tree["nodes"]:
            unit = node.get("unit") or {}
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

    return name_count, level_count


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


def annotate_infantry_equipment(node: dict, at_hand_weapons: set[str]) -> None:
    """Count soldiers with handheld AT weapons and detect carried shovels."""
    node["anti_tank_weapon_count"] = 0
    node["has_shovel"] = False
    if node["unit_class"] != "infantry":
        return

    for member in node.get("members") or []:
        inventory = (member.get("breed_file") or {}).get("inventory_items") or []
        item_names = [str(item.get("item") or "") for item in inventory]
        if any(re.match(r"^shovel(?:_|$)", name, re.IGNORECASE) for name in item_names):
            node["has_shovel"] = True

        normalized_items = {
            re.sub(r"\s+(?:weapon|grenade)$", "", name, flags=re.IGNORECASE).lower()
            for name in item_names
        }
        if normalized_items & at_hand_weapons:
            node["anti_tank_weapon_count"] += int(member.get("count") or 0)


def annotate_unit_metadata(
    trees: list[dict], vehicle_archive: Path, gamelogic_archive: Path
) -> tuple[int, int, int, int]:
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
        infantry_at_hand_weapons: set[str] = set()
        for name in gamelogic.namelist():
            if not name.startswith("set/stuff/") or name.endswith("/"):
                continue
            basename = PurePosixPath(name).name
            for suffix in (".weapon", ".grenade"):
                if basename.endswith(suffix):
                    basename = basename[: -len(suffix)]
            weapon_files[basename.lower()].append(name)
            if name.startswith(("set/stuff/bazooka/", "set/stuff/grenade/anti-tank grenade/")):
                infantry_at_hand_weapons.add(basename.lower())

        preset_blocks: dict[str, str] = {}
        for name in gamelogic.namelist():
            if name.startswith("set/stuff/") and name.endswith("/.presets"):
                preset_text = gamelogic.read(name).decode("utf-8", errors="replace")
                preset_blocks.update(_named_parenthesized_blocks(preset_text, '(define '))

        reload_pattern = re.compile(r'\("reload time"\s+seconds\(([0-9.]+)\)\)', re.IGNORECASE)

        weapon_metadata_cache: dict[str, tuple[float | None, float | None]] = {}

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

                weapon_references = re.findall(r'\{weapon\s+"([^"]+)"', definition_text)
                weapon_options = [
                    (reference, *weapon_metadata(reference)) for reference in weapon_references
                ]
                caliber_options = [option for option in weapon_options if option[2] is not None]
                selected_weapon = (
                    max(caliber_options, key=lambda option: option[2])
                    if caliber_options
                    else (weapon_options[0] if weapon_options else (None, None, None))
                )
                node["primary_weapon"] = selected_weapon[0]
                node["reload_time"] = selected_weapon[1]
                node["main_gun_caliber_mm"] = selected_weapon[2]
                if node["reload_time"] is not None:
                    reload_count += 1
                if node["main_gun_caliber_mm"] is not None:
                    caliber_count += 1

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
                annotate_infantry_equipment(node, infantry_at_hand_weapons)

    return indirect_count, reload_count, armor_count, caliber_count


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
    localized_name_count, localized_level_count = annotate_localized_names(
        trees, game_files.localization_archive
    )
    log(
        f"Resolved {localized_name_count} in-game unit names and "
        f"{localized_level_count} localized unit levels"
    )
    indirect_count, reload_count, armor_count, caliber_count = annotate_unit_metadata(
        trees,
        game_files.vehicle_archive,
        game_files.game_logic_archive,
    )
    log(
        f"Detected indirect-fire capability on {indirect_count} research nodes "
        "from game entity definitions"
    )
    log(f"Resolved primary-weapon reload time for {reload_count} research nodes")
    log(f"Resolved frontal armor thickness for {armor_count} research nodes")
    log(f"Resolved main-gun caliber for {caliber_count} research nodes")
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
#filters { height: 82px; display: flex; flex-wrap: wrap; align-content: center; align-items: center; gap: 8px 13px; padding: 6px 12px; background: #121617; border-bottom: 1px solid #343a3d; }
#filters label { display: flex; align-items: center; gap: 6px; white-space: nowrap; color: #b8c0c2; }
#filters input[type="number"] { width: 74px; }
#filters input[type="checkbox"] { width: auto; accent-color: #36a96c; }
#filter-count { color: #75daa5; font-weight: 650; }
#viewport { position: absolute; inset: 136px 0 0; overflow: hidden; cursor: grab; background-color: #0d1112; background-image: radial-gradient(#303638 1px, transparent 1px); background-size: 24px 24px; }
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
.node.selected { border-color: var(--accent); box-shadow: 0 0 18px #e0ad4fcc; z-index: 4; }
.node.required { border-color: var(--required); box-shadow: 0 0 13px #67c7f499; z-index: 2; }
.node.dimmed { opacity: .2; }
.node.search-match { outline: 4px solid #d65cff; outline-offset: 2px; }
.node.filter-match { background: #24563d; border-color: #73e4aa; box-shadow: 0 0 15px #50d79499; }
.node.filter-match .node-title { background: #24563d; }
#details { position: absolute; z-index: 10; right: 0; top: 136px; bottom: 0; width: min(430px, 42vw); background: #171b1df5; border-left: 1px solid #495154; box-shadow: -8px 0 24px #0008; overflow: auto; padding: 18px; transform: translateX(100%); transition: transform .2s; }
#details.open { transform: translateX(0); }
#close-details { float: right; font-size: 18px; padding: 2px 8px; }
.detail-head { display: flex; gap: 14px; align-items: flex-start; margin: 8px 0 14px; }
.detail-head img { width: 112px; height: 140px; object-fit: cover; border: 1px solid #626a6c; border-radius: 5px; }
.detail-head h2 { margin: 0 0 5px; font-size: 21px; }
.muted { color: #9ea7a9; overflow-wrap: anywhere; }
.totals { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; margin: 12px 0; }
.total { padding: 8px; background: #252b2e; border-radius: 5px; text-align: center; }
.total strong { display: block; font-size: 18px; color: #f0c873; }
#details h3 { margin: 18px 0 7px; padding-bottom: 4px; border-bottom: 1px solid #42494c; }
.stats { display: grid; grid-template-columns: minmax(105px, .8fr) minmax(0, 1.2fr); gap: 1px; background: #343b3e; border: 1px solid #343b3e; }
.stats dt, .stats dd { margin: 0; padding: 5px 7px; background: #202527; overflow-wrap: anywhere; }
.stats dt { color: #aeb7b9; }
.member { border: 1px solid #3e4649; border-radius: 5px; padding: 9px; margin: 8px 0; background: #1d2224; }
.member h4 { margin: 0 0 7px; color: #9edcff; }
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip { background: #30383b; border-radius: 10px; padding: 2px 7px; font-size: 12px; }
.notice { padding: 9px; border-left: 3px solid #db9b45; background: #3b2d1c; margin: 10px 0; }
html[data-theme="light"] { color-scheme: light; --line: #697477; --accent: #9b6300; --required: #0879ac; }
html[data-theme="light"] body { background: #e9eeea; color: #182022; }
html[data-theme="light"] #toolbar { background: #f8faf7; border-color: #b9c1bd; }
html[data-theme="light"] #filters { background: #f1f5f1; border-color: #b9c1bd; }
html[data-theme="light"] #filters label { color: #4f5b5d; }
html[data-theme="light"] button, html[data-theme="light"] select, html[data-theme="light"] input { color: #182022; background: #fff; border-color: #8b9799; }
html[data-theme="light"] button:hover { background: #e4e9e6; }
html[data-theme="light"] #viewport { background-color: #e5ebe7; background-image: radial-gradient(#aeb9b5 1px, transparent 1px); }
html[data-theme="light"] .node { background: #fff; border-color: #687477; box-shadow: 0 3px 8px #3444; }
html[data-theme="light"] .node img, html[data-theme="light"] .node .no-image { background: #dce2de; }
html[data-theme="light"] .node-title { background: #f7f9f6; }
html[data-theme="light"] .badge, html[data-theme="light"] .cp-badge, html[data-theme="light"] .reload-badge, html[data-theme="light"] .at-count-badge, html[data-theme="light"] .infantry-level, html[data-theme="light"] .shovel-icon, html[data-theme="light"] .indirect-icon { background: #fffE; border-color: #5e676a99; color: #4d642d; }
html[data-theme="light"] .cp-badge { color: #005b86; }
html[data-theme="light"] .badge.units { color: #005b86; }
html[data-theme="light"] .node.filter-match, html[data-theme="light"] .node.filter-match .node-title { background: #bcebcf; border-color: #16824a; }
html[data-theme="light"] #details { background: #f8faf7f5; border-color: #aab4b1; box-shadow: -8px 0 24px #4555; }
html[data-theme="light"] .muted { color: #626e70; }
html[data-theme="light"] .total { background: #e4e9e6; }
html[data-theme="light"] .total strong { color: #754900; }
html[data-theme="light"] .stats { background: #b9c3c0; border-color: #b9c3c0; }
html[data-theme="light"] .stats dt, html[data-theme="light"] .stats dd { background: #f2f5f1; }
html[data-theme="light"] .stats dt { color: #596466; }
html[data-theme="light"] .member { background: #f2f5f1; border-color: #b8c1be; }
html[data-theme="light"] .chip { background: #dce3df; }
html[data-theme="light"] .notice { background: #fff0d4; }
@media (max-width: 1000px) { #hint { display: none; } #filters { height: 46px; flex-wrap: nowrap; overflow-x: auto; } #viewport { inset: 100px 0 0; } #details { top: 100px; } }
@media (max-width: 760px) { #details { width: 100%; } #toolbar h1 { display: none; } }
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
<div id="filters">
  <strong>Highlight filters</strong>
  <label>Min unit size <input id="min-size" type="number" min="0" step="1" placeholder="Any"></label>
  <label>Min unit level <input id="min-level" type="number" min="0" step="1" placeholder="Any"></label>
  <label>Min infantry AT <input id="min-infantry-at" type="number" min="0" step="1" placeholder="Any"></label>
  <label>Min front armour <input id="min-front-armor" type="number" min="0" step="0.1" placeholder="Any"> mm</label>
  <label>Min gun calibre <input id="min-caliber" type="number" min="0" step="0.1" placeholder="Any"> mm</label>
  <label>Max reload <input id="max-reload" type="number" min="0" step="0.1" placeholder="Any"> seconds</label>
  <label>Max CP <input id="max-cp" type="number" min="0" step="1" placeholder="Any"></label>
  <label>Unit class <select id="unit-class"><option value="">Any</option><option value="infantry">Infantry</option><option value="tanks">Tanks</option><option value="artillery">Artillery</option><option value="at-cannon">AT cannon</option><option value="other">Other</option></select></label>
  <label><input id="has-shovel" type="checkbox"> Infantry with shovel</label>
  <button id="clear-filters">Clear filters</button>
  <span id="filter-count"></span>
</div>
<main id="viewport"><div id="world"><svg id="edges"></svg><div id="nodes"></div></div></main>
<aside id="details" aria-live="polite"><button id="close-details" title="Close">×</button><div id="detail-content"></div></aside>
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
  const factionSelect = document.getElementById('faction');
  const themeButton = document.getElementById('theme');
  const minSizeInput = document.getElementById('min-size');
  const minLevelInput = document.getElementById('min-level');
  const minInfantryAtInput = document.getElementById('min-infantry-at');
  const minFrontArmorInput = document.getElementById('min-front-armor');
  const minCaliberInput = document.getElementById('min-caliber');
  const maxReloadInput = document.getElementById('max-reload');
  const maxCpInput = document.getElementById('max-cp');
  const unitClassSelect = document.getElementById('unit-class');
  const hasShovelInput = document.getElementById('has-shovel');
  const filterCount = document.getElementById('filter-count');
  let tree, byId, nodeElements, edgeElements, worldWidth, worldHeight;
  let scale = 1, tx = 0, ty = 0, dragging = false, dragStart;

  const esc = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const label = key => key.replaceAll('_', ' ').replace(/\b\w/g, ch => ch.toUpperCase());
  const shown = value => value !== null && value !== undefined && value !== '' && (!Array.isArray(value) || value.length);
  const number = value => Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));

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

  function setTransform() { world.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`; }
  function nodePosition(node) { return { x: PAD + node.position.x * STEP_X, y: PAD + node.position.y * STEP_Y }; }

  function renderTree(faction) {
    tree = trees.find(item => item.faction === faction);
    byId = new Map(tree.nodes.map(node => [node.id, node]));
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
        const x1 = rp.x + NODE_W / 2, y1 = rp.y + NODE_H;
        const x2 = p.x + NODE_W / 2, y2 = p.y;
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
      const atWeaponBadge = node.anti_tank_weapon_count > 0 ? `<span class="at-count-badge" title="Infantry carrying AT launchers or AT hand grenades">AT ×${esc(node.anti_tank_weapon_count)}</span>` : '';
      const lowerLeftBadges = cpBadge || reloadBadge || atWeaponBadge ? `<div class="lower-left-badges">${cpBadge}${reloadBadge}${atWeaponBadge}</div>` : '';
      const indirectIcon = node.indirect_fire ? '<span class="indirect-icon" title="Indirect fire capability" aria-label="Indirect fire capability"><svg viewBox="0 0 24 20" aria-hidden="true"><path d="M2 17 Q8 2 18 7" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="2 2"/><path d="M15 4 L20 7 L16 11" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="3" cy="17" r="2" fill="currentColor"/></svg></span>' : '';
      card.innerHTML = `${image}${infantryLevel}${shovelIcon}${indirectIcon}${lowerLeftBadges}<div class="badges"><span class="badge" title="Research points needed">${flaskIcon}${esc(number(node.cost))}</span>${unitBadge}</div><div class="node-title">${esc(node.display_name)}</div>`;
      card.addEventListener('click', event => { event.stopPropagation(); selectNode(node.id); });
      nodesLayer.append(card); nodeElements.set(node.id, card);
    }
    clearHighlighting();
    applyFilters();
    requestAnimationFrame(startView);
  }

  function applyFilters() {
    if (!tree || !nodeElements) return;
    const hasMinSize = minSizeInput.value !== '';
    const hasMinLevel = minLevelInput.value !== '';
    const hasMinInfantryAt = minInfantryAtInput.value !== '';
    const hasMinFrontArmor = minFrontArmorInput.value !== '';
    const hasMinCaliber = minCaliberInput.value !== '';
    const hasMaxReload = maxReloadInput.value !== '';
    const hasMaxCp = maxCpInput.value !== '';
    const selectedClass = unitClassSelect.value;
    const shovelOnly = hasShovelInput.checked;
    const active = hasMinSize || hasMinLevel || hasMinInfantryAt || hasMinFrontArmor || hasMinCaliber || hasMaxReload || hasMaxCp || !!selectedClass || shovelOnly;
    const minSize = Number(minSizeInput.value);
    const minLevel = Number(minLevelInput.value);
    const minInfantryAt = Number(minInfantryAtInput.value);
    const minFrontArmor = Number(minFrontArmorInput.value);
    const minCaliber = Number(minCaliberInput.value);
    const maxReload = Number(maxReloadInput.value);
    const maxCp = Number(maxCpInput.value);
    let matches = 0;
    for (const [id, element] of nodeElements) {
      const node = byId.get(id);
      const unitSize = node.stats?.unit_count;
      const unitLevel = node.unit_level;
      const infantryAt = node.anti_tank_weapon_count;
      const frontArmor = node.front_armor_thickness_mm;
      const caliber = node.main_gun_caliber_mm;
      const reload = node.reload_time;
      const commandPoints = node.unit?.cp;
      const match = active
        && (!hasMinSize || (unitSize !== null && unitSize !== undefined && unitSize >= minSize))
        && (!hasMinLevel || (unitLevel !== null && unitLevel !== undefined && unitLevel >= minLevel))
        && (!hasMinInfantryAt || (node.unit_class === 'infantry' && infantryAt >= minInfantryAt))
        && (!hasMinFrontArmor || (frontArmor !== null && frontArmor !== undefined && frontArmor >= minFrontArmor))
        && (!hasMinCaliber || (caliber !== null && caliber !== undefined && caliber >= minCaliber))
        && (!hasMaxReload || (reload !== null && reload !== undefined && reload <= maxReload))
        && (!hasMaxCp || (commandPoints !== null && commandPoints !== undefined && commandPoints <= maxCp))
        && (!selectedClass || node.unit_class === selectedClass)
        && (!shovelOnly || (node.unit_class === 'infantry' && node.has_shovel));
      element.classList.toggle('filter-match', match);
      if (match) matches += 1;
    }
    filterCount.textContent = active ? `${matches} matching nodes` : '';
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
    details.classList.add('open');
  }

  function clearHighlighting() {
    for (const element of nodeElements?.values() || []) element.classList.remove('selected', 'required', 'dimmed');
    for (const edge of edgeElements || []) edge.element.classList.remove('highlight', 'dimmed');
    details.classList.remove('open');
  }

  function statRows(object, omitted = new Set()) {
    if (!object) return '<p class="muted">None</p>';
    return '<dl class="stats">' + Object.entries(object)
      .filter(([key, value]) => !omitted.has(key) && shown(value))
      .map(([key, value]) => `<dt>${esc(label(key))}</dt><dd>${formatValue(value)}</dd>`).join('') + '</dl>';
  }

  function formatValue(value) {
    if (Array.isArray(value)) return `<div class="chips">${value.map(item => `<span class="chip">${typeof item === 'object' ? esc(JSON.stringify(item)) : esc(item)}</span>`).join('')}</div>`;
    if (typeof value === 'object' && value) return esc(JSON.stringify(value));
    return esc(value);
  }

  function renderDetails(node, required) {
    const allNodes = [node, ...[...required].map(id => byId.get(id)).filter(Boolean)];
    const totalCost = allNodes.reduce((sum, item) => sum + Number(item.cost || 0), 0);
    const missing = new Set();
    for (const item of allNodes) for (const id of item.requires) if (!byId.has(id)) missing.add(id);
    const image = node.web_image ? `<img src="${esc(node.web_image)}" alt="">` : '';
    const unit = node.unit;
    const memberHtml = (node.members || []).map(member => {
      const declaration = member.declaration ? statRows(member.declaration, new Set(['raw'])) : '<p class="muted">No declaration</p>';
      const breed = member.breed_file ? statRows(member.breed_file) : '<p class="muted">No breed file</p>';
      return `<section class="member"><h4>${esc(member.alias)} ×${esc(member.count)}</h4>${statRows({slot: member.slot, total_cost: member.total_cost})}<h4>Declaration</h4>${declaration}<h4>Breed</h4>${breed}</section>`;
    }).join('');
    const requirementNames = [...required].map(id => byId.get(id)?.display_name || id);
    detailContent.innerHTML = `
      <div class="detail-head">${image}<div><h2>${esc(node.display_name)}</h2><div class="muted">${esc(node.id)}</div><div class="muted">${esc(node.node_type)}</div></div></div>
      <div class="totals"><div class="total"><strong>${esc(number(node.cost))}</strong>Own RP</div><div class="total"><strong>${esc(number(totalCost))}</strong>Total RP</div><div class="total"><strong>${shown(node.stats?.unit_count) ? esc(node.stats.unit_count) : '—'}</strong>Units</div></div>
      ${missing.size ? `<div class="notice">Missing prerequisite data: ${[...missing].map(esc).join(', ')}</div>` : ''}
      <h3>Unlock prerequisites (${required.size})</h3>${requirementNames.length ? `<div class="chips">${requirementNames.map(name => `<span class="chip">${esc(name)}</span>`).join('')}</div>` : '<p class="muted">No prerequisites</p>'}
      <h3>Research data</h3>${statRows({cost: node.cost, indirect_fire_capability: node.indirect_fire ? 'Yes' : 'No', position_x: node.position.x, position_y: node.position.y, source_asset: node.image?.source_asset})}
      <h3>Aggregate unit stats</h3>${statRows({...node.stats, unit_class: node.unit_class, unit_level: node.unit_level_label, carries_shovel: node.unit_class === 'infantry' ? (node.has_shovel ? 'Yes' : 'No') : null, anti_tank_equipped_infantry: node.anti_tank_weapon_count || null, at_cannon: node.at_cannon ? 'Yes' : 'No', front_armor_thickness_mm: node.front_armor_thickness_mm, maximum_armor_thickness_mm: node.maximum_armor_thickness_mm, primary_weapon: node.primary_weapon, main_gun_caliber_mm: node.main_gun_caliber_mm, reload_time_seconds: node.reload_time})}
      <h3>Unit stats</h3>${statRows(unit, new Set(['raw', 'members', 'id']))}
      ${memberHtml ? `<h3>Unit members (${node.members.length})</h3>${memberHtml}` : ''}`;
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

  viewport.addEventListener('wheel', event => { event.preventDefault(); const rect = viewport.getBoundingClientRect(); zoomAt(event.deltaY < 0 ? 1.12 : .89, event.clientX - rect.left, event.clientY - rect.top); }, {passive:false});
  viewport.addEventListener('pointerdown', event => { if (event.button !== 0 || event.target.closest('.node')) return; dragging = true; dragStart = {x:event.clientX, y:event.clientY, tx, ty}; viewport.classList.add('dragging'); viewport.setPointerCapture(event.pointerId); });
  viewport.addEventListener('pointermove', event => { if (!dragging) return; tx = dragStart.tx + event.clientX - dragStart.x; ty = dragStart.ty + event.clientY - dragStart.y; setTransform(); });
  viewport.addEventListener('pointerup', () => { dragging = false; viewport.classList.remove('dragging'); });
  viewport.addEventListener('click', event => { if (event.target === viewport || event.target === world || event.target === nodesLayer) clearHighlighting(); });
  factionSelect.addEventListener('change', () => renderTree(factionSelect.value));
  document.getElementById('clear').addEventListener('click', clearHighlighting);
  document.getElementById('close-details').addEventListener('click', clearHighlighting);
  document.getElementById('fit').addEventListener('click', fitTree);
  document.getElementById('zoom-in').addEventListener('click', () => zoomAt(1.25));
  document.getElementById('zoom-out').addEventListener('click', () => zoomAt(.8));
  themeButton.addEventListener('click', () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  for (const control of [minSizeInput, minLevelInput, minInfantryAtInput, minFrontArmorInput, minCaliberInput, maxReloadInput, maxCpInput, unitClassSelect, hasShovelInput]) control.addEventListener('input', applyFilters);
  document.getElementById('clear-filters').addEventListener('click', () => { minSizeInput.value = ''; minLevelInput.value = ''; minInfantryAtInput.value = ''; minFrontArmorInput.value = ''; minCaliberInput.value = ''; maxReloadInput.value = ''; maxCpInput.value = ''; unitClassSelect.value = ''; hasShovelInput.checked = false; applyFilters(); });
  document.getElementById('search').addEventListener('input', event => {
    const query = event.target.value.trim().toLowerCase();
    for (const [id, element] of nodeElements) {
      const node = byId.get(id);
      element.classList.toggle('search-match', !!query && (id.toLowerCase().includes(query) || node.display_name.toLowerCase().includes(query)));
    }
  });
  window.addEventListener('resize', fitTree);
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

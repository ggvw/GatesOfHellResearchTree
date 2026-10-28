# Build and development guide

[Back to the project](../README.md)

## Requirements

- Python 3.10 or newer
- [Pillow](https://pypi.org/project/pillow/) for converting game images
- An installed copy of Call to Arms: Gates of Hell — Ostfront

Install Pillow with:

```bash
python3 -m pip install Pillow
```

## Quick start

The scripts require the path to the game's `resource` directory. A typical Linux
Steam installation uses:

```text
~/.local/share/Steam/steamapps/common/Call to Arms - Gates of Hell/resource
```

First export the game data:

```bash
./export_research_trees.py \
  "$HOME/.local/share/Steam/steamapps/common/Call to Arms - Gates of Hell/resource"
```

Then build the HTML viewer:

```bash
./create_research_tree_html.py \
  "$HOME/.local/share/Steam/steamapps/common/Call to Arms - Gates of Hell/resource"
```

Open `research_tree_html/index.html` in a browser. See the [viewer guide](viewer-guide.md)
for controls and filters.

### Steam Workshop mods

No extra arguments are needed. The exporter finds Workshop content for app
`400750` in the game's Steam library and other libraries registered in
`libraryfolders.vdf`. Run both commands above after installing or updating mods.

Each dataset starts with base-game resources, then applies the mod's required
Workshop dependencies in declaration order, followed by the selected mod.
Unrelated installed mods are never combined. Within each resource layer,
archives are mounted in sorted path order at their containing directories,
then loose files override archived files. File paths are matched without case
sensitivity. Mod deletion directives are applied before mounting that mod.
Both build stages use this same precedence for research, rosters, breeds,
weapons, entities, properties, localization, and images, including custom archive
names. The active conquest roster's includes determine which unit definitions
are loaded. English names come from default localization archives and resource
localization files.

The export retains base factions at its root, stores mod factions under
`mods/WORKSHOP_ID/`, and records their dependency layers in `datasets.json`.
Keep the installed mods available until the HTML build finishes. The generated
viewer then works independently of Steam and the installed game.

The parsers support relative includes, research templates with `key(value)`
arguments, integer addition/subtraction of template offsets, fractional node
positions, and implicit starting-unit positions. Missing references, corrupt
archives, include/dependency cycles, malformed research data, and unsupported
structures produce warnings. Unusable factions or datasets are skipped; missing
images use placeholders. Dependencies that are absent or cannot be resolved
prevent that mod's export. This is a static data viewer: arbitrary mod scripts
and more complex template expressions are not executed.

Both output directories are replaced on every run. Use `--output` or `--input`
to select different locations:

```bash
./export_research_trees.py GAME_PATH --output /tmp/research_export
./create_research_tree_html.py GAME_PATH \
  --input /tmp/research_export \
  --output /tmp/research_tree_html
```

Run either script with `--help` for the complete command-line reference.

## How it works

The process is intentionally split into two stages:

1. `export_research_trees.py` reads research, roster, breed, and interface
   archives. It writes one JSON file per faction plus the corresponding images.
2. `create_research_tree_html.py` enriches that export with localization,
   vehicle armour and road speed, weapon, reload, indirect-fire, and equipment
   data. It converts images to PNG and embeds all faction data in one HTML file.

The generated directories are ignored by Git because they contain extracted game
data and can always be rebuilt locally.

## Game-data notes

The game uses a custom text format rather than a formal public schema. Parsers in
this project deliberately extract only the fields needed by the viewer.

Infantry command points are calculated from the role class of every squad member.
Vehicle and object CP is added to the CP of their crew or squad members. The
stats panel shows base, member, and total command points; a zero-CP object can
therefore still require CP for its crew. Research-point cost is separate. A small,
documented compatibility table handles four aliases referenced by the current
rosters but omitted from their declaration files.

Some research nodes may not have a normal unit definition. The exporter reports
these cases and keeps the nodes in the graph when their research data and images
are available.

Research branch types are derived from the section surrounding each root in the
game's research files. Descendants retain every applicable root type because the
game contains cross-branch prerequisites. The `conquest_blank` placeholders are
deliberately excluded.

## Repository layout

```text
export_research_trees.py       Extract game data and images
create_research_tree_html.py   Enrich the export and build the viewer
firepower.py                   Calculate firepower estimates and percentiles
game_data.py                   Discover Workshop mods and layer resource files
research_export/               Generated intermediate data (ignored)
research_tree_html/            Generated website (ignored)
```

## Contributing

When changing a parser, test against a current unmodified game installation and
run both stages end to end. Please avoid committing generated game data or assets.

Run the calculation, Workshop overlay, and extraction tests with:

```bash
python3 -m unittest discover -s tests -v
```

Run the viewer's armour filter checks with Node.js:

```bash
node tests/test_armour_filters.js
node tests/test_general_filters.js
node tests/test_unit_table.js
```

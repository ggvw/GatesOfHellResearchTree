# Gates of Hell Research Tree

Generate a searchable, interactive HTML version of the dynamic-conquest research
trees from an installed copy of **Call to Arms: Gates of Hell — Ostfront**.

The project reads the game's own archives, so unit names, research links, images,
and statistics come from the installed game version instead of a separately
maintained database.

## Features

- Navigable research graph for every detected faction
- Localized in-game unit names and infantry levels
- Unit portraits and icons extracted from the game archives
- Prerequisite highlighting and total research-point calculation
- Light and dark themes
- A collapsible filter panel with squad size, level, command-point, reload-time,
  unit-speed, armor, gun-caliber, indirect-fire, and infantry-equipment
  filters
- Multiselect filters for infantry inventory, individual weapons, weapon roles,
  and specialist types
- Research-branch multiselect for infantry, support-weapon, and vehicle branches;
  selected branches retain shared prerequisites and collapse empty graph rows
- Detailed unit, member, weapon, and equipment statistics
- A resizable right-side stats panel with scrollable comparison tables for infantry and crew,
  vehicle statistics in a separate table and quantities shown for each variant
- Localized main, secondary, and additional carried weapons for each soldier
- Localized vehicle guns and machine guns, with calibre and reload statistics
- Per-gun ammunition types and counts, including spare and loaded rounds
- A self-contained `index.html` that works without a web server

- <img width="3398" height="1792" alt="image" src="https://github.com/user-attachments/assets/e91c1430-c3c8-4651-b033-a6432773b906" />



## Using the filters

The collapsible panel on the left highlights matching nodes. Most filters leave
the complete research tree visible for context. The research-branch filter is
the exception: it hides unrelated branches and compacts empty graph rows.

Selecting several values within one multiselect matches units containing any of
those values. Selections from different filter groups are combined, so a unit
must satisfy every active group.

The General section's Unit speed (km/h) filter sets a minimum movement speed.
Infantry uses the game's base sprint speed with breed perk modifiers; squads
use their slowest member. Mounted units use their vehicle's road speed. Each
soldier's sprint speed is also shown in the comparison table. These are configured
speeds; terrain, stamina, injuries, and carried equipment can affect actual
movement. Unresolved speeds are shown as Unknown and do not match this filter.

### Infantry inventory

Inventory names differ between factions. The generator therefore maps the
game's internal item IDs to the following cross-faction categories:

- Shovel
- Binoculars
- Mine detector
- Wire cutters
- Pickaxe
- Demolition charge
- Anti-tank grenade
- Anti-personnel grenade
- Anti-personnel mine
- Anti-tank mine
- Smoke grenade
- Incendiary or white-phosphorus item
- Molotov cocktail
- Body armour
- Radio
- Flare gun
- Knife or bayonet

The grenade classifications come directly from the game's anti-tank and
anti-personnel grenade directories. Smoke and incendiary grenades remain
separate categories. Ordinary weapons and ammunition are intentionally omitted
from Inventory because they are represented by the Weapon roles filter.

### Weapon roles and specialists

Weapon roles are derived from each soldier breed's icon, producing options such
as rifle, submachine gun, automatic rifle, machine gun, AT launcher, AT rifle,
flamethrower, sniper rifle, and rifle grenade. Specialist types use role classes,
perks, and narrowly scoped aliases to identify scouts/recon troops, snipers,
scoped marksmen, engineers, medics, officers, tank crews, repair specialists,
and radio operators. Only values present in the generated research data are
shown in each multiselect.

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

Open `research_tree_html/index.html` in a browser.

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
   vehicle armor and road speed, weapon, reload, indirect-fire, and equipment
   data. It converts images to PNG and embeds all faction data in one HTML file.

The generated directories are ignored by Git because they contain extracted game
data and can always be rebuilt locally.

## Game-data notes

The game uses a custom text format rather than a formal public schema. Parsers in
this project deliberately extract only the fields needed by the viewer.

Infantry command points are calculated from the role class of every squad member.
Vehicles and formations retain their explicit command-point values. A small,
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
research_export/               Generated intermediate data (ignored)
research_tree_html/            Generated website (ignored)
```

## Contributing

When changing a parser, test against a current unmodified game installation and
run both stages end to end. Please avoid committing generated game data or assets.

## License

This project's source code and documentation are licensed under the [MIT License](LICENSE).
The license does not cover game data or assets extracted from an installed copy of
Call to Arms: Gates of Hell — Ostfront.

This is an unofficial community project and is not affiliated with Barbedwire
Studios or Digitalmindsoft. Game names and assets belong to their respective
owners.

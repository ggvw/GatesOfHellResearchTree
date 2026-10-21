# Gates of Hell Research Tree

Generate a searchable, interactive HTML version of the dynamic-conquest research
trees from an installed copy of **Call to Arms: Gates of Hell — Ostfront**.

The project reads the game's own archives, so unit names, research links, images,
and statistics come from the installed game version instead of a separately
maintained database.

## Features

- Navigable research graph for every detected faction
- Graph/Table switch with a mobile-friendly unit list and shared filters
- Automatic Steam Workshop discovery with a single-mod selector and separate base-game data
- Localized in-game unit names and infantry levels
- Unit portraits and icons extracted from the game archives
- Prerequisite highlighting and total research-point calculation
- Light and dark themes
- A collapsible filter panel with squad size, level, command-point, reload-time,
  unit-speed, armour, gun-caliber, indirect-fire, and infantry-equipment
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
- Turret turn speeds in degrees per second, with a minimum-speed filter
- Configured AI, direct-control, and minimum firing ranges, with ammunition overrides and range filters
- Per-gun ammunition types and counts, including spare and loaded rounds
- Rounds before reload for infantry and vehicle weapons, with a primary-weapon
  minimum-capacity filter in Weapons
- Weapon rate of fire in RPM, with a primary-weapon minimum-rate filter
- Firepower metrics with filters, role-group percentiles, and target-specific help
- A self-contained `index.html` that works without a web server
-  <img width="1157" height="795" alt="Screenshot from 2026-10-16 10-15-31" src="https://github.com/user-attachments/assets/e50a340a-5d30-4615-ba6b-6caf54439df2" />




## Using the filters

Choose Graph or Table in the top bar. Graph mode highlights matching nodes;
Table mode lists matching units and removes rows that do not match. Search and
branch selections also filter table rows. Table columns show unit name, CP, RP,
total RP including shared prerequisites counted once, unit size, gun calibre,
AI range, direct-control range, minimum firing distance, reload time, rate of
fire, and movement speed. Select a unit name to open its
statistics. Missing values appear as a dash. On small screens the table uses
labelled rows, and filters can be opened with the side button. The viewer starts
in Table mode on small screens and remembers an explicit view choice.

In Table mode, gun calibre, reload time, RPM, and capacity filters use the
largest-calibre weapon in the unit. Vehicles use mounted weapons only; infantry
uses weapons carried by active squad members. Values come from the same weapon,
so a cannon's calibre cannot be paired with a machine gun's rate of fire.

The collapsible panel on the left highlights matching nodes. Most filters leave
the complete research tree visible for context. The research-branch filter is
the exception: it hides unrelated branches and compacts empty graph rows.

Selecting several values within one multiselect matches units containing any of
those values. Selections from different filter groups are combined, so a unit
must satisfy every active group.

Filters are grouped into General (CP, size, speed), Infantry (level and equipment),
Weapons (calibre, capacity, rate, reload, turret turn speed, range, indirect fire), Armour, and Firepower
estimates.

The General section's Min speed (km/h) filter sets a minimum movement speed.
Infantry uses the game's base sprint speed with breed perk modifiers; squads
use their slowest member. Mounted units use their vehicle's road speed. Each
soldier's sprint speed is also shown in the comparison table. These are configured
speeds; terrain, stamina, injuries, and carried equipment can affect actual
movement. Unresolved speeds are shown as Unknown and do not match this filter.

Min rounds before reload checks the primary vehicle gun, or any soldier's main
weapon in an infantry squad. Secondary and additional weapons do not affect
matching. This is weapon capacity, separate from starting loaded rounds and
total ammunition carried. Unknown capacities do not match the filter.

Armour filters set minimum thicknesses for front, left side, right side, rear,
roof, floor, and default thickness. Choose hull, turret, hull and turret, or any
part (including mantlets and shields). A single part must satisfy every entered
minimum; values from different plates are never combined. Hull includes engine
compartment parts. A face without an override uses that part's default thickness.
Unknown thicknesses do not match, and an explicit zero remains zero. Changing
the part selector alone does not activate a filter. Clear filters also resets
the part selection.

Min rate of fire (RPM) uses the same primary-weapon rule. Rates come from weapon
definitions and their inherited presets. For single-shot weapons without an
explicit rate, RPM is calculated as 60 divided by reload time in seconds.
AI burst pauses, aiming, and other delays can reduce actual firing rates.

Min turret turn speed (°/s) checks the main turret's configured turn speed.
The Vehicle stats table shows it when available, with other turret speeds listed
separately. Values come from turret bone settings, including arithmetic in
parameterized presets; a preset's `power_traverse` argument is not itself the
final turn speed. Gun elevation, hull traverse, and commander optics are excluded.
Missing or unsupported values do not match the filter. Mod overrides are respected.

The Weapons section's Firing range filters set minimum AI and direct-control
ranges, or a maximum minimum firing distance to find weapons that can fire
closer. Ranges are configured game distances in meters, not historical ranges.
`range` specifies AI and direct-control ranges separately; `minRange` is a
separate minimum firing distance and is only shown when explicitly available.
Weapon stats shows each gun's default ranges and ammunition-specific overrides
(for example, a gun may have 200 m default range but 180 m with HE).
Range filters and table columns use the largest-calibre weapon's default settings
in both views. Unknown values do not match filters, including a zero threshold.
Presets, weapon inheritance, and mod overrides are respected. Game mode and
direct-control settings can permit firing beyond the configured range.

Indirect fire includes mortar and artillery entity settings, the PIAT carried by
infantry, the Sturmmörser’s RW61 rocket mortar, and mounted weapons with curved-fire
settings or howitzer presets.
Weapon inheritance and the selected mod's overrides are respected. This indicates
capability with at least one weapon; it does not change an infantry squad or
tank's role classification. Generic projectile gravity alone is not sufficient.
The PIAT and RW61 are explicitly classified because their game definitions
share generic RPG/rocket patterns without a distinct indirect-fire flag.

### Firepower

The Firepower estimates filter section includes help explaining each estimate and its
limitations. Hover over metric labels for a short explanation.

| Metric | Meaning | Useful for |
| --- | --- | --- |
| Burst output | Shots in the first 5 seconds, including reloads | Short engagements against infantry |
| Sustained output | Average rounds per minute across reload cycles | Prolonged infantry engagements and potential volume of suppressive fire |
| Firepower per CP | Sustained output divided by total CP | Comparing purchasing efficiency within similar roles |
| Calibre-weighted output | Sustained output weighted linearly by calibre / 7.62 mm | Comparing similar guns; not a penetration or damage estimate |
| Firing endurance | Time until the earliest included weapon empties its first magazine | Identifying firing windows and reload gaps; longer is not always better |

Primary and secondary weapons have separate stats and minimum-value filters;
their output is never added together. Infantry estimates sum soldiers' first
weapons as primary and second weapons as secondary, using each soldier's quantity.
These are alternative firing options, not simultaneous fire. Vehicles use the
main gun as primary and the next mounted gun type as secondary, including repeated
mounts of the same type but excluding crew sidearms. Additional weapon types have
their own stats. Thrown grenades are excluded. For example, the Valentine Mk.XI
shows 1 primary-gun round and 63 secondary-machine-gun rounds per 5 seconds,
not a combined 64-round estimate. Each slot's efficiency uses the full unit CP.
Estimates assume fully loaded weapons and
unlimited resupply for sustained output. AI pauses, accuracy, aiming, firing
arcs, crew conflicts, explosive damage, range, armour, and survivability are
not modelled. Missing required inputs make the affected score Unknown.

These metrics measure theoretical fire volume, not overall danger or kills.
Against infantry, start with burst and sustained output. Against light vehicles,
also check ammunition and penetration. Against tanks, penetration at range,
ammunition, armour, and impact angle matter: these scores cannot determine
anti-armour effectiveness, regardless of calibre or machine-gun output.

Minimum-value filters use the raw unit estimates. Percentiles alongside the
stats compare the same weapon slot within the active faction and role group;
they are not damage percentages. Additional weapons have no percentile.
Ties share a rank and single-unit groups receive 50.
Zero or missing CP produces an unknown efficiency score. All active filters
must match, and missing weapons or Unknown values do not match a numeric filter.

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

### Steam Workshop mods

No extra arguments are needed. The exporter finds Workshop content for app
`400750` in the game's Steam library and other libraries registered in
`libraryfolders.vdf`. Run both commands above after installing or updating mods.
The viewer's **Mod** selector, immediately left of the faction selector, defaults
to **None** (base game). Select one installed mod to switch its factions, unit
stats, localized names, and images without rebuilding or running a web server.

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

## Deploying a release to GitHub Pages

[The Pages workflow](.github/workflows/deploy-pages.yml) deploys the
`research_tree_html.zip` asset from each newly published stable GitHub Release.
It skips prereleases and does not run on pushes. It downloads the triggering
release's asset, validates it, and uploads the extracted files using GitHub's
official Pages actions. It does not regenerate or commit game data.

Set up the repository once:

1. Under **Settings → Pages → Build and deployment**, select **GitHub Actions**
   as the source.
2. Ensure **Settings → Actions → General** allows GitHub Actions and the official
   `actions/configure-pages`, `actions/upload-pages-artifact`, and
   `actions/deploy-pages` actions.
3. Under **Settings → Environments → github-pages**, ensure deployment rules allow
   release **tags**, such as `V*`. A rule allowing only `main` will block releases.
   Remove required reviewers if deployments should proceed without approval.

Include the workflow in the commit targeted by the next release tag. Attach the
ZIP to the draft release **before publishing**. Its contents must start with
`index.html` and `assets/`, not a wrapping `research_tree_html/` directory. Relative
paths such as `assets/...` are preserved. Missing ZIPs, invalid archives, or missing
root `index.html` files fail with a clear error. After correcting an asset, rerun
the failed workflow from the Actions tab.

No additional secrets or personal access token are required for this deployment.
The download job has `contents: read`; only the deployment job has `pages: write`
and `id-token: write`.

Publish the release through GitHub's UI or an authenticated user/App. GitHub does
not trigger another workflow for releases created by a workflow's `GITHUB_TOKEN`;
this is separate from the default token used to download and deploy the site.
See [GitHub's token event rules](https://docs.github.com/en/actions/concepts/security/github_token).

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
node tests/test_unit_table.js
```

## License

This project's source code and documentation are licensed under the [MIT License](LICENSE).
The license does not cover game data or assets extracted from an installed copy of
Call to Arms: Gates of Hell — Ostfront.

This is an unofficial community project and is not affiliated with Barbedwire
Studios or Digitalmindsoft. Game names and assets belong to their respective
owners.

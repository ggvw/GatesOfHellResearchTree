# Viewer guide

[Back to the project](../README.md)

## Open the viewer

Use the [hosted viewer](https://ggvw.github.io/GatesOfHellResearchTree/), or download
`research_tree_html.zip` from a [release](https://github.com/ggvw/GatesOfHellResearchTree/releases).
Extract the entire ZIP and open `index.html` in your browser. Keep `assets/` next
to it so images load correctly. No web server or game installation is needed to
browse an already generated viewer.

## Navigation and unit statistics

- Choose a faction in the top bar and use search to find a unit.
- In Graph mode, drag to pan, scroll to zoom, or select **Fit tree**.
- Select a graph node or a table unit name to open **Unit statistics**.
- The summary shows CP, RP, total RP including prerequisites, and unit size.
- Resize the statistics panel by dragging its left edge; close it with **×** or Escape.
- Use the theme button to switch between light and dark mode.

## Mods

The viewer's **Mod** selector, immediately left of the faction selector, defaults
to **None** (base game). Select one installed mod to switch its factions, unit
stats, localized names, and images without rebuilding or running a web server.

Required dependencies are included automatically. Available mods depend on what
was installed when the viewer was generated. See the [build guide](development.md)
to refresh game or mod data.

## Views and filters

Choose Graph or Table in the top bar. Graph mode highlights matching nodes;
Table mode lists matching units and removes rows that do not match. Search and
branch selections also filter table rows. Table columns show unit name, CP, RP,
total RP including shared prerequisites counted once, unit size, gun calibre,
weapon range, indirect fire (Yes/No), reload time, rate of
fire, and movement speed. Select a unit name to open its
statistics. Missing values appear as a dash. On small screens the table uses
labelled rows, and filters can be opened with the side button. The viewer starts
in Table mode on small screens and remembers an explicit view choice.

Click or tap a column heading to cycle through ascending, descending, and
unsorted. Each new column is added to the existing sort order. Arrows and numbers
show direction and priority; removing a column promotes those after it.
Cycle all sorted columns back to unsorted to restore research-tree order.
Unknown values stay at the bottom in either direction. Sorting is retained
when filtering or switching factions and views.
Weapon range shows the largest-calibre weapon's configured AI firing range.

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

Min and Max command points (CP) set inclusive limits on total unit CP, including
crew. Leave either blank for no limit; unknown CP does not match an active limit.
Min gun calibre (mm) increments in whole millimetres. Indirect fire offers Yes,
No, or <unselected> (no restriction). Clear filters resets these controls too.

The Infantry section also has Min soldier health, Min base vision (m), and
Min equipped vision reach (est. m), with explanatory tooltips.
A squad matches when at least one soldier meets all active health and vision
limits. Vehicles do not match through their crews.
Unknown stats and zero-count roster entries do not match an active limit.
Each soldier's health, base vision, equipped vision reach, optics sources,
and vision profile appear in Soldier stats.
Health is maximum starting health, including breed health perks, not squad-total
health. Base vision is the configured forward spotting distance against ordinary
standing infantry in Conquest, not a universal detection limit. Target stance,
stealth, cover and line of sight affect actual spotting. Peripheral vision,
scopes, binoculars, and veterancy earned during battle are not included in base vision.

Equipped vision reach is an estimate: the maximum of base vision and each usable
carried scope/binocular's configured direct-control aim distance plus its aimed
spotting radius. The soldier must have the matching ability and equipment tags.
For example, a 130 m scoped rifle with a 15 m aimed radius estimates 145 m reach;
200 m binocular aiming with a 30 m radius estimates 230 m. These are not passive
all-round detection ranges or guaranteed in-game spotting distances: optics need
active aiming and a clear line of sight. Without usable optics the value equals
base vision. Missing required range data is Unknown, not silently ignored.
All active health and vision limits must be met by the same soldier.

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

## Screenshot

<img width="1157" height="795" alt="Screenshot from 2026-10-16 10-15-31" src="https://github.com/user-attachments/assets/e50a340a-5d30-4615-ba6b-6caf54439df2" />

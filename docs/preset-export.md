# Export one combined ModManager preset

Both scripts accept `--preset-config PATH --preset 'Exact preset name'`.
The exporter reads only the preset's listed Workshop directories, overlays them
on the base game in exactly that order, and writes **one combined dataset**.
It does not discover/export other installed Workshop items. Later layers win.
Required dependencies must already occur earlier in the list: missing dependencies,
duplicate IDs, and incompatible dependency ordering fail rather than adding or
reordering anything. Without these arguments the legacy base/per-mod mode remains.

Optional repeatable `--local-layer /absolute/path/to/mod` appends explicitly selected
local mods in argument order. Supply the same arguments to both scripts. No active
profile or local repair mod is implicitly selected. A layer without `resource/`
is retained with a warning; external installers/DLL effects are not emulated.

`datasets.json` records the selected ordered layers, discovered/exported factions,
and resource warnings. HTML checks the requested preset against that recorded
stack and rejects incomplete preset exports. Warnings remain visible; successful
completion does not imply every node or reference parsed without warnings. Changing
mod contents after export still requires re-export (the manifest is not a content hash).

## Hotmod 1968 (Ultrahotmod)

From the repository directory, run these **separately**:

```bash
python3 export_research_trees.py \
  '/run/media/wbw/Big Games/steamapps/common/Call to Arms - Gates of Hell/resource' \
  --preset-config "$HOME/.goh-mod-manager/config.json" \
  --preset 'Hotmod 1968 (Ultrahotmod)' \
  --output research_export_ultrahotmod
```

Inspect faction counts and warnings before building:

```bash
python3 create_research_tree_html.py \
  '/run/media/wbw/Big Games/steamapps/common/Call to Arms - Gates of Hell/resource' \
  --preset-config "$HOME/.goh-mod-manager/config.json" \
  --preset 'Hotmod 1968 (Ultrahotmod)' \
  --input research_export_ultrahotmod \
  --output research_tree_html_ultrahotmod \
  --exclude-factions csa eng fin fra frg ger isr usa
```

These outputs are separate from any partial legacy export. Existing selected output
directories are replaced. The named preset currently lists, in order:

1. 3669674324 — Hotmod 1968 Redux v0.31
2. 2897299509 — West-81
3. 3151234579 — Ultrahotmod
4. 3434019219 — cold war gone hot
5. 3808590860 — Icon Priority Fix (no resource directory)
6. 3646683856 — Minimap+
7. 3814488828 — Auto Resupply and Return
8. 3541253287 — Better GoH - 02 - Environment Visibility - 1.062.0
9. 3651388289 — Cinematic Muzzle Flashes LITE
10. 3805812451 — Crater Cover

Read-only inventory found 14 research trees: `csa eng fin fra frg gdr ger isr nat
pol prc rus sov usa`, including all ten previously expected faction IDs. This is
an inventory, not verification that all records parse successfully.

The inspected active profile differs: it omits `3434019219` and appends
`ultrahotmod_repair_bb611`. The named preset contains **no local BB611 layers**;
the commands above intentionally match the named preset, not that active profile.
Do not add a local repair layer unless that additional overlay is explicitly wanted.
Full export/build runtime has not been measured; allow minutes, especially for HTML
metadata/image enrichment. Only one combined resource stack is processed per stage.

## Operator-selected visible factions

The HTML command above hides exactly `csa eng fin fra frg ger isr usa`, leaving
`gdr nat pol prc rus sov`. This is the operator's supplied selection, **not**
automatic validation against the running game. `--exclude-factions` requires an
explicit preset, rejects unknown IDs and an all-hidden selection, and adds only
per-tree presentation metadata. All 14 exported JSONs, embedded trees, source
records, images and resource dependencies remain intact. Other datasets do not
inherit these exclusions; there is no global vanilla-faction hiding rule.

Local read-only evidence (effective files in Workshop `3151234579/resource/gamelogic.pak`):

- `set/multiplayer/armies/{csa,fin,fra,frg,gdr,nat,pol,prc,rus,sov}.set`
  declares ten IDs/titles/icons, not a verified runtime six-faction selection list.
- `interface/layout/views/DynamicCampaignCreate.xml:56-74,107-125` declares army
  previous/next controls without a literal allowed-army list. The inspected
  `set/dynamic_campaign/values.set` army-pair tables are not a selectable list.
  No authoritative runtime six-ID list was established from these local configs.
- `set/multiplayer/units/roster_conquest.set:22,27,32-33,44-49` actively includes
  CSA, FIN, FRA and FRG infantry/unit sources. Hiding their viewer trees is not
  a reason to remove their source files.
- NAT research `set/dynamic_campaign/unit_research_nat.set:664` grants `ambulance`;
  effective roster lookup resolves the French-side definition in
  `set/multiplayer/units/conquest/units_fra_era1945.set:129`.
- `conquest/units_nat_era1945.set:553` and `units_csa_era1945.set:533` define the
  same `squad_natguard_con_mid` composition under NAT and CSA sides. CSA infantry
  declarations for its `nat_squadlead` member occur in
  `inf_csa_era1960.set:135,1567,1915`, alongside NAT-specific versions in
  `inf_nat_era1945.set:137,1569,1916`. This demonstrates shared/copied unit content,
  not a claim that every CSA-specific file is required by NAT.

The active profile still differs from this named preset as documented above.
The inspected local `ultrahotmod_repair_bb611/1.pat` has no army definitions,
DynamicCampaignCreate UI or dynamic-campaign values file. Research-tree existence,
army metadata and shared roster availability do not prove runtime selectability.
No blanket claim that every file is necessary is made; no game/mod data is deleted.

For the specific RUS/SOV question, `values.set:58-79` contains Europe
`AvailableMatchups` entries `nat sov`/`sov nat` (line 61), `nat rus`/`rus nat`
(line 69), and `sov rus`/`rus sov` (line 79). This establishes configured matchups,
not that both appear in the creation menu. Separately,
`set/multiplayer/games/campaign_capture_the_flag.set:61,67` uses
`armySelectionMode alliance` and includes `presets/alliances_generic.inc`;
that include has active CSA (line 4) and SOV (line 12), with no RUS entry.
The creation-menu runtime filtering was not established, so both IDs remain
visible per operator selection rather than being asserted playable or hidden
based on these different-purpose lists.

## Known source and viewer limitations

Research parsing excludes semicolon-commented declarations. Every parsed source
record is retained in each faction JSON's `research_records`; duplicate records
are also listed in `duplicate_research_records`. PRC has two distinct `zbd86`
grants and POL has two `pol_desnatowa_1960` categories. The interactive viewer
still keys nodes by ID and displays the last definition only, not both grants or
categories. Export warnings and the HTML Data limitations notice explicitly report
this limitation; the retained records must not be mistaken for a fully represented
interactive graph. No engine duplicate-ID semantics are inferred.

The Finnish `single_bazooker_fin_m62` roster contains the malformed member token
`c2(antitank_pzs_ammo:_m621)`. The parser retains `_m621` as `raw_count`, leaves
`count` and derived member-count/cost/command-point totals unresolved (`null`), and
warns. It does not silently repair this to the nearby valid
`antitank_pzs_ammo_m62:1` definition or default its count. The source game/mod files
are unchanged. Other unknown units, breeds, or icons remain visible warnings.

Downstream firepower retains unknown-count infantry members, including an
unresolved primary weapon placeholder when no weapon can be resolved. An affected
weapon slot has unknown weapon count, burst, sustained RPM, RPM/CP, caliber-weighted
RPM, and endurance; those metrics receive no percentile and are excluded from
peer rankings. Known per-weapon profiles remain available. Secondary/additional
slots are affected when that member has a listed weapon in that slot. Vehicle
mount-based firepower does not depend on crew quantity. Explicit zero quantities
remain absent, distinct from unknown quantities.

Roster-group and carried-weapon totals show unknown rather than counting an
unknown member as zero. An anti-tank carrier with unknown quantity makes the
anti-tank weapon total unknown. On-foot slowest-member speed and infantry primary
capacity/rate summaries are left unknown when composition includes an unresolved
count; vehicle statistics and individual member profiles remain available.

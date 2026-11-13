# AI stage graph

Choose **AI stages** next to the faction selector. The existing graph cards,
icons, detail panel, unit filters, zoom and pan remain available. Player research
is a separate mode; AI cards have no prerequisite edges. AI source records are
not inferred from research grants, and AI-only purchases are retained.

Choose a campaign duration and a reachable numbered AI variant, or their union.
Colored columns group first unlock stages and label the actual numeric stage
(sparse stages are compacted); unresolved first stages use **Unknown stage**.
Horizontal headings group the Lua `base` category and show each cell's card count.
Each stage adapts to its largest cell, from two to six card columns. Cells show
at most two tile rows and scroll independently: wheel or scroll the cell scrollbar
to reach every purchase, or focus a cell and use keyboard scrolling. Drag headings
or gaps to pan; wheel over headings/gaps or Ctrl+wheel over a cell zooms the graph.
The initial AI view frames the first three category rows of the first stage at a
minimum 70px card width on a normal desktop. Narrow/short windows may show fewer
rows rather than shrinking cards further. **Fit tree** explicitly fits the full
stage/category overview, including all cell viewports, not all locally scrollable
cards simultaneously; large overviews can have tiny cards. AI overview fitting can
zoom below the research graph's minimum scale; buttons and wheel continue smoothly
from that fitted scale. Switching faction or
AI selection restores the readable initial view. Ordinary unit filters preserve
the current pan/zoom; branch filters rebuild cells for the visible subset.
Cards show their first and maximum stage. **Eligible at stage** removes purchases
outside their known inclusive min/max interval; unresolved purchases remain
visible and are labelled **eligibility unknown**. The duration schedule states
how many games have been played when the selected stage first becomes available;
it does not turn stage numbers into battle numbers by guesswork.

This is configured **stage eligibility**, not actual battle affordability,
selection probability, guaranteed spawning, or confirmation that an AI purchase
passes engine roster-resource checks. Those checks and budget/scoring policies
are not simulated. A maximum stage of 99 remains numeric 99, not infinity.
Missing bounds are absent, unresolved expressions are unknown; neither is
silently interpreted as an unbounded range or a default of zero.

## Effective source and supported syntax

The normal preset overlay order supplies all sources. `script/` is now indexed
alongside the existing resource domains. The inspected preset dispatches from
`script/multiplayer/bot.main.lua` to `modes/conquest.lua`; its
`OnGameStartUtility("conquest")` loader in `modes/utility.lua` selects
`math.random(1, upperLimit)`, where `upperLimit` comes from
`MaxDivisionArmyCount.Faction[army] or 1`. It loads numbered
`script/multiplayer/units/<army>/conquest.<army>.<number>.lua` modules.
The older `bot.conquest.lua` and its `MaxDivisionCount` are not the active loader:
using that older table would omit NAT variants 4–7, SOV 5, RUS 4 and CSA 2–4.
Unnumbered files and numbered files outside that effective range are not added.
A selected-but-missing module is warned, not silently removed from the selector.

The small static Lua reader does not execute Lua. It supports balanced nested
tables, single/double quoted strings, line comments, Lua long comments and long
strings. Strings are opaque tokens: text such as `unit="ghost"` inside a note
never creates a purchase. A direct `unit` value must be one complete literal,
followed by a field delimiter or the table end; a quoted prefix of a concatenation
is not accepted. Quoted strings decode escaped quotes/backslashes, standard Lua
control escapes, escaped newlines, decimal byte escapes (up to three digits,
0–255) and two-digit hexadecimal byte escapes. Other escapes (including `\\z`
and Unicode escapes) remain unresolved with warnings. Long strings support
matching equals-sign delimiters and the ignored initial newline. Decoded purchase
IDs retain source file/line and the raw record; nonliteral or unsupported values
produce retained unresolved records and warnings. Lua function evaluation, dynamic roster generation, arbitrary require
chains, and alternative runtime loaders are not emulated. Unsupported/absent
loaders warn instead of inferring reachable variants from filenames.

Purchase lookup prefers exact SDL IDs (including literal army suffixes), then
template-emitted IDs in the effective conquest roster. Named SDL calls with
literal `key(value)` arguments are expanded through effective balanced `define`
bodies. Bounds are read from the resulting `research_stage` and
`research_stage_max` fields, including literal template defaults and direct
field overrides. Macro aliases never overwrite an existing exact SDL record:
the enclosing record (including its direct fields) remains the lookup value.
Regression fixtures verify this static extraction precedence, not unvalidated
game-engine duplicate-field semantics. Unresolved parameters, arbitrary SDL arithmetic/conditions,
recursive templates and undocumented engine defaults are not evaluated:
unsupported/absent values remain warnings. Existing roster/member/icon enrichment runs on AI-only units as
well. Original/protected-type player policies do not filter AI purchases.

Duration `ResearchStages` strings come from effective `duration_*.set` files.
The documented source direction is `GamesPlayed:Stage`, e.g. `3:2` means stage 2
after three games played. Literal nonnegative integer pairs are supported.

AI records and enrichment live in each exported faction JSON as `ai` and
`ai_nodes`, separately from research `nodes`. Every parsed AI record is retained,
including duplicates across variants; cards union exact purchase IDs. The
current union card uses the first record's category; conflicting per-record
bounds display as unknown instead of selecting one interval. Inspect retained
raw records for per-record differences. Export
and page warnings identify unresolved roster/bound data. Explicit viewer faction
exclusions apply unchanged to both modes; hidden faction data stays embedded.

Run the two preset commands in [preset-export.md](preset-export.md) separately.
No installed game, mod, campaign, or AI configuration is modified.

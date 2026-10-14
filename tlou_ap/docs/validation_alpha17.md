# Alpha 17 validation

The launcher now follows the Renegade desktop layout: horizontal room fields,
three progress counters, an inline campaign tree and a resizable session log.
The separate available-checks counter has been removed. Expand tracker opens
the same campaign component in a larger window, with the shared Light/Dark theme.

All 29 missions remain visible by default. Each enabled check appears once,
with chapter completions under their last mission. Search matches mission,
chapter and check names. Check-type toggles and Hide completed only affect
visible children, never parent/global totals. A completed mission with missed
collectibles stays incomplete. Locally earned checks remain Pending sync until
acknowledged, even with Hide completed enabled. Offline access becomes Unknown
while confirmed progress remains visible. Expansion/selection survive updates.

## Verification

Automated tests cover grouping, unique check ownership, search, category filters,
pending acknowledgements, unfinished collectibles, no-check missions, stale
access, themes, settings persistence and shared inline/enlarged behavior.
Distribution smoke tests exercise the campaign tree with all 181 default checks,
filters, theme switches, reset, the existing settings panels, horn assets and
WebSocket loopback. They use isolated state without attaching to the game.
Archive verification also checks packaged hashes and required assets.
See dist/alpha17-*-validation.json for distribution results.

## Compatibility and limits

This changes only the launcher/tracker and documentation. Native ABI 4 build
d058868d7041f63b, gameplay behavior, save compatibility protection, receipts,
DeathLink, Airhorn recordings and AP world logic are unchanged. Keep the existing
.state folder and close the previous launcher before replacing its files.
The existing seed and AP world remain usable; no game restart is required solely
for this layout change. Alpha 17 keeps its own campaign coverage record.

The tree is informational: an Available row describes chapter/story permission,
not a guarantee that the current save belongs to this run. Save/run mismatch
warnings remain prominent and must be resolved before playing the run.
Broader full-campaign, multiworld and clean-PC validation remains outstanding.

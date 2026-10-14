# Alpha 31: separate test utility controls

The separately built TLOU Test Utility now has Game and Archipelago tabs. The
Archipelago tab contains Collectables, Missions and Unlocks. No test controls
are added to the normal Archipelago client UI.

A local Windows named-memory mailbox binds requests to the attached game and
current client instance. The client serializes them on its normal polling
thread, writes an audit beside the run ledger, and uses its existing server
connection for LocationChecks. Pending and server-confirmed checks have
separate statuses. The utility has no server credentials or AP build dependency.

Collectables call the game's actual treasure pickup routine on the game thread,
including normal inventory/profile/manual effects, and verify inventory presence
before the explicit check is accepted. Already held collectibles are idempotent.
Only the fixed 140-entry main-story catalog is accepted. Collectible checks must
be enabled and their chapter accessible in the active run.

Mission completion is an explicit, persisted AP-only test override. It never
writes native task flags, moves the character, or fabricates gameplay events.
Missions still require chapter access and story order. Completing a chapter's
last mission also earns its enabled chapter check. Overrides survive reconnects.

Unlocks fills shivs or medkits to 3 using native inventory routines and respects
character inventory limits. It creates no server item receipt or received item.
Commands revalidate live mission, heartbeat, inventory and gameplay on the game
thread. Paused requests wait up to 60 seconds; unsent requests cancel on disconnect.
Unknown outcomes are never automatically replayed.

The bridge ABI remains 4. Native build 82ac26ded4f01a85 adds commands 8–10 to the
alpha30/7077cec8ac0ee9cc bridge; gate and DeathLink code are unchanged. Existing
gate/DeathLink regressions and new native command tests pass. A game restart is
required when updating from an earlier bridge. The existing seed is compatible.

Validation: 201 Python tests passed, including a real loopback WebSocket exchange
through production Client.poll and server acknowledgements for collectible,
mission and chapter checks. Native tests cover duplicate collection, full/capped
inventories, character limits, invalid indices and changed/locked scenes. The
standalone utility's existing self-tests also pass. Live gameplay verification
and package results are recorded separately in .research/test-controls.

Source for this release is isolated from the Progressive Tools preview in
.research/test-controls/client. Full campaign validation remains pending.

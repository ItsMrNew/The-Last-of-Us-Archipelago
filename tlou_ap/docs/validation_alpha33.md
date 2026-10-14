# Alpha 33: collectible pickup order

The embedded campaign tracker and enlarged tracker now interleave artifacts,
pendants, comics and manuals in suggested pickup order within each mission.
Automatic starting inventory comes first. Optional nearby pickups can be
visited in either order. Completing or filtering checks preserves route order.

Financial District: Fireflies Note, Final Attack Note, Mob Attack Note, Truck Note.
Route reference: https://www.powerpyx.com/the-last-of-us-ps5-remake-collectibles-guide/

Display metadata covers all 140 existing collectibles exactly once in their
existing missions. No AP IDs, catalog, world, save identity, native bridge or
delivery behavior changes. Existing seeds remain compatible. Native bridge
c40461d60666c46a is unchanged from alpha32; no game restart is required.
The separate alpha31 test utility integration is retained. Progressive Tools
remains in its separate preview pending the deferred live test.

The remaining QTE/DeathLink candidates stay parked until final-release testing:
Bus Depot submerged-bus/drowning rescue; Lakeside Resort finale crawl, horse
struggle and Joel ambush; University rebar (exclude the scripted story injury);
Alone and Forsaken saving Ellie; Bill's Town truck escape; Pittsburgh pursuit;
Suburbs sniper chase; Firefly Lab operating-room and escape failures.
These are potential gaps, not confirmed missing DeathLinks. Verify exactly one
event for fatal player failures, normal reload/rearming, no incoming-death echo,
and no events for success, manual reloads or scripted story events.
Full checklist and evidence: workspace docs/native-research.md.

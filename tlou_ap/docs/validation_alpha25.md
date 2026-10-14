# Alpha 25: collectibles before subchapter boundaries

The Medical Pamphlet is assigned to Museum in the game's treasure catalog,
but the live run recorded its award while Downtown was active. Native events
466 (pickup, flags 1) and 467 (profile award, flags 3) contained its SID
`a230bcda4867dee1`; neither was quarantined. The client required Museum's
mission access before recording either event, so the check was lost.

Pickup eligibility now requires the collectible's chapter to be unlocked and
reachable in story order. Its display grouping is independent of this check.
Live award evidence and a started managed run are still required. Inventory
restores with the award flag clear do not count. Mission completion, foreign
save quarantine and chapter gates are unchanged, as are all location IDs,
names, slot data and the world graph. No seed regeneration is required.

Regression coverage includes the observed Downtown/Museum pickup, duplicate
pickup/profile events, persistence after restart, unchanged mission completion,
locked and unreached chapters, unstarted runs and inventory restores. Final
test and package results are recorded in `.research/alpha25-tests.txt` and
`dist/standalone-validation.json`. Full campaign validation remains pending.

Client-only update. Native build remains `e80002c9e90a1217`, ABI 4. Restart
the client while preserving the game, saves, `.state` and existing seed.

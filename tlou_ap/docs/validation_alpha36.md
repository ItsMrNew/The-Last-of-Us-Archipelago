# Alpha 36: automatic save progress scan

The Save guide now scans all readable save slots against the same progress
comparison used by the live managed-run guard. Green means Compatible; red
means Incompatible or explicitly known to belong to another run. Amber means
the format/progress could not be verified. Gray means the save is unavailable.
No manual ownership confirmation is needed for the automatic progress check.

Green is not proof of ownership: an unrelated older playthrough can pass the
progress guard. It does not bypass chapter locks, grant checks, or make an
advanced save compatible. The existing fingerprint ownership notes are retained.
Select a save in the launcher for the rejection reason or compatibility details.
F9 toggles the click-through in-game guide. Native menu text is unchanged.

The reader supports the observed 1.1.3.0 main-story save format (magic 60050).
It requires two complete copies of the known 602 task identifiers in order,
72-byte records, matching serialization markers, difficulty values in range,
and agreement between both task copies. Unsupported, truncated, malformed or
disagreeing data remains unverified. Save files are checked for concurrent writes.
Reads never modify a save or load it into the game. UI scans run every five
seconds while the guide is open/enabled, and re-evaluate the current run ledger.

Read-only local validation found 21 supported saves, 17 compatible and 4
incompatible against the current run. The current autosave's 29 mission values
matched live task telemetry. Script-presence metadata also matched the earlier
602-node research snapshot. Synthetic tests cover all 30 completion boundaries
at all 7 difficulty levels, malformed/copy disagreement cases, overwrites,
guard agreement, and known ownership interactions.

Native bridge remains 96b4d08a1aa9aec5, ABI 4. Updating from alpha35 only needs
a launcher restart. The installed run, seed, receipt state and saves are kept.
Progressive Tools remains a separate preview; remaining QTE live tests and
persistent offline play remain parked. Alpha34's ammo threshold still has its
previously deferred live gameplay test.

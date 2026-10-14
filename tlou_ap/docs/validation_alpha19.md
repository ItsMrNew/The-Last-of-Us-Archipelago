# Alpha 19 validation

Item transfer colours follow the server's classification for all games, including
The Last of Us. Progression, useful, trap and filler retain the Zero Hour palette
and combined-flag precedence. Item names and local definitions never override
the classification. Missing, malformed or unrecognized metadata displays neutral.

Archipelago console grants can default to zero without determining item type.
Zero flags at synthetic negative locations therefore display as unknown, while
real checks with zero flags remain filler. Explicit nonzero classifications on
grants are respected. Plain server messages without item metadata remain neutral.
Data packages provide names, not a universal classification catalogue.

Automated checks cover foreign game names, conflicting local definitions, all
four types, combined flags, unknown grants, deduplication and reconnection without
inventory notification replay. All 166 Python tests pass. The packaged client smoke test exercises actual
launcher log spans in both Light and Dark themes, using isolated state and a
loopback WebSocket. No items are sent to the live room.

The native bridge is unchanged from alpha 18 (ABI 4, build f818afd2465a624d).
No new seed or game restart is needed when updating from alpha 18. Keep `.state`
and restart the launcher. Earlier bridge updates still require the game restart
described in alpha 18's validation. Its remaining campaign test coverage applies.

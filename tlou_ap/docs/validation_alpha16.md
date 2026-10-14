# Alpha 16 validation

The alpha 15 client assumed an address without a scheme meant a plain WebSocket.
The user's hosted Archipelago room required TLS, so it closed the connection
before returning an HTTP handshake. The client stopped with `InvalidMessage:
did not receive a valid HTTP response`, before any slot authentication.

Alpha 16 follows Archipelago CommonClient's negotiation behavior: try the
requested address, then upgrade `ws://` to `wss://` if the opening handshake
raises InvalidMessage. It upgrades once, before processing any AP packets.
It remembers the resolved address for reconnects during that client connection.
It never downgrades TLS or disables certificate verification. Local plain
WebSocket rooms still connect normally. Other handshake failures are reported
and retried by the launcher's existing reconnect loop.

## Verification and scope

Seven targeted regressions cover TLS upgrade, secure reconnects, changing from
a secure host to a local plain host, failed upgrade, TLS certificate rejection,
cancellation cleanup and established-session/authentication errors. The latter
must not trigger another transport attempt. Existing protocol tests exercise
actual loopback WebSocket connections and reward/check deduplication.

The real room was probed without logging into any slot: plain WebSocket
reproduced the failure, while verified TLS received RoomInfo. Distribution
checks use the production connection helper for their loopback test. The optional
`--self-test-server` argument reads only a remote RoomInfo packet and never sends
Connect, checks, chat, gifts or goal packets. It does not attach to the game.
See `dist/alpha16-validation.json` and the source, frozen-room and archive
verification reports for final results.

This update retains alpha 15's five horn recordings and the same ABI 4 native
build d058868d7041f63b. AP world logic, slot options, existing seeds and receipts
are unchanged. Preserve `.state` and close the previous client before updating.
Alpha 16 stores campaign coverage separately; earlier records remain intact.
No game restart is needed solely for this connection fix.

The room probe establishes transport and certificate handling, not full slot
authentication or a multiworld playthrough. The broader campaign and clean-PC
validation described in previous reports remains outstanding.

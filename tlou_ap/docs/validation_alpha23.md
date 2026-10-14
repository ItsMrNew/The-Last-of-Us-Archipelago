# Alpha 23: pending rewards in the status area

Pending supply names, grouped quantities and waiting reasons now appear directly
under the mission/delivery counters. The details update with the existing live
delivery snapshot and disappear when no supply rewards remain. Disconnected
status is labelled as waiting to reconnect; held rewards retain their recovery
warning. Airhorn and DeathLink continue to use their existing status counters.

Ordinary deferred supply attempts no longer write waiting messages to the session
log. Successful deliveries and uncertain receipts still log immediately. Native
retry timing and durable receipt handling are unchanged. This replaces alpha 22's
30-second waiting-message throttle.

Client-only update; native build remains `e80002c9e90a1217`, ABI 4. Keep existing
seeds, saves and `.state`. Only a client restart is needed. Previous gameplay
validation and campaign test limits remain as documented in validation_alpha21.md.

# Alpha 22: quieter queued-reward logging

Repeated "queued until inventory is ready" log messages are limited to one per
reward every 30 seconds during a client session. The first waiting message is
immediate. Delivery attempts keep their existing timing, and delivered/held
messages remain immediate. Reconnecting the room in the same launcher session
retains the cooldown; restarting the launcher starts a fresh logging cooldown.

Client-only update. Native build remains `e80002c9e90a1217`, ABI 4. Existing
seeds, saves, inventory receipts and mission progress are unchanged. See
validation_alpha21.md for the preceding mission progress fix and its test limits.

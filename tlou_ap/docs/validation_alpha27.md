# Alpha 27: named delivery messages

Supply delivery messages use the received item's catalog name instead of its
receipt number, for example `Reward Shiv: Delivered.` Recovery warnings also
name the item. Pending rewards remain in the launcher's status area.

Delivery, retry, persistence and native game behavior are unchanged. This is a
client-only update; preserve saves, `.state` and the existing seed. No game
restart or seed regeneration is required for this message change.

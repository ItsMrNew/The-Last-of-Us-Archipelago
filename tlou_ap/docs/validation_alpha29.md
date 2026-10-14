# Alpha 29: Pittsburgh opening QTE DeathLink

The fatal broken-glass struggle in Alone and Forsaken uses a scripted failure
instead of the normal player death signal. The detector now accepts that
specific task in Pittsburgh as well as the existing prologue failure path.
The checkpoint task resets the latch even when the actor survives the reload.

Native regression tests cover one event per failure, repeated observations,
checkpoint rearming, unrelated Pittsburgh tasks, incoming death echo prevention,
and the existing prologue story-death exclusion.

Live verification passed on bridge `7077cec8ac0ee9cc`: one deliberately failed
QTE produced one local native death event and one outgoing mailbox notification.
Checkpoint restart cleared the latch, with zero native errors. The test had no
network socket and sent no death to Renegade. The user confirmed the checkpoint
reloaded and pause worked. All saved Archipelago state files stayed unchanged.
Nineteen Python DeathLink tests and the native harness passed. A second live
failure after reconnecting to the room remains a playthrough check.

Siphon Hose and Force Carrier are automatic story pickups. The game awards them
on entering Pittsburgh and can award them again on checkpoint reload. A locked
chapter prevents check credit until access is granted; repeated awards do not
send duplicate checks. These are not rewards for dying.

This hotfix is based on alpha27 and does not include the alpha28 Progressive
Tools preview. Existing seeds and managed run state are preserved. Full campaign
coverage and other scripted deaths still need testing.

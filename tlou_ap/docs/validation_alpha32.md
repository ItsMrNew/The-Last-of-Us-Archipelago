# Alpha 32: Hotel Lobby drowning QTE DeathLink

The hunter drowning struggle uses task-fail-if-active!, whose fail event comes
from a different callsite than task-fail!. The detector now accepts that exact
callsite only in the observed Hotel Lobby task a78b83f44520de9e. Restarting that
task clears the failure latch. Original event arguments and behavior are retained.
No generic script failure or checkpoint reload is treated as a death.

Live bridge c40461d60666c46a recorded one local death and one mailbox notification
for a deliberately failed struggle, then reset and rearmed after normal reload.
The user confirmed normal death, checkpoint recovery and restored camera. Zero
native errors. The test had no network socket and sent no death to Renegade;
the existing run ledgers and settings stayed unchanged.

The first diagnostic callback recorder did not preserve every native argument
and interrupted the failure/reload. It was detached and is not part of this
build or validation. Restart Checkpoint restored the game before the successful
test of the production event hook.

Native regression coverage includes exactly-once deaths, repeated failure plus
normal death signals, same-actor checkpoint rearming, wrong tasks/calls, menus,
locked missions and incoming-death no-echo. Existing prologue story-death
exclusion, Pittsburgh QTE, gate, supply, Airhorn and test-command tests pass.

Based on alpha31: preserves the separate test utility and alpha30 mission
tracking fixes. Progressive Tools stays in its separate untested preview.
Successful QTE playthrough and other parked scripted failures remain live checks.
Preserve saves, .state and the existing seed. Normal installs require restarting
the game; this development session swapped the bridge while paused and isolated.

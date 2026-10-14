# Alpha 11 validation

This release adds Shiv rewards and changes Ammo Supply to add half of every
owned weapon's current maximum total ammo, capped at that maximum. Odd
capacities round up. Existing Ammo Supply and Health Kit IDs remain stable;
newly generated seeds include Shivs. Update the client and native DLL together
and restart the game: the shared-memory interface is now ABI 3.

## Automated checks

- 104 Python tests, including per-item eligibility, full inventory handling,
  saved deferred receipts, reload/retry and duplicate protection.
- 37 native test groups exercise the actual bridge command code with isolated
  game callbacks: all nine ammo types, holstered weapons, half-capacity math,
  partial-batch uncertainty, consumable caps, Ellie shiv deferral, playable-state
  checks and the deer-hunt exception. Existing mission gate and DeathLink
  tests remain passing.
- Official Archipelago 0.6.9 generation with the expanded filler pool: all 83
  valid option combinations, five additional default seeds, five DeathLink
  seeds and a two-player mixed-options world. Tracker logic is checked at
  every progressive chapter stage.

## Live supply evidence

Tests use the isolated, backed-up test save pack and an offline command lab.
No real AP server, run ledger, checks or goal packets are involved.

Pre-release testing confirmed Joel's nine owned weapons receive the expected
half-capacity additions while holstered. A second gift filled each remaining
space; a third remained undelivered. Counts were rechecked on later frames.
Shivs reached three, medkits reached three, and full inventories rejected
further effects. Duplicate receipts did not grant twice. A medkit deferred
while paused subsequently delivered; a shiv deferred while Ellie was active
subsequently delivered to Joel.

Live testing found that the opening deer-hunt task restores Ellie's arrow
count after a grant. The final build defers the entire Ammo Supply during
that task. It does not spend the gift on only the pistol. Medkits remain
eligible when Ellie is playable; crafted shivs wait for Joel.

The final build also passed the hunting-task deferral, medkit delivery,
mission-lock refusal, pause and Load Game navigation during a hold, and
release without closing the player's pause menu. The same refused medkit
receipt subsequently delivered once to Joel in Outside. The deferred Ammo
Supply then correctly refilled all nine owned weapons, with counts confirmed
on later frames. Replaying both receipts added nothing; a Shiv remained queued
at the three-shiv cap. Detailed final-build results and hashes are recorded in
`dist/gate-validation.json`.

Cutscene deferral has code and automated coverage, but the attempted live
opening-cinematic test via Chapter Select started after the cinematic. It is
not counted as a live cinematic pass; that test remains pending.

## Limits

This is targeted alpha testing, not complete campaign certification. Every
scripted inventory transition, all cinematic types, natural outgoing
DeathLinks, remaining collectible acquisition paths, a complete multiworld
campaign and installation on a second Windows machine still need coverage.

The game and AP client save independently. Loading an older checkpoint can
remove a supply already delivered after that checkpoint; delivered gifts are
not automatically granted again. Gifts still queued remain in client state.
If a crash leaves an effect uncertain, it is held for recovery, not blindly
replayed or silently deleted. See the setup guide for receipt recovery.

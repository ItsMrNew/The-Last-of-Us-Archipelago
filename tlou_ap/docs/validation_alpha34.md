# Alpha 34: wait for a drawn weapon at half ammo or less

Ammo Supply stays queued until the drawn weapon's loaded rounds plus reserve
are at most half its current maximum total capacity. Holstered weapons do not
trigger delivery. Once eligible, the same gift adds half capacity (rounded up)
to every owned supported weapon, capped at each maximum. No new item IDs,
world options or seed changes are needed.

The launcher displays the waiting reason. The game thread rechecks the drawn
weapon and ammo before applying the gift, so holstering, switching or picking
up ammo after a client poll cannot spend an ineligible reward. Refused commands
do not consume their receipt, and later retries use the same receipt.
Pause, cutscene, mission-lock, backpack and deer-hunt guards are retained.

56 targeted Python tests passed, including queues surviving reconnect, inclusive
and odd thresholds, unrelated supply delivery, receipt recovery and trackers.
The native implementation passed 60 isolated harness cases, including late
eligibility changes, half-capacity boundary, odd capacity, duplicate receipts,
batch caps, partial delivery, existing gate, DeathLink and test utility commands.

Native build 96b4d08a1aa9aec5, ABI 4. The gate and hooks are unchanged from alpha32;
only the ammo eligibility predicate and its use changed. This build requires a
game restart. The new ammo threshold still needs a live gameplay test.
Remaining QTE candidates remain parked on the final-release checklist.
Progressive Tools remains a separate preview pending its deferred live test.

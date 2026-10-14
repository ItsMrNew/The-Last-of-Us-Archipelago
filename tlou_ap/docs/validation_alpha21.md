# Alpha 21 validation

Client-only update; native build remains `e80002c9e90a1217`, ABI 4.
Existing seeds, saves, run ledgers and the AP world remain compatible.

## Mission progression fix

The real managed run entered Beyond the Wall after completing 20 Years Later.
Task `1ffa0666eaa14f80` was observed starting automatically and the game marked
it completed, but it emitted no type-6 completion hook event. Requiring that
event made the client mistake legitimate progress for an imported save. It then
quarantined the final task completion and held Beyond the Wall.

The observer now supplements hooks with a task's incomplete-to-complete change
only after observing its live automatic start in an allowed mission. It resets
this tracking across Play/Begin requests (loads, restarts and explicit level
starts). An already-completed snapshot, an unobserved task or a locked mission
does not create evidence. The aggregate native mission completion is still
required. Inferred evidence is recorded with `source: live_task_difficulty`.

Events are read after the stable task snapshot. A newly detected mismatch keeps
its events for one further poll, covering the interval between a native flag
write and publication of its completion hook. A persistent mismatch still
blocks gameplay and quarantines events.

Nine focused regressions cover missing hooks, exact-once reconciliation,
same-poll transitions, checkpoint/load boundaries, initial completed snapshots,
locked missions, delayed hook publication and foreign-save rejection. Tests
exercise the production NativeAdapter observer, not the preflight fixture that
pre-completed mission prerequisites. The earlier preflight did not cover this
natural progression path; see validation_alpha20.md for its narrower results.

Further natural transitions, particularly cinematic skips, remain part of the
campaign playthrough audit. This update does not claim full campaign validation.

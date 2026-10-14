# Alpha 26: mission transitions in one polling batch

The live run completed Museum with event 517 and automatically started The
Capitol Building's opening task (`4ac65ae812106da1`) with event 518 in the same
batch. The observer evaluated the new task against the session's old mission
progress and discarded its start. This task emitted no completion hook.
At the end of The Outskirts the native completion flag was set, but the ledger
was missing that one required task, causing a false save mismatch at The Woods.

The observer now previews mission access using the current batch's completion
events, existing managed-run evidence and the native completion snapshot.
It considers inferred predecessor completions before new mission starts.
Validated completion events are then committed in mission order, confirming
each predecessor before processing evidence from the next mission.

The preview does not write state. Snapshot flags alone, unobserved tasks,
loads/restores and locked chapters still cannot authorize inferred completion.
All required live evidence and aggregate native mission completion are still
necessary. No native DLL, location IDs, slot data or world graph changed.

Regression tests exercise the production observer across a transition batch,
missing hooks on both sides of a boundary, multiple completions in one poll,
reordered completion events, locked chapters, snapshot-only progress and
restore invalidation. Results are in `.research/alpha26-tests.txt`; packaged
verification is in `dist/standalone-validation.json`. Full campaign validation
remains pending.

The affected run's recovery is separately audited against its own event log
and current native task state, with backups taken before application. The
recovery restores the Capitol Building and Outskirts completion checks and
retains the two observed Woods preparation task completions; it does not
complete The Woods or grant a chapter unlock item.

Client-only update, native build `e80002c9e90a1217`, ABI 4. Preserve saves,
`.state` and the existing seed. A game restart is unnecessary.

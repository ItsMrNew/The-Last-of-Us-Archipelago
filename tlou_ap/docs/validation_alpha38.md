# Alpha 38: client failure-path review

Reviewed the stable alpha37 client paths for run switching, save classification,
network reconnect, reward receipts, DeathLink and Airhorn dispatch. Root source
remains the deferred Progressive Tools preview; it was not used for this build.

Four confirmed issues fixed (all client-side):

1. A failed launcher-settings write during run selection left the UI and active
   run name switched while the saved selection still named the old run. Selection
   is now persisted before changing run state, credentials, tracker or queues.
2. Client/Test Utility initialization failures bypassed native-adapter cleanup.
   A Test Utility cleanup exception also skipped it. Adapter cleanup now runs
   even when initialization or the other cleanup step fails.
3. Notification history assigned its new identity before loading and validating
   the history file. After a failed read, reconnect skipped validation and could
   overwrite history and repeat old notifications. New feed identity/history is
   committed only after successful validation. Non-object JSON is rejected as
   a normal validation error, allowing the client to disable optional notices.
4. An unexpected exception in the background save reader left its busy flag set
   indefinitely, with stale labels displayed. Every failed scan now returns an
   unavailable result, clears old entries, and permits the next scan to recover.

Seven added regression tests reproduced the errors before the respective fixes.
The existing YAML-export UI test now supplies its own slot name, since new run
profiles intentionally start blank; previously it waited indefinitely on a
validation dialog. Full suite: 246 tests passed. Tests use temporary state and
mock adapters/local sockets; no actual game commands or room checks are sent.

Native bridge stays 96b4d08a1aa9aec5, ABI 4. No save payloads, live ledgers,
reward receipts, item pool or gameplay hooks are changed by this update.
Only a launcher restart is needed to update from alpha37.

Release validation still requires the previously parked campaign/QTE tests and
a live two-room run-switch test. Automated tests do not certify every native
gameplay path. Persistent offline play and Progressive Tools remain deferred.

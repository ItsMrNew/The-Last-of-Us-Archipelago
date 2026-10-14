# Alpha 30: mission evidence after locked entry and checkpoint reload

Two client tracking gaps blocked Hotel Lobby after a completed Alone and
Forsaken: its opening root completed while Pittsburgh was locked and was
discarded, and the QTE checkpoint start shared a restore batch and never
rearmed live difficulty tracking.

The client now retains a verified automatic start/completion for the next
mission's root while loading behind a chapter gate. It promotes that evidence
only when access is granted. This does not award locked checks or admit arbitrary
future mission completions. The evidence survives client restarts.

After a restore, automatic starts require a later unfinished baseline before
their live difficulty changes can count as completion. Restored completed flags
alone remain insufficient. Native build 7077cec8ac0ee9cc is unchanged, including
the alpha29 QTE DeathLink fix. Progressive Tools remains in a separate preview.

The reported run's recovery uses its original opening completion hook, QTE
restart and subsequent live gameplay evidence, final completion hook, and current
native aggregate completion. Only Alone and Forsaken's mission check is added;
Hotel Lobby is admitted but not completed. Items, collectibles and receipts are
preserved. Backups and replay reports are in .research/pittsburgh-qte.

Validation: targeted progress and run-ledger tests cover restore rejection,
post-reload rearming, locked root persistence, no early checks, and ordered
transition processing. Broader campaign transition testing remains required.

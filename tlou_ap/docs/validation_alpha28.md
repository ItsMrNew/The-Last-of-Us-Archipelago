# Alpha 28 preview: Progressive Tools

PREVIEW ONLY. Native build `b272fce070b80e2f` is not admitted for normal
campaign attachment until a live test is completed. Alpha 27 remains installed.
The user requested building now and deferring the live tool grant until later.
Automated package success does not mean live native validation has passed.

## Behavior

- New useful item: Progressive Tools (ID 19710005). Existing IDs are unchanged.
- YAML option `progressive_tools`: 0 to 5 copies, default 5; limited by available
  pool space after chapter unlocks. These items replace filler slots and are
  excluded from the Airhorn percentage calculation. No access rule requires tools.
- Each gift records an absolute target one level above the current tools,
  capped at 5. Normal toolboxes remain available. Parts are still required at
  workbenches; the item does not purchase upgrades or grant parts.
- Gifts wait for stable Joel gameplay, a matching managed run and unlocked
  mission. Menus, cutscenes, loading, death, Sarah and Ellie defer delivery.
- Durable targets make receipt replay and checkpoint restoration idempotent.
  An older save restores previously granted targets; higher native levels are
  never reduced. At level 5 the gift completes without exceeding the cap.
- Pending rewards appear in the existing status area and delivery list. The
  launcher displays the current tool level. Useful item colour comes from AP flags.
- Old slot data remains byte-for-byte compatible when the new option is absent.
  Existing rooms keep their original pool. Newly generated tool seeds require
  the updated client and world.

## Native evidence and remaining test

The game's treasure catalog entries 140-144 are named Tools Level 1-5 and have
category 4. Inventory serialization at 0x17ed568 stores these consecutive owned
treasure entries as `tool-level`; restoration at 0x17eed9c uses the normal
treasure pickup function, 0x13664ec, with both award/inspection flags false.
The new command follows that path on the game thread. It does not patch toolbox
scripts, write arbitrary profile flags, or change mission locking/death/trap code.
Telemetry uses one previously reserved ABI 4 weapon word.

Automated coverage includes native level discovery, invalid/nonconsecutive
entries, zero-to-five grants, repeated targets, reload restoration, capped gifts,
locked/nonplayable/wrong-character refusal, receipt recovery after interruption,
normal tool progression, legacy slot data and all pool settings. The existing
native gate, supplies, DeathLink and Airhorn harness also passes.

Before admission: restart the game with this bridge in the isolated test harness;
observe the workbench level, grant one bonus, check upgrade eligibility, reload
the checkpoint and reconnect, then collect a normal toolbox. Verify no extra
checks or duplicate bonus levels, and rerun the gate/menu/unlock smoke test.
Do not replace the user's stable launcher or installed AP world before that test.

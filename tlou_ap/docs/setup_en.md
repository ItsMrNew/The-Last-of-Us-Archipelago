# The Last of Us Part I — Archipelago

Main-story integration for Windows and the fingerprinted 1.1.3.0 AVX2
`tlou-i.exe`. Left Behind is not included. Read VALIDATION.md for the exact
build's tested behaviour and remaining acceptance checks.

## Install and connect

1. Install `tlou_part1.apworld` through Archipelago's **Install APWorld** action,
   then restart Archipelago Launcher.
2. Open **The Last of Us Part I Client** in Archipelago Launcher. The APWorld
   includes the Windows executable; first launch extracts a verified local copy.
   No separate Python installation or client download is needed.
3. Use Archipelago's option creator to generate your YAML. New item options
   require a new seed; existing rooms retain their original item pool.
4. Start the supported game normally, enter your room server and slot in the
   client, and connect. Enter a room password only when required.
5. New managed runs begin with New Game in Hometown. Resume an existing run
   with a compatible save belonging to it. Restart the game when switching runs.

Alternatively, extract the standalone Windows ZIP and run `TLOU Archipelago.exe`.
Both executable launch methods share run data at
`%LOCALAPPDATA%\TLOUArchipelago\.state`. Versioned executable caches live under
`%LOCALAPPDATA%\TLOUArchipelagoLauncher\clients`; updating the APWorld does not
replace run data. Do not run two clients against the same managed run concurrently.

When upgrading from alpha40's portable `.state`, close the old client, install
and launch the updated standalone client from that same folder once **before**
opening the APWorld client. It copies the legacy data into the new location only
when no central profile exists, and retains the original. If a central profile
already exists, back up both and import deliberately; the client never merges or
overwrites them automatically.

The standalone launcher includes Python; a separate Python installation is not
required. The source package needs the dependencies listed in pyproject.toml.
Windowed or borderless mode supports the click-through notification overlay.

## Checks and progression

The full main-story catalog has 29 mission completions, 12 chapter completions,
and 140 collectibles. Each category can be disabled in the YAML. Mission means
the game's subchapter. Progressive Chapter Unlock opens the next chapter in
story order; its missions still require their preceding mission completions.
The goal is completing Jackson's epilogue. The client remains connected after
completion, including DeathLink when enabled.

Locked gameplay is paused after scene loading. The pause menu stays available
for loading a compatible save or returning to the main menu. The overlay names
the required unlock or reports a save mismatch. Receiving the required item
releases the hold without closing an already-open pause menu.

The campaign tracker lists missions and checks in suggested pickup order.
Search, check-type filters and Hide completed reduce the list. Orange means
available/in logic, red means locked, and green means complete. Total checks,
checks in logic and chapters unlocked appear above the tracker. Light and Dark
themes apply to the launcher and its auxiliary windows.

## Saves and multiple runs

Keep one manual game save per run. To switch rooms: disconnect, restart the
game, select the managed run, connect, then load that run's save. Each run has
its own short description and server/slot settings. Passwords are not retained
between run selections. New managed run creates another entry.

Save guide (F9) is an advisory overlay, not recolouring of native save-menu rows.
Green means the save passes this run's progress guard or has a confirmed link;
red means rejected or linked elsewhere; amber means it cannot be verified.
Matching progress alone is not proof of ownership. New/overwritten saves are
rescanned. Loading an incompatible save does not unlock or award its progress.

Back up saves and run creates a local ZIP with hashes. Pause before backup.
The backup does not modify saves. Previously awarded AP checks remain recorded
when loading an earlier checkpoint. Consumables already delivered are not
granted again to compensate for checkpoint rollback.

## Helpful items

- Ammo Supply waits for a drawn firearm with **50% or less of its maximum
  total ammo**, including loaded rounds and reserve. It then adds half capacity
  to every owned weapon, capped at each maximum. A holstered weapon cannot
  trigger delivery. Queued supplies can deliver consecutively while eligible.
- Health Kit adds one medkit; Shiv adds one crafted shiv. Carry limit: three.
  Shiv waits for Joel; Ellie uses a permanent switchblade.
- Crafting Cache adds one full unit of each crafting material, capped individually.
- Workbench Parts adds 25 parts. Supplement Stash adds 10 supplements.
- Progressive Tools raises the tool level by one, capped at five. Normal toolboxes
  remain. Parts are still needed for upgrades. Saved absolute tool targets prevent
  duplicate increments and restore earned AP tool levels after older checkpoints.

Supplies wait for stable playable inventory, available space and an unlocked
mission. Menus, cutscenes, loading, death and the early temporary inventories
defer delivery. Ammo also waits through Ellie's opening deer hunt, whose script
restores arrows. Pending names and reasons appear below the launcher totals
and in Deliveries; ordinary waits do not repeatedly fill the session log.

Inventory generally carries through chronological chapters, subject to native
character changes, scripted resets and save loading. An interrupted consumable
whose outcome cannot be proven stays held rather than risking a duplicate.

## Traps and DeathLink

Airhorn Trap emits noise that enemies hear and plays a horn sound. Single blast
emits once; timed mode repeats during 30–120 playable seconds. Three 30-second
timed traps stack to 90 seconds. The five installed recordings shuffle between
blasts without consecutive repeats. Volume controls sound, not enemy hearing.
Enemies retain their normal searching behaviour after noise stops.

Shaky Hands adds the approved stronger aiming sway for 30 playable seconds.
Shots follow the moving reticle. Faulty Flashlight varies only the player's
flashlight brightness for 30 playable seconds; it does not turn an off lamp on.
Copies stack within each trap type; different trap types can overlap.

Trap timers wait through menus, cutscenes and locked missions. Confirmed deaths
clear active stacks, independently of whether DeathLink is enabled. Wholly
unstarted queues remain waiting. Cancelled stacks remain cancelled on reconnect.
Native timed-effect leases expire if the client stops, restoring normal effects.

DeathLink can follow YAML, be enabled, or disabled in Live settings. Received
deaths wait until controllable gameplay; disabling preserves waiting deaths.
Confirmed outgoing deaths include the recorded fatal QTE/companion failures.
The prologue's scripted story death is excluded. Received deaths do not echo.

## Launcher tools and notifications

Deliveries shows queued effects, waiting reasons, held receipts and optional
completed history. Live settings controls DeathLink, Airhorn mode/duration,
volume, notification corner and display duration. Changes apply after pressing
Apply live settings; existing trap receipts retain their recorded duration.

Two transfer cards appear at once; later cards queue. Effects do not wait for
cards. Card timers pause while Alt-Tabbed. Item colours follow the server's
classification for any game, with a neutral colour for unknown classifications.
The launcher no longer includes reward-retirement, YAML-creation or campaign-
coverage controls. YAML generation remains available through Archipelago.

## Disconnect and recovery

Keep the client running when disconnected and reconnect to the same run.
Persistent offline play across a client/game crash is not implemented; keep
backups and avoid treating an offline session as guaranteed durable progress.
Do not delete `.state` to fix an error. Preserve logs and the backup when
investigating held deliveries or incompatible saves.

Closing the game removes injected hooks. To play without the mod, restart the
game and leave the AP launcher closed. Back up run state before uninstalling.
The separate Offline Test Lab is for isolated testing and never sends real
checks. Restart the game before returning from a lab to a managed run.

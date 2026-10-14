# Alpha 15 validation

Alpha 15 replaces the single synthesized horn with the user's five selected
ZapSplat recordings: Airhorn single blast 1, 6, 3, 2 and 11. Every available
recording is used once in a shuffled order before reshuffling; no recording
repeats immediately across the pool boundary. Rotation continues across traps.

The MP3 downloads were manually supplied by the user and converted to 16-bit
stereo PCM at their original 48 kHz sample rate. Durations, levels and original
downloads are preserved. All five WAVs are distinct, non-silent, unclipped and
shorter than the five-second pulse interval. Attribution and source URLs are
included with the mod. Conversion tools are development-only dependencies and
are not needed or bundled at runtime.

## Compatibility and scope

Native build d058868d7041f63b, ABI 4, is unchanged. No native hooks, game memory
writes, enemy hearing commands, delivery receipts, trap durations or AP world
logic changed. The recording is selected only when an applied blast reaches
the existing sound notification path. Single blasts, mute, volume, cutscene
deferral, paused gameplay time and 30/90-second timing retain their behavior.

Keep `.state` when updating. Airhorn journals stay at version 3. Alpha 15 starts
a separate coverage record; previous records remain intact. Restart the client
to use the new sound pack. No game restart is required for this audio update.

## Verification

The sound tests cover six blasts over 30 seconds and 18 over stacked 90 seconds
through the production Airhorn/overlay path with a simulated native clock.
They verify silent waiting and pauses, every recording used before reshuffling,
no adjacent repeats, volume scaling, mute preserving the next selection,
cache refresh after audio changes, and fallback after missing/malformed audio
or audio-device failures. Playback is mocked in these automated tests.

Distribution smoke checks require all five selected recordings and verify their
hashes, decode their PCM, and scale each at 50% without playing sound. Source
and standalone archives are checked after extraction in isolated state; the
standalone runs without external Python on PATH. These checks do not attach to
the game or modify managed-run state or saves.

See `dist/alpha15-audio-import.json`, `dist/alpha15-validation.json`,
`dist/standalone-validation.json` and the archive verification reports for the
completed checks and artifact hashes. The earlier alpha 14 Capitol Building
live test established silent cutscene deferral, 90 gameplay seconds/18 pulses,
pause timing and user-observed soldier searching using the same native bridge.
See `validation_alpha14.md` for that evidence and the remaining campaign,
multiworld and clean-machine validation. The new recordings have not yet been
auditioned by the user in the game.

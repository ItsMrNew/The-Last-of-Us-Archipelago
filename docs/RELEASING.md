# Building and releasing

Use Windows and Python 3.12. Install `pip install -e .[research,bundle,test]`.
The native compiler is Zig 0.13.0 in `.deps/zig-windows-x86_64-0.13.0`.
MinHook v1.3.4, commit `c3fcafdc10146beb5919319d0683e44e3c30d537`, belongs
in `.deps/minhook`. Dependencies and game files must not be committed.

The game executable is required only to fingerprint and build the native bridge.
Run `python tools/build_native.py "PATH/TO/tlou-i.exe"`, followed by
`python tools/test_native.py`. New native hashes must pass targeted live acceptance
before being added to `VALIDATED_ENGINE_GATES`; never bypass that gate for a release.

Licensed ZapSplat WAVs are not part of the MIT source checkout. Maintainers must
supply the licensed files listed by `tlou_ap/data/airhorns/manifest.json` to make
an exact release build. The client has an original synthesized fallback for
source development; release self-tests require the five selected recordings.
The game-identification icon is not covered by the project's MIT licence.

## Packaging order

1. Update `tlou_ap/version.py`, `pyproject.toml`, APWorld metadata and release notes.
2. Run the Python suite: `python -m unittest discover -s tests`.
3. Build the native DLL and run its harness when native sources have changed.
4. Update `dist/gate-validation.json` from the accepted native-build evidence.
5. Run `python tools/build_standalone.py` (requires pinned PyInstaller 6.22.3).
6. Run `python tools/build_apworld.py` to embed that exact verified executable.
7. Run `python tools/build_client.py` for the optional source-based client bundle.
8. Run `python tools/verify_bundle.py ARCHIVE REPORT.json` on both client ZIPs.
9. Run `python tools/verify_world.py PATH/TO/OFFICIAL/AP/CHECKOUT`.
10. Run `python tools/smoke_ap_launcher.py --apworld dist/tlou_part1.apworld
    --output .research/UNIQUE-AUDIT-DIRECTORY` against installed Archipelago.
11. Run `python tools/release_source.py` for the GitHub source ZIP and release hashes.

For a single-download executable, run `python tools/build_single_exe.py` after
building the APWorld. It wraps that exact verified client payload, checks first
launch and cache reuse with Python removed from PATH, and writes
`dist/single-exe-validation.json`. The runtime and game bridge do not change.
Upload the resulting `.exe` and its SHA-256 file alongside the existing packages.
The APWorld already includes the same Python-independent client; it does not
download the executable from GitHub at launch time.

`tools/build_apworld.py --world-only --output PATH` creates a small generation-only
development APWorld. Do not ship that instead of the normal bundled APWorld.
Client ZIPs deliberately do not contain another APWorld, avoiding recursive bundles.

The smoke test uses a private Archipelago copy and LocalAppData directory. It
launches twice to check cache reuse and runs the extracted executable's self-test.
It must not attach to a game or connect to a real room.

## Publication

Upload `tlou_part1.apworld`, the standalone ZIP, optional source-client ZIP,
GitHub source ZIP and `SHA256SUMS.txt` as release assets. Use RELEASE_NOTES.md
as the description. Mark release candidates as prereleases until their outstanding
acceptance checks pass. Publishing/tagging is a separate step; these tools
never push a repository or create a GitHub release.

Exclude `.state`, `.research`, `.deps`, `.venv`, game saves, crash dumps and
credentials from source and release assets. Package manifests must contain no
run state. Preserve existing user profiles when installing updates.

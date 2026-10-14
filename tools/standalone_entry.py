"""Single-download entry point for the exact client bundled in the APWorld."""
import ctypes
from pathlib import Path
import subprocess
import sys

from tlou_ap import launcher_client
from tlou_ap.state_paths import migrate_legacy_state, state_directory


def main():
    try:
        bundle = Path(sys._MEIPASS) / 'launcher_bundle'
        launcher_client.resources = lambda: bundle
        executable = launcher_client.prepare_client()
        # A former portable install can be migrated before the cached client opens.
        portable = Path(sys.executable).resolve().parent
        if '--self-test' not in sys.argv:
            migrate_legacy_state(portable / '.state', state_directory(portable, frozen=True))
        with launcher_client.independent_dll_directory():
            child = subprocess.Popen([str(executable), *sys.argv[1:]], cwd=executable.parent,
                                     env=launcher_client.client_environment())
        if '--self-test' in sys.argv:
            return child.wait(timeout=60)
        return 0
    except Exception as exc:
        if '--self-test' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'The Last of Us Part I Client', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

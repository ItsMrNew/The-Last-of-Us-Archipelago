"""Stable standalone/APWorld profiles; legacy portable data is copied once."""
import os
from pathlib import Path
import tempfile


def state_directory(root, frozen=False):
    override = os.environ.get('TLOU_AP_STATE_DIR')
    if override:
        return Path(override).resolve()
    if frozen:
        local = os.environ.get('LOCALAPPDATA')
        if not local:
            raise RuntimeError('LOCALAPPDATA is unavailable; cannot locate managed runs.')
        return Path(local) / 'TLOUArchipelago' / '.state'
    return Path(root) / '.state'


def migrate_legacy_state(legacy, destination):
    """Never merge/overwrite another profile, and retain the original copy."""
    legacy, destination = Path(legacy).resolve(), Path(destination).resolve()
    if legacy == destination or destination.exists() or not legacy.is_dir():
        return False
    files = [p for p in legacy.rglob('*') if p.is_file()]
    if any(p.is_symlink() for p in legacy.rglob('*')):
        raise ValueError('Legacy state contains links; migration stopped.')
    before = {p.relative_to(legacy): p.read_bytes() for p in files}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='migrate-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'state'
        stage.mkdir()
        for name, data in before.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if before != {p.relative_to(legacy): p.read_bytes() for p in legacy.rglob('*') if p.is_file()}:
            raise RuntimeError('Legacy state changed during migration; close the other client and retry.')
        try:
            stage.rename(destination)
        except FileExistsError:
            return False
    return True

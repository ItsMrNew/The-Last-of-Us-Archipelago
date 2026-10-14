"""Verify every packaged byte and run the extracted client's isolated smoke test."""
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
archive_path, report_path = map(Path, sys.argv[1:3])
with ZipFile(archive_path) as archive:
    assert archive.testzip() is None
    assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts for n in archive.namelist())
    hashes = json.loads(archive.read('TLOU-Archipelago/SHA256SUMS.json'))
    assert set(archive.namelist()) == {'TLOU-Archipelago/' + n for n in hashes} | {'TLOU-Archipelago/SHA256SUMS.json'}
    assert not any('.state' in PurePosixPath(n).parts for n in hashes)
    for name, expected in hashes.items():
        payload = archive.read('TLOU-Archipelago/' + name)
        assert hashlib.sha256(payload).hexdigest() == expected, name
        if name.endswith('.py'): ast.parse(payload, filename=name)
    with tempfile.TemporaryDirectory(prefix='verify-bundle-', dir=ROOT / 'build') as folder:
        archive.extractall(folder)
        app = Path(folder) / 'TLOU-Archipelago'
        output = Path(folder) / 'smoke.json'
        executable = app / 'TLOU Archipelago.exe'
        if executable.exists():
            environment = {**os.environ, 'PYTHONHOME': '', 'PYTHONPATH': '',
                           'PATH': str(Path(os.environ['SystemRoot']) / 'System32')}
            command = [str(executable), '--self-test', str(output)]
        else:
            environment = os.environ.copy()
            script = "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from tlou_ap.selftest import run; run(Path(sys.argv[2]), Path(sys.argv[1]))"
            command = [sys.executable, '-I', '-c', script, str(app), str(output)]
        subprocess.run(command, cwd=folder, env=environment, check=True, timeout=45)
        report = json.loads(output.read_text())
        assert report['passed']
        assert report['horn_recordings_installed'] == 5
        report.update(file_checksums_verified=len(hashes), source_ast_parsed=True,
                      archive_sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest())
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))

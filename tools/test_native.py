"""Compile and run isolated tests against the actual native gate implementation."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
mh = ROOT / '.deps/minhook'
compiler = ROOT / '.deps/zig-windows-x86_64-0.13.0/zig.exe'
out = ROOT / 'build/native'
if not (out / 'anchors.h').exists():
    raise SystemExit('Run tools/build_native.py first to generate the verified anchor header')
command = [str(compiler), 'cc', '-target', 'x86_64-windows-gnu', '-O1', '-std=c11',
           '-I' + str(out), '-I' + str(mh / 'include'), str(ROOT / 'tests/native_gate.c'),
           *(str(mh / name) for name in ('src/buffer.c', 'src/hook.c', 'src/trampoline.c')),
           str(ROOT / 'native/hook_decoder.c'), '-o', str(out / 'test_native_gate.exe')]
subprocess.run(command, check=True, cwd=ROOT)
subprocess.run([str(out / 'test_native_gate.exe')], check=True, cwd=ROOT)

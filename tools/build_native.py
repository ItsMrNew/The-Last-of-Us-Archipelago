"""Build the x64 DLL with a local verified Zig compiler and MinHook checkout."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.analyze_native import Executable

PROFILE = json.loads((ROOT / 'tlou_ap/native/build_1130.json').read_text())
game = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r'D:\Games\The Last of Us - Part I\tlou-i.exe')
if hashlib.sha256(game.read_bytes()).hexdigest() != PROFILE['sha256']:
    raise SystemExit('Unsupported executable; do not generate a profile automatically')
exe = Executable(game)
out = ROOT / 'build/native'
out.mkdir(parents=True, exist_ok=True)
anchors = [{'rva': rva, 'bytes': exe.get_data(rva, 24).hex()}
           for rva in (0x18178c8, 0x1817898, 0x3fe1f0, 0x17e9f5c, 0x18c52af, 0x199bab4, 0x19c34f0, 0x19c0d64, 0x3edb7c, 0x10e3db8, 0x2376db0, 0x233b3c4, 0x20050ac, 0x431ab0, 0x5ebea0, 0x62aa10, 0x62b6d0, 0x626e80, 0x62b680, 0x13664ec, 0x1366884, 0x62b1a0, 0x5ea8f0, 0x19e17e8, 0x1a95d44,
                       0x17f0e68, 0x1dbde04, 0x1dbe3ac, 0x12bc06c, 0x1db85d8, 0x19e02e4,
                       0x17f0df4, 0x12001fc, 0x1dbec54, 0x15b13d8, 0x15b148c, 0x1f0a5fc, 0x3f05c0,
                       0x235c880, 0x235c99f, 0x235c9e8, 0x235cb25)]
source = b''.join((ROOT / 'native' / name).read_bytes() for name in ('bridge.h', 'bridge.c', 'test_commands.h', 'test_collectibles.h', 'hook_decoder.c'))
build_id = int.from_bytes(hashlib.sha256(source).digest()[:8], 'little')
header = '#include <stdint.h>\n#define AP_BUILD_ID UINT64_C(0x%016x)\n' % build_id
header += 'typedef struct { uint32_t rva; uint32_t size; unsigned char data[32]; } APAnchor;\n'
header += 'static const APAnchor ap_anchors[] = {\n'
for a in anchors:
    data = bytes.fromhex(a['bytes'])
    header += '{0x%x, %d, {%s}},\n' % (a['rva'], len(data), ','.join(str(b) for b in data))
header += '};\n'
(out / 'anchors.h').write_text(header)
compiler = ROOT / '.deps/zig-windows-x86_64-0.13.0/zig.exe'
mh = ROOT / '.deps/minhook'
command = [str(compiler), 'cc', '-target', 'x86_64-windows-gnu', '-O2', '-shared', '-std=c11',
           '-I' + str(ROOT / 'native'), '-I' + str(out), '-I' + str(mh / 'include'),
           str(ROOT / 'native/bridge.c'), *(str(mh / name) for name in
           ('src/buffer.c', 'src/hook.c', 'src/trampoline.c')),
           str(ROOT / 'native/hook_decoder.c'), '-o', str(out / 'bridge.dll')]
subprocess.run(command, check=True, cwd=ROOT)
destination = ROOT / 'dist/native'
destination.mkdir(parents=True, exist_ok=True)
name = f'tlou_ap_bridge_{build_id:016x}.dll'
shutil.copyfile(out / 'bridge.dll', destination / name)
manifest = {'schema': 1, 'build_id': build_id, 'dll': name, 'game_sha256': PROFILE['sha256'],
            'dll_sha256': hashlib.sha256((destination / name).read_bytes()).hexdigest(), 'anchors': anchors,
            'mode': 'experimental_native', 'gate_mode': 2, 'abi_version': 5}
binary = pefile.PE(str(destination / name))
manifest['restart_rva'] = next(entry.address for entry in binary.DIRECTORY_ENTRY_EXPORT.symbols
                               if entry.name == b'APStart')
(destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
shutil.copyfile(mh / 'LICENSE.txt', destination / 'MinHook-LICENSE.txt')
print(destination / name)

"""Resolve script-native registration candidates from a local executable.

Reads static metadata only. Does not execute or hook a game function.
Example: python tools/find_script_native.py GAME_EXE task-subnode-play
"""
import argparse
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.analyze_native import Executable
from tlou_ap.native.tasks import sid


def resolve(executable, name):
    header = struct.unpack_from('<I', executable.data, 0x3c)[0] + 24
    image_base = struct.unpack_from('<Q', executable.data, header + 24)[0]
    result = []
    for match in re.finditer(re.escape(struct.pack('<Q', sid(name))), executable.data):
        try:
            record = executable.get_rva_from_offset(match.start())
            # Registration: descriptor pointer, name SID, runtime hash-chain pointer.
            descriptor = struct.unpack('<Q', executable.get_data(record - 8, 8))[0] - image_base
            vtable, callback = struct.unpack('<QQ', executable.get_data(descriptor, 16))
            callback -= image_base
            if not any(section.Characteristics & 0x20000000
                       and section.VirtualAddress <= callback < section.VirtualAddress + section.size
                       for section in executable.sections):
                continue
            executable.get_data(vtable - image_base, 8)
            result.append({'name': name, 'sid': f'{sid(name):016x}',
                           'registration_rva': hex(record - 8), 'descriptor_rva': hex(descriptor),
                           'callback_rva': hex(callback)})
        except (ValueError, struct.error):
            continue
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('names', nargs='+')
    args = parser.parse_args()
    executable = Executable(args.executable)
    print(json.dumps({name: resolve(executable, name) for name in args.names}, indent=2))


if __name__ == '__main__':
    main()

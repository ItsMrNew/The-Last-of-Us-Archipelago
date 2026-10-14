"""Static executable research: list function boundaries referencing named strings.

Requires capstone in the development environment. Read-only.
"""
import argparse
import bisect
from pathlib import Path
import re
import struct
from dataclasses import dataclass
from capstone import Cs, CS_ARCH_X86, CS_MODE_64


class Executable:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        self.pe = self
        header = struct.unpack_from('<I', self.data, 0x3c)[0]
        count = struct.unpack_from('<H', self.data, header + 6)[0]
        optional = header + 24
        optional_size = struct.unpack_from('<H', self.data, header + 20)[0]
        self.sections = []
        for i in range(count):
            offset = optional + optional_size + i * 40
            size, rva, raw_size, raw = struct.unpack_from('<4I', self.data, offset + 8)
            flags = struct.unpack_from('<I', self.data, offset + 36)[0]
            self.sections.append(Section(rva, raw_size, raw, flags, self.data))
        exception_rva, exception_size = struct.unpack_from('<II', self.data, optional + 112 + 24)
        exception = self.get_data(exception_rva, exception_size)
        self.functions = [(start, end) for start, end, _ in struct.iter_unpack('<III', exception)]
        self.starts = [start for start, _ in self.functions]
        self.decoder = Cs(CS_ARCH_X86, CS_MODE_64)

    def get_rva_from_offset(self, offset):
        for section in self.sections:
            if section.raw <= offset < section.raw + section.size:
                return section.VirtualAddress + offset - section.raw
        raise ValueError('Offset has no section')

    def get_data(self, rva, size):
        for section in self.sections:
            if section.VirtualAddress <= rva < section.VirtualAddress + section.size:
                offset = section.raw + rva - section.VirtualAddress
                return self.data[offset:offset + size]
        raise ValueError('RVA has no section')

    def function(self, rva):
        index = bisect.bisect_right(self.starts, rva) - 1
        if index >= 0:
            start, end = self.functions[index]
            if start <= rva < end:
                return start, end
        return rva, rva + 128

    def references(self, text):
        targets = set()
        for match in re.finditer(re.escape(text.encode() + b"\0"), self.data):
            targets.add(self.pe.get_rva_from_offset(match.start()))
        result = []
        for section in self.pe.sections:
            if not section.Characteristics & 0x20000000:
                continue
            data = section.get_data()
            # LEA r64,[RIP+disp32]; matches are candidates, disassemble to verify.
            for match in re.finditer(rb'[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]', data):
                offset = match.start()
                rva = section.VirtualAddress + offset
                target = rva + 7 + struct.unpack_from('<i', data, offset + 3)[0]
                if target in targets:
                    result.append((rva, self.function(rva)))
        return result

    def disassemble(self, rva, size):
        for instruction in self.decoder.disasm(self.pe.get_data(rva, size), rva):
            print(f"{instruction.address:08x}  {instruction.mnemonic:9s} {instruction.op_str}")


@dataclass
class Section:
    VirtualAddress: int
    size: int
    raw: int
    Characteristics: int
    data: bytes

    def get_data(self):
        return self.data[self.raw:self.raw + self.size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('--text')
    parser.add_argument('--rva', type=lambda value: int(value, 0))
    parser.add_argument('--size', type=lambda value: int(value, 0), default=256)
    args = parser.parse_args()
    executable = Executable(args.executable)
    if args.text:
        for rva, (start, end) in executable.references(args.text):
            print(f"Reference {rva:#x} in function {start:#x}..{end:#x}")
    if args.rva is not None:
        executable.disassemble(args.rva, args.size)


if __name__ == '__main__':
    main()

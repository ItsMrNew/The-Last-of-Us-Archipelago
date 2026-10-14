"""Read local PSARC archives. Does not write to the game's installation.

Oodle decompression uses the library already supplied with the user's game.
No library or extracted game data is included in the mod distribution.
"""
import argparse
import ctypes
import hashlib
from dataclasses import dataclass
from pathlib import Path
import struct
import zlib


@dataclass(frozen=True)
class Entry:
    digest: bytes
    block: int
    size: int
    offset: int


class Archive:
    def __init__(self, path: Path, oodle: Path | None = None):
        self.path = path
        with path.open("rb") as stream:
            header = stream.read(32)
            magic, version, self.codec, toc_size, entry_size, count, self.block_size, flags = struct.unpack(
                ">4sI4s5I", header)
            if magic != b"PSAR" or entry_size != 30 or toc_size > 64 * 1024 * 1024:
                raise ValueError("Unsupported PSARC header")
            if count * entry_size + 32 > toc_size or self.block_size != 65536:
                raise ValueError("Unsupported PSARC table")
            table = stream.read(toc_size - 32)
            if len(table) != toc_size - 32:
                raise ValueError("Truncated PSARC table")
        self.entries = []
        for i in range(count):
            row = table[i * 30:(i + 1) * 30]
            self.entries.append(Entry(row[:16], int.from_bytes(row[16:20], "big"),
                                      int.from_bytes(row[20:25], "big"), int.from_bytes(row[25:30], "big")))
        lengths = table[count * 30:]
        self.blocks = [int.from_bytes(lengths[i:i + 2], "big") or self.block_size
                       for i in range(0, len(lengths), 2)]
        self.oodle = None
        if self.codec == b"oodl":
            if oodle is None:
                raise ValueError("Supply the game's oo2core_9_win64.dll path")
            library = ctypes.CDLL(str(oodle.resolve()))
            self.oodle = library.OodleLZ_Decompress
            self.oodle.argtypes = [ctypes.c_void_p, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_ssize_t,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
            self.oodle.restype = ctypes.c_ssize_t
        elif self.codec != b"zlib":
            raise ValueError(f"Unsupported compression: {self.codec!r}")
        manifest = self.read_entry(0).decode("utf-8")
        names = manifest.rstrip("\0").split("\0") if "\0" in manifest else manifest.splitlines()
        if len(names) != len(self.entries) - 1:
            raise ValueError(f"Name count {len(names)} does not match entry count {len(self.entries)}")
        by_digest = {entry.digest: i for i, entry in enumerate(self.entries)}
        self.names = {name: by_digest[hashlib.md5(name.encode()).digest()] for name in names}

    def read_entry(self, index: int) -> bytes:
        entry = self.entries[index]
        if entry.size > 64 * 1024 * 1024:
            raise ValueError("Research reader limits individual entries to 64 MiB")
        output = bytearray()
        with self.path.open("rb") as stream:
            stream.seek(entry.offset)
            block = entry.block
            while len(output) < entry.size:
                expected = min(self.block_size, entry.size - len(output))
                size = self.blocks[block]
                data = stream.read(size)
                if len(data) != size:
                    raise ValueError("Truncated archive block")
                if size == expected:
                    result = data
                elif self.oodle:
                    destination = ctypes.create_string_buffer(expected)
                    count = self.oodle(data, len(data), destination, expected, 1, 0, 0,
                                       None, 0, None, None, None, 0, 3)
                    if count != expected:
                        raise ValueError("Oodle block decompression failed")
                    result = destination.raw
                else:
                    result = zlib.decompress(data)
                if len(result) != expected:
                    raise ValueError("Unexpected decompressed block size")
                output.extend(result)
                block += 1
        return bytes(output)

    def read(self, name: str) -> bytes:
        return self.read_entry(self.names[name])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--oodle", type=Path)
    parser.add_argument("--filter", default="")
    parser.add_argument("--entry")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    archive = Archive(args.archive, args.oodle)
    if args.entry:
        if args.output is None:
            parser.error("--entry requires --output (use the ignored .research directory)")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(archive.read(args.entry))
        print(f"Read {args.entry} into {args.output}")
    else:
        for name, index in archive.names.items():
            if args.filter.lower() in name.lower():
                print(f"{archive.entries[index].size:10d} {name}")


if __name__ == "__main__":
    main()

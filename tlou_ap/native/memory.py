"""Minimal Windows process reader. No process-write or injection API is exposed."""
import ctypes as c
from ctypes import wintypes as w
import os
import struct


class Module(c.Structure):
    _fields_ = [("size", w.DWORD), ("id", w.DWORD), ("pid", w.DWORD),
                ("global_use", w.DWORD), ("process_use", w.DWORD),
                ("base", c.c_void_p), ("length", w.DWORD), ("module", w.HMODULE),
                ("name", w.WCHAR * 256), ("path", w.WCHAR * 260)]


class ProcessReader:
    def __init__(self, pid):
        if os.name != 'nt':
            raise OSError('Live inspection requires Windows')
        self.kernel = k = c.WinDLL('kernel32', use_last_error=True)
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        k.ReadProcessMemory.restype = w.BOOL
        k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        k.Module32FirstW.argtypes = [w.HANDLE, c.POINTER(Module)]
        k.Module32NextW.argtypes = [w.HANDLE, c.POINTER(Module)]
        snapshot = k.CreateToolhelp32Snapshot(0x18, pid)
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        self.modules = []
        try:
            entry = Module()
            entry.size = c.sizeof(entry)
            ok = k.Module32FirstW(snapshot, c.byref(entry))
            while ok:
                self.modules.append({'name': entry.name, 'path': entry.path,
                                     'base': entry.base, 'size': entry.length})
                ok = k.Module32NextW(snapshot, c.byref(entry))
        finally:
            k.CloseHandle(snapshot)
        self.game = next((m for m in self.modules if m['name'].lower() in ('tlou-i.exe', 'tlou-i-l.exe')), None)
        if self.game is None:
            raise ValueError('Selected process is not The Last of Us Part I')
        self.handle = k.OpenProcess(0x1010, False, pid)
        if not self.handle:
            raise c.WinError(c.get_last_error())

    def read(self, address, size):
        if not 0 < size <= 64 * 1024 * 1024:
            raise ValueError('Read size must be 1 byte to 64 MiB')
        data = c.create_string_buffer(size)
        length = c.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, address, data, size, c.byref(length)):
            raise c.WinError(c.get_last_error())
        if length.value != size:
            raise OSError('Incomplete process memory read')
        return data.raw

    def qword(self, address):
        return struct.unpack('<Q', self.read(address, 8))[0]

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

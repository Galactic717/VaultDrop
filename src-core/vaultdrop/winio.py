"""Windows-specific I/O: long paths, uncached reads, error classification."""

import ctypes
import errno
import mmap
import os
from contextlib import contextmanager
from ctypes import wintypes

import xxhash

CHUNK = 1 << 20

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
_k32.ReadFile.restype = wintypes.BOOL
_k32.ReadFile.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)
_k32.GetVolumeInformationW.restype = wintypes.BOOL
_k32.GetVolumeInformationW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                       ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD)

_GENERIC_READ = 0x80000000
_SHARE_READ_WRITE = 0x1 | 0x2
_OPEN_EXISTING = 3
_NO_BUFFERING = 0x20000000
_SEQUENTIAL_SCAN = 0x08000000
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_ES_CONTINUOUS, _ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
_k32.SetThreadExecutionState.restype = wintypes.DWORD
_k32.SetThreadExecutionState.argtypes = (wintypes.DWORD,)

# Page-aligned buffer (4096 bytes): FILE_FLAG_NO_BUFFERING requires an aligned address and read size.
# One buffer per process: the core is single-threaded.
_buf = mmap.mmap(-1, CHUNK)
_buf_addr = ctypes.addressof(ctypes.c_char.from_buffer(_buf))
_buf_view = memoryview(_buf)

# WinError codes that mean the drive was unplugged: NOT_READY, DEV_NOT_EXIST, NO_SUCH_DEVICE,
# DEVICE_HARDWARE_ERROR, FILE_INVALID (volume vanished under an open file), IO_DEVICE, DEVICE_NOT_CONNECTED.
YANKED_WINERRORS = {21, 55, 433, 483, 1006, 1117, 1167}
DISK_FULL_WINERRORS = {39, 112}


def lp(path: str) -> str:
    """Absolute path with the \\\\?\\ prefix: lifts the 260-character limit regardless of Windows settings."""
    if path.startswith("\\\\?\\"):
        return path
    return "\\\\?\\" + os.path.abspath(path)


def read_unbuffered(path: str, consume) -> None:
    """Reads a file from the disk itself (FILE_FLAG_NO_BUFFERING), not the Windows cache; passes chunks to consume."""
    handle = _k32.CreateFileW(lp(path), _GENERIC_READ, _SHARE_READ_WRITE, None, _OPEN_EXISTING,
                              _NO_BUFFERING | _SEQUENTIAL_SCAN, None)
    if handle == _INVALID_HANDLE:
        raise _last_error(path)
    got = wintypes.DWORD()
    try:
        while True:
            if not _k32.ReadFile(handle, _buf_addr, CHUNK, ctypes.byref(got), None):
                raise _last_error(path)
            consume(_buf_view[:got.value])
            if got.value < CHUNK:  # short read = end of file; the next offset would no longer be aligned
                return
    finally:
        _k32.CloseHandle(handle)


def hash_unbuffered(path: str) -> str:
    """xxh64 of a file read from disk bypassing the cache."""
    h = xxhash.xxh64()
    read_unbuffered(path, h.update)
    return h.hexdigest()


def volume_fs(path: str) -> str:
    """File system name of the volume: NTFS, exFAT, FAT32 or unknown."""
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    name = ctypes.create_unicode_buffer(64)
    if not _k32.GetVolumeInformationW(root, None, 0, None, None, None, name, 64):
        return "unknown"
    return name.value


@contextmanager
def keep_awake():
    """Keeps Windows awake during copy or verify (the display may still turn off)."""
    _k32.SetThreadExecutionState(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        _k32.SetThreadExecutionState(_ES_CONTINUOUS)


def classify(exc: OSError, dest_root: str) -> str:
    """Reason for a write failure in dest: disk_full, yanked or io_error."""
    code = getattr(exc, "winerror", None)
    if code in DISK_FULL_WINERRORS or exc.errno == errno.ENOSPC:
        return "disk_full"
    if code in YANKED_WINERRORS or not os.path.exists(lp(dest_root)):
        return "yanked"
    return "io_error"


def _last_error(path: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(None, ctypes.FormatError(code).strip(), path, code)

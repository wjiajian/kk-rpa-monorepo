import errno
import os
from types import SimpleNamespace

import pytest

from rpa_core import locks


def test_windows_byte_lock_is_exclusive_and_released(tmp_path, monkeypatch):
    held = set()
    calls = []

    def locking(descriptor, mode, size):
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0 and size == 1
        identity = os.fstat(descriptor).st_ino
        calls.append(mode)
        if mode == "lock":
            if identity in held:
                raise OSError(errno.EACCES, "already locked")
            held.add(identity)
        else:
            held.remove(identity)

    monkeypatch.setattr(locks, "_fcntl", None)
    monkeypatch.setattr(locks, "_msvcrt", SimpleNamespace(locking=locking, LK_NBLCK="lock", LK_UNLCK="unlock"))
    first = locks.RunDirectoryLock(tmp_path / "profile.lock")
    second = locks.RunDirectoryLock(first.path)
    first.acquire()
    with pytest.raises(locks.RunAlreadyActiveError):
        second.acquire()
    first.release()
    second.acquire()
    second.release()
    assert not held and calls == ["lock", "lock", "unlock", "lock", "unlock"]


def test_missing_platform_lock_still_fails_closed(monkeypatch):
    monkeypatch.setattr(locks, "_fcntl", None)
    monkeypatch.setattr(locks, "_msvcrt", None)
    with pytest.raises(locks.RunLockUnsupportedError):
        locks.RunDirectoryLock.ensure_supported()

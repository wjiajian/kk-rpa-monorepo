"""Process locks used by browser profile and port ownership."""

import errno
import os
import stat
from pathlib import Path

try:
    import fcntl as _fcntl
except ImportError:
    _fcntl = None

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None


class RunLockError(RuntimeError):
    error_code = "run_lock_error"


class RunLockUnsupportedError(RunLockError):
    error_code = "run_lock_unsupported"


class RunAlreadyActiveError(RunLockError):
    error_code = "run_already_active"


class RunDirectoryLock:
    """Hold a process-scoped exclusive lock for one run directory."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._descriptor: int | None = None

    @staticmethod
    def ensure_supported() -> None:
        if _fcntl is None and _msvcrt is None:
            raise RunLockUnsupportedError(
                "OS file locking is unavailable; refusing to run without exclusivity"
            )

    def acquire(self) -> None:
        self.ensure_supported()
        if self._descriptor is not None:
            raise RunLockError("run lock is already held by this object")
        if self.path.is_symlink():
            raise RunLockError("run lock must not be a symbolic link")

        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor: int | None = None
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as error:
            raise RunLockError(f"cannot safely open run lock: {self.path}") from error
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise RunLockError("run lock target must be one regular file")
            try:
                linked = os.lstat(self.path)
            except OSError as error:
                raise RunLockError("run lock path changed while opening") from error
            if stat.S_ISLNK(linked.st_mode):
                raise RunLockError("run lock must not be a symbolic link")
            if (opened.st_dev, opened.st_ino) != (linked.st_dev, linked.st_ino):
                raise RunLockError("run lock path changed while opening")
            try:
                if _fcntl is not None:
                    _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                else:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    _msvcrt.locking(descriptor, _msvcrt.LK_NBLCK, 1)
            except BlockingIOError as error:
                raise RunAlreadyActiveError(
                    f"run is already active: {self.path.parent.name}"
                ) from error
            except OSError as error:
                if error.errno in {errno.EACCES, errno.EAGAIN}:
                    raise RunAlreadyActiveError(
                        f"run is already active: {self.path.parent.name}"
                    ) from error
                raise RunLockError(f"cannot acquire run lock: {self.path}") from error
            locked = os.fstat(descriptor)
            if not stat.S_ISREG(locked.st_mode) or locked.st_nlink != 1:
                raise RunLockError("run lock target changed while acquiring")
            self._descriptor = descriptor
            descriptor = None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def release(self) -> None:
        descriptor = self._descriptor
        if descriptor is None:
            return
        self._descriptor = None
        try:
            if _fcntl is not None:
                _fcntl.flock(descriptor, _fcntl.LOCK_UN)
            else:
                os.lseek(descriptor, 0, os.SEEK_SET)
                _msvcrt.locking(descriptor, _msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)

    def __enter__(self) -> "RunDirectoryLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()

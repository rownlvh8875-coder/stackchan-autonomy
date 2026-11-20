"""Publish only complete personal profiles into a validated, bound private directory."""

import contextlib
import os
import secrets
import stat
from pathlib import Path

from pc_mic_profile import EnrollmentError, validate_profile

ROOT = Path(__file__).resolve().parents[3]


def output_target(path, root=ROOT):
    path = Path(path).absolute()
    private = Path(root).resolve() / ".local"
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            metadata = part.lstat()
            if part.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400:
                raise EnrollmentError("private_output_required")
    if not path.resolve().is_relative_to(private) or path.suffix != ".swk1" or path.exists():
        raise EnrollmentError("new_private_output_required")
    return path


@contextlib.contextmanager
def _windows_directories(root, parts):
    # Hold each validated parent without WRITE/DELETE sharing. This prevents its
    # replacement/reparse while path-based Win32 file/link calls run below it.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    info = kernel.GetFileInformationByHandleEx
    info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    info.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL

    class Attributes(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    handles = []
    try:
        current = root
        for index, part in enumerate([None, *parts]):
            if index:
                current = current / part
                current.mkdir(mode=0o700, exist_ok=True)
            handle = create(str(current), 0x80, 1, None, 3, 0x02000000 | 0x00200000, None)
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            attributes = Attributes()
            if not info(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
                raise ctypes.WinError(ctypes.get_last_error())
            if attributes.attributes & 0x400 or not attributes.attributes & 0x10:
                raise EnrollmentError("private_output_required")
        yield _Directory(current)
    finally:
        for handle in reversed(handles):
            close(handle)


class _Directory:
    def __init__(self, path, descriptor=None):
        self.path, self.fd = path, descriptor

    def open_new(self, name):
        return os.open(
            self.path / name if self.fd is None else name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
            **({} if self.fd is None else {"dir_fd": self.fd}),
        )

    def link_new(self, source, target):
        if self.fd is None:
            os.link(self.path / source, self.path / target)
        else:
            os.link(source, target, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)

    def unlink(self, name):
        if self.fd is None:
            (self.path / name).unlink()
        else:
            os.unlink(name, dir_fd=self.fd)

    def identity(self, name):
        metadata = os.stat(
            self.path / name if self.fd is None else name,
            follow_symlinks=False,
            **({} if self.fd is None else {"dir_fd": self.fd}),
        )
        return metadata.st_dev, metadata.st_ino

    def sync(self):
        if self.fd is not None:
            os.fsync(self.fd)


@contextlib.contextmanager
def _private_directory(path, root):
    root = Path(root).resolve()
    parts = path.parent.relative_to(root).parts
    if os.name == "nt":
        with _windows_directories(root, parts) as folder:
            yield folder
        return
    descriptors = []
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            descriptor = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            descriptors.append(descriptor)
        yield _Directory(path.parent, descriptor)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def save_private_profile(path, profile, root=ROOT):
    validate_profile(profile)
    path = output_target(path, root)
    try:
        with _private_directory(path, root) as folder:
            temporary = "." + path.name + "." + secrets.token_hex(16) + ".tmp"
            created, identity = False, None
            try:
                descriptor = folder.open_new(temporary)
                created = True
                with os.fdopen(descriptor, "wb") as target:
                    metadata = os.fstat(target.fileno())
                    identity = metadata.st_dev, metadata.st_ino
                    if target.write(profile) != len(profile):
                        raise OSError("short_write")
                    target.flush()
                    os.fsync(target.fileno())
                # Hard-link publication is atomic, same-directory and never replaces
                # an existing file. The final name is invisible until sync completes.
                folder.link_new(temporary, path.name)
                folder.unlink(temporary)
                created = False
                folder.sync()
            except BaseException:
                try:
                    if identity is not None:
                        try:
                            own_final = folder.identity(path.name) == identity
                        except FileNotFoundError:
                            own_final = False
                        if own_final:
                            folder.unlink(path.name)
                    if created:
                        folder.unlink(temporary)
                except OSError:
                    raise EnrollmentError(
                        "private_profile_cleanup_failed_do_not_use_file"
                    ) from None
                raise
    except OSError as exc:
        raise EnrollmentError("private_profile_write_failed") from exc

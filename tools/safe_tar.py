#!/usr/bin/env python3
"""Validated tar extraction for the SDK tooling.

`tarfile.extractall` trusts the archive: before Python 3.14 its default filter lets a member write outside the destination (`../x`, absolute
names), plant a symlink that later members write through, create device nodes when run as root, and restore setuid bits. The SDK tarball is
the artifact a consumer installs, so the tools that unpack one (the candidate builder and its distribution probe) validate EVERY member
first and then extract with the strict `data` filter. The validation is deliberately narrower than the filter: it admits only regular files and
directories, so an archive with any link is refused instead of being silently rewritten.
"""
from __future__ import annotations
import pathlib, posixpath, tarfile

MAX_MEMBERS = 100_000
MAX_TOTAL_BYTES = 4 << 30  # 4 GiB of file content


class UnsafeArchive(RuntimeError):
    """The archive contains something the SDK tooling never produces and never accepts."""


def validate_members(archive: tarfile.TarFile, max_members: int = MAX_MEMBERS, max_bytes: int = MAX_TOTAL_BYTES) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    if len(members) > max_members:
        raise UnsafeArchive(f'too many members: {len(members)} > {max_members}')
    seen: set[str] = set()
    total = 0
    for member in members:
        name = member.name
        if not name or '\x00' in name or '\\' in name:
            raise UnsafeArchive(f'unsafe member name: {name!r}')
        if name.startswith('/') or (len(name) > 1 and name[1] == ':'):
            raise UnsafeArchive(f'absolute member name: {name!r}')
        normal = posixpath.normpath(name)
        if normal == '..' or normal.startswith('../') or '/../' in f'/{name}/':
            raise UnsafeArchive(f'member escapes the destination: {name!r}')
        if not (member.isreg() or member.isdir()):
            kind = 'symlink' if member.issym() else 'hardlink' if member.islnk() else 'device/fifo/other'
            raise UnsafeArchive(f'{kind} member is not admitted: {name!r}')
        if normal in seen:
            raise UnsafeArchive(f'duplicate member: {name!r}')
        seen.add(normal)
        if member.isreg():
            total += member.size
            if member.size < 0 or total > max_bytes:
                raise UnsafeArchive(f'archive content exceeds {max_bytes} bytes')
    return members


def safe_extract(archive_path: pathlib.Path, destination: pathlib.Path, **limits) -> list[str]:
    """Extract `archive_path` into `destination` (created if needed). Returns the extracted member names."""
    destination = pathlib.Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive_path) as archive:
        members = validate_members(archive, **limits)
        for member in members:  # defence in depth: the resolved path of every member must stay inside the destination
            if not (root / member.name).resolve().is_relative_to(root):
                raise UnsafeArchive(f'member resolves outside the destination: {member.name!r}')
        try:
            if hasattr(tarfile, 'data_filter'):
                archive.extractall(root, members=members, filter='data')
            else:  # older Python: the validation above already restricted the archive to regular files and directories
                archive.extractall(root, members=members)
        except tarfile.FilterError as error:   # e.g. a symlink that already exists in the destination redirects a member
            raise UnsafeArchive(str(error)) from error
    return [member.name for member in members]

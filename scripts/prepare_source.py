#!/usr/bin/env python3
"""Obtain and byte-verify the pinned original Supermodel source; no media download."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REVISION = '24d2ffcfc7f14229337f05f4920fe26b56633d9d'
ARCHIVE_SHA256 = '027c544e0eb223831c3a702fe326f7ac7c9b120c036133f05b52ccf3ca0feb95'
ARCHIVE_URL = f'https://codeload.github.com/trzy/Supermodel/tar.gz/{REVISION}'
ARCHIVE = ROOT / 'build/downloads' / f'supermodel-{REVISION}.tar.gz'
SOURCE = ROOT / 'build/upstream/supermodel'
REPORT = ROOT / 'build/source/source-acceptance.json'


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def prepare_archive() -> Path:
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        with tempfile.TemporaryDirectory(prefix='source-download-', dir=ARCHIVE.parent) as work:
            temporary = Path(work) / 'archive.tar.gz'
            # System curl uses the system certificate store; TLS verification remains enabled.
            subprocess.run(['/usr/bin/curl', '--fail', '--location', '--silent', '--show-error',
                            '--retry', '2', '--proto', '=https', '--tlsv1.2', '--max-time', '120',
                            '--output', str(temporary), ARCHIVE_URL], check=True)
            if sha(temporary) != ARCHIVE_SHA256:
                raise RuntimeError('Downloaded source archive SHA256 differs from the pinned identity')
            temporary.replace(ARCHIVE)
    if ARCHIVE.is_symlink() or sha(ARCHIVE) != ARCHIVE_SHA256:
        raise RuntimeError('Cached source archive SHA256 differs from the pinned identity')
    return ARCHIVE


def archive_inventory() -> dict:
    prepare_archive()
    prefix = f'Supermodel-{REVISION}/'
    inventory = {}
    with tarfile.open(ARCHIVE, 'r:gz') as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile() or not member.name.startswith(prefix):
                raise RuntimeError('Unexpected archive member: ' + member.name)
            relative = Path(member.name[len(prefix):])
            if relative.is_absolute() or '..' in relative.parts or not relative.parts:
                raise RuntimeError('Unsafe archive member: ' + member.name)
            name = relative.as_posix()
            if name in inventory:
                raise RuntimeError('Duplicate archive member: ' + name)
            with archive.extractfile(member) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            inventory[name] = {'bytes': member.size, 'sha256': digest,
                               'executable': bool(member.mode & 0o111)}
    if not inventory:
        raise RuntimeError('Pinned source archive has no files')
    return inventory


def verify_tree(directory: Path, inventory: dict) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError('Source directory is absent or a symbolic link')
    actual = set()
    for path in directory.rglob('*'):
        relative = path.relative_to(directory)
        if relative.parts[0] == '.git':
            continue
        if path.is_symlink():
            raise RuntimeError('Unexpected source link: ' + relative.as_posix())
        if path.is_file():
            actual.add(relative.as_posix())
    if actual != set(inventory):
        raise RuntimeError('Source inventory changed: ' + json.dumps({
            'missing': sorted(set(inventory) - actual), 'unexpected': sorted(actual - set(inventory))}))
    for name, expected in inventory.items():
        path = directory / name
        if path.stat().st_size != expected['bytes'] or sha(path) != expected['sha256']:
            raise RuntimeError('Original source differs from pinned archive: ' + name)
        if bool(path.stat().st_mode & 0o111) != expected['executable']:
            raise RuntimeError('Original source executable mode differs: ' + name)


def verify_source(*, create: bool = True) -> dict:
    """Verify an existing clone or extracted tree against the same pinned archive."""
    inventory = archive_inventory()
    if not SOURCE.exists():
        if not create:
            raise RuntimeError('Source tree is absent; run scripts/prepare_source.py first')
        SOURCE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='source-extract-', dir=SOURCE.parent) as work:
            with tarfile.open(ARCHIVE, 'r:gz') as archive:
                archive.extractall(work, filter='data')
            extracted = Path(work) / f'Supermodel-{REVISION}'
            verify_tree(extracted, inventory)
            extracted.rename(SOURCE)
    verify_tree(SOURCE, inventory)
    report = {'passed': True, 'upstream': 'https://github.com/trzy/Supermodel',
              'revision': REVISION, 'archiveSHA256': ARCHIVE_SHA256, 'files': inventory,
              'fileCount': len(inventory), 'scriptSHA256': sha(Path(__file__)),
              'scope': 'Every original archive file, executable flag and source-tree inventory; Git metadata is excluded. No derived build or gameplay claim.'}
    write_json(REPORT, report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    report = verify_source(create=not args.verify_only)
    print(json.dumps({'verified': True, 'files': report['fileCount'],
                      'revision': REVISION, 'archiveSHA256': ARCHIVE_SHA256}))

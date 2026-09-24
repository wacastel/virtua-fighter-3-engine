#!/usr/bin/env python3
"""Stage and audit an explicit ROM-free source inventory. Never publish or run Git."""
from __future__ import annotations
import argparse
import ast
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from prepare_source import ROOT, REVISION, ARCHIVE_SHA256, sha, write_json

REVIEW = ROOT / 'build/publication-review'
PAYLOAD = REVIEW / 'engine-source'
# Review additions here explicitly. This list never discovers and silently admits new source.
REVIEWED_FILES = '''
.gitignore
COPYING
Configuration/Games.xml
Configuration/invincibility-ppc.json
Configuration/media.json
Configuration/replays/arcade.json
Configuration/replays/attract.json
Configuration/replays/challenger.json
Configuration/replays/fighter-akira.json
Configuration/replays/fighter-aoi.json
Configuration/replays/fighter-jacky.json
Configuration/replays/fighter-jeffry.json
Configuration/replays/fighter-kage.json
Configuration/replays/fighter-lau.json
Configuration/replays/fighter-lion.json
Configuration/replays/fighter-pai.json
Configuration/replays/fighter-sarah.json
Configuration/replays/fighter-shun.json
Configuration/replays/fighter-taka.json
Configuration/replays/fighter-wolf.json
Configuration/replays/input-diagnostics.json
Configuration/replays/invincibility-arcade.json
Configuration/replays/invincibility-attract.json
Configuration/replays/invincibility-p2.json
Configuration/replays/invincibility-ringout.json
Configuration/replays/invincibility-timeout.json
Configuration/replays/invincibility-versus.json
Configuration/replays/late-start.json
Configuration/replays/versus.json
Documentation/architecture.md
Documentation/audio-lifecycle-acceptance.json
Documentation/bridge-acceptance.json
Documentation/controller-acceptance.json
Documentation/fighter-coverage.json
Documentation/gui-controls-acceptance.json
Documentation/host-acceptance.json
Documentation/host-invincibility-acceptance.json
Documentation/input-acceptance.json
Documentation/integration-acceptance.json
Documentation/invincibility-acceptance.json
Documentation/invincibility-fixture-acceptance.json
Documentation/invincibility-source-acceptance.json
Documentation/link-guard-acceptance.json
Documentation/live-acceptance.json
Documentation/media-acceptance.json
Documentation/package-acceptance.json
Documentation/ppc-acceptance.json
Documentation/publication.md
Documentation/reproduction-acceptance.json
Documentation/sound-acceptance.json
Documentation/startup-credit-analysis.json
Documentation/startup-host-acceptance.json
Documentation/startup-launch-acceptance.json
Documentation/typecheck-acceptance.json
Documentation/validation.md
Documentation/z80-acceptance.json
Licenses/Crypto-BSD-3-Clause.txt
Licenses/README.md
Licenses/SourceNotices.txt
Licenses/Supermodel-LICENSE.txt
Licenses/Supermodel-README.txt
Licenses/manifest.json
Play.command
README.md
Resources/Info.plist
Sources/Bridge/DetachedNetwork.h
Sources/Bridge/Platform.cpp
Sources/Bridge/vf3.cpp
Sources/Bridge/vf3.h
Sources/Mac/AudioOutput.swift
Sources/Mac/CabinetSave.swift
Sources/Mac/Controls.swift
Sources/Mac/EngineWorker.swift
Sources/Mac/GameScene.swift
Sources/Mac/Input.swift
Sources/Mac/Media.swift
Sources/Mac/NativeGame.swift
Sources/Mac/README.md
Sources/Mac/Tests/main.swift
Sources/Mac/main.swift
Sources/Translated/ppc/README.md
Sources/Translated/sound/README.md
Tools/ReferenceLab/control.py
Tools/ReferenceLab/fighter_routes.py
Tools/ReferenceLab/invincibility_fixture.cpp
Tools/ReferenceLab/ppc_observer.inc
Tools/ReferenceLab/ppc_operation_fixture.cpp
Tools/ReferenceLab/ppc_z80_fixture.cpp
Tools/ReferenceLab/replay.py
Tools/ReferenceLab/sound68k_probe.c
Tools/ReferenceLab/sound_captures.py
Tools/ReferenceLab/sound_dsp_probe.cpp
Tools/ReferenceLab/sound_lifecycle.py
Tools/ReferenceLab/sound_observe.cpp
Tools/ReferenceLab/sound_observe.h
scripts/build.sh
scripts/build_engine.py
scripts/build_host.sh
scripts/build_icon.sh
scripts/build_icon.swift
scripts/compile_ppc.py
scripts/compile_sound.py
scripts/compile_z80.py
scripts/import_assets.py
scripts/prepare_licenses.py
scripts/prepare_native.py
scripts/prepare_publication.py
scripts/prepare_source.py
scripts/verify_bridge.py
scripts/verify_host.py
scripts/verify_host_invincibility.py
scripts/verify_integration.py
scripts/verify_invincibility.py
scripts/verify_live.py
scripts/verify_package.py
scripts/verify_ppc.py
scripts/verify_sound.py
scripts/verify_startup.py
scripts/verify_startup_launch.py
scripts/verify_z80.py
'''.split()
SOURCE_TREES = {'Sources', 'Tools', 'scripts', 'Configuration', 'Documentation', 'Licenses', 'Resources'}
TEXT_SUFFIXES = {'.py', '.sh', '.command', '.c', '.cpp', '.h', '.hpp', '.inc', '.swift', '.xml', '.md', '.json', '.txt', '.plist'}


def inventory() -> list[Path]:
    if len(REVIEWED_FILES) != len(set(REVIEWED_FILES)):
        raise RuntimeError('Duplicate reviewed source path')
    media = json.loads((ROOT / 'Configuration/media.json').read_text())
    if media.get('game') != 'vf3':
        raise RuntimeError('Publication requires current Virtua Fighter 3 media identities')
    paths = []
    for name in REVIEWED_FILES:
        path = ROOT / name
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or any((ROOT / parent).is_symlink() for parent in [relative, *relative.parents]) or not path.is_file():
            raise RuntimeError('Missing or unsafe reviewed source: ' + name)
        if path.suffix not in TEXT_SUFFIXES and name not in {'.gitignore', 'COPYING'}:
            raise RuntimeError('Non-source reviewed extension: ' + name)
        paths.append(relative)
    extra = []
    for directory in SOURCE_TREES:
        for path in (ROOT / directory).rglob('*'):
            if '__pycache__' in path.parts or path.name == '.DS_Store':
                continue
            if path.is_file() and path.relative_to(ROOT).as_posix() not in REVIEWED_FILES:
                extra.append(path.relative_to(ROOT).as_posix())
    if extra:
        raise RuntimeError('New files require an explicit publication inventory review: ' + json.dumps(sorted(extra)))
    return sorted(paths)


def known_media(maximum_source_bytes: int):
    """Hash all supplied files and recursively decoded ZIP/7z members, plus local media products."""
    identities = {}; candidates = {}; names = set(); count = 0
    def add(name: str, stream, length: int):
        nonlocal count
        digest = hashlib.sha256(); data = bytearray() if length <= maximum_source_bytes else None
        size = 0
        while block := stream.read(1024 * 1024):
            digest.update(block); size += len(block)
            if data is not None: data.extend(block)
        if size != length:
            raise RuntimeError('Media changed during scanning: ' + name)
        if size == 0: return
        count += 1; value = digest.hexdigest(); names.add(Path(name).name)
        identities[value] = size
        if data is not None: candidates[value] = (name, bytes(data))
    def inspect(path: Path, label: str, depth: int = 0):
        if path.is_symlink():
            raise RuntimeError('Media link is outside the scan contract: ' + label)
        before = path.stat()
        with path.open('rb') as stream: add(label, stream, before.st_size)
        suffix = path.suffix.lower()
        if suffix in {'.zip', '.7z'} and depth >= 8:
            raise RuntimeError('Media archive nesting exceeds the scan bound: ' + label)
        if suffix == '.zip':
            with zipfile.ZipFile(path) as archive:
                for index, member in enumerate(archive.infolist()):
                    if member.is_dir(): continue
                    member_label = label + '/' + member.filename
                    extension = Path(member.filename).suffix.lower()
                    if extension in {'.zip', '.7z'}:
                        # Supplied download wrappers contain another ROM ZIP.
                        # Decode them too, without trusting archive member paths.
                        with tempfile.TemporaryDirectory(prefix='nested-media-', dir=REVIEW) as work:
                            nested = Path(work) / ('archive-' + str(index) + extension)
                            with archive.open(member) as stream, nested.open('wb') as output:
                                shutil.copyfileobj(stream, output)
                            inspect(nested, member_label, depth + 1)
                    else:
                        with archive.open(member) as stream: add(member_label, stream, member.file_size)
        elif suffix == '.7z':
            listed = subprocess.check_output(['/usr/bin/tar', '-tf', str(path)], text=True).splitlines()
            detail = subprocess.check_output(['/usr/bin/tar', '-tvf', str(path)], text=True).splitlines()
            if any(not line.startswith(('-', 'd')) for line in detail):
                raise RuntimeError('Archive has unsupported links or special files: ' + label)
            if any(Path(name).is_absolute() or '..' in Path(name).parts for name in listed):
                raise RuntimeError('Unsafe media archive member: ' + label)
            with tempfile.TemporaryDirectory(prefix='media-scan-', dir=REVIEW) as work:
                subprocess.run(['/usr/bin/tar', '--no-same-owner', '--no-same-permissions', '-xf', str(path), '-C', work], check=True)
                for member in sorted(Path(work).rglob('*')):
                    if member.is_symlink(): raise RuntimeError('Unexpected media archive link')
                    if member.is_file(): inspect(member, label + '/' + member.relative_to(work).as_posix(), depth + 1)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('Media changed during scanning: ' + label)

    supplied = ROOT / 'Virtua Fighter 3 ROMs'
    if not supplied.is_dir() or supplied.is_symlink():
        raise RuntimeError('Supplied media directory is required for the complete publication scan')
    for path in sorted(supplied.rglob('*')):
        if path.is_symlink(): raise RuntimeError('Supplied media contains a symbolic link')
        if path.is_file() and path.name != '.DS_Store': inspect(path, path.relative_to(ROOT).as_posix())
    bundled = ROOT / 'build/assets/vf3.zip'
    inspect(bundled, 'bundled/vf3.zip')
    seed = ROOT / 'build/assets/default.nv'
    if seed.is_file():
        with seed.open('rb') as stream: add('bundled/default.nv', stream, seed.stat().st_size)
    for path in sorted((ROOT / 'build/generated').rglob('*')):
        if path.is_file() and path.suffix.lower() in {'.bin', '.rom'}:
            with path.open('rb') as stream: add(path.relative_to(ROOT).as_posix(), stream, path.stat().st_size)
    return identities, candidates, names, count


def scan() -> dict:
    allowed = {str(path) for path in inventory()}
    files = sorted(p for p in PAYLOAD.rglob('*') if p.is_file())
    if not files or {p.relative_to(PAYLOAD).as_posix() for p in files} != allowed:
        raise RuntimeError('Staged inventory differs from explicitly reviewed files')
    identities, candidates, media_names, count = known_media(max(p.stat().st_size for p in files))
    private = re.compile(rb'/(?:Users|home)/[^/\s"\x27]+/')
    secrets = [re.compile(pattern) for pattern in [rb'gh[pousr]_[A-Za-z0-9]{30,}',
        rb'github_pat_[A-Za-z0-9_]{30,}', rb'AKIA[0-9A-Z]{16}', rb'xox[baprs]-[A-Za-z0-9-]{20,}',
        rb'sk-(?:proj-|svcacct-)[A-Za-z0-9_-]{20,}', rb'-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----']]
    issues = []
    for path in files:
        name = path.relative_to(PAYLOAD).as_posix(); data = path.read_bytes()
        if path.is_symlink(): issues.append((name, 'symbolic link'))
        if path.name in media_names or hashlib.sha256(data).hexdigest() in identities:
            issues.append((name, 'complete media identity'))
        for media_name, needle in candidates.values():
            if len(data) >= len(needle) and needle in data:
                issues.append((name, 'raw complete media: ' + media_name))
            if len(data) >= len(needle) * 2 and needle.hex().encode() in data.lower():
                issues.append((name, 'hex-encoded complete media: ' + media_name))
            if len(data) >= ((len(needle) + 2) // 3) * 4 and base64.b64encode(needle) in data:
                issues.append((name, 'base64-encoded complete media: ' + media_name))
        try: data.decode('utf-8')
        except UnicodeDecodeError: issues.append((name, 'non-UTF8 source data'))
        if private.search(data): issues.append((name, 'local user path'))
        if any(pattern.search(data) for pattern in secrets): issues.append((name, 'credential-shaped text'))
        if path.suffix == '.py': ast.parse(data, filename=name)
    if issues: raise RuntimeError(json.dumps(issues, indent=2))
    return {'passed': True, 'files': len(files), 'bytes': sum(p.stat().st_size for p in files),
            'mediaObjectsRead': count, 'uniqueMediaIdentities': len(identities),
            'mediaIdentityInventorySHA256': hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest(),
            'rawHexBase64CompleteMediaMatches': 0, 'localUserPathMatches': 0, 'credentialPatternMatches': 0,
            'scope': 'Explicit source allowlist and UTF8 text. Every supplied file and recursively decoded ZIP/7z member (including nested download wrappers), bundled ZIP and its members, and generated .bin/.rom image checked by complete identity and raw/contiguous-hex/base64 encoding when its size could fit. This is a bounded scan, not a general copyright or secret classifier.'}


def prepare() -> None:
    paths = inventory()
    REVIEW.mkdir(parents=True, exist_ok=True)
    if (PAYLOAD / '.git').exists():
        raise RuntimeError('Reviewed staging contains a Git checkout; preserve it and use a separate publication checkout')
    if PAYLOAD.exists(): shutil.rmtree(PAYLOAD)
    for relative in paths:
        target = PAYLOAD / relative; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    report = scan()
    rows = []
    for relative in paths:
        source, staged = ROOT / relative, PAYLOAD / relative
        if sha(source) != sha(staged) or stat.S_IMODE(source.stat().st_mode) != stat.S_IMODE(staged.stat().st_mode):
            raise RuntimeError('Source changed while staging; repeat after edits finish: ' + str(relative))
        rows.append({'path': str(relative), 'sha256': sha(staged), 'bytes': staged.stat().st_size,
                     'mode': stat.S_IMODE(staged.stat().st_mode)})
    write_json(REVIEW / 'engine-companion-manifest.json', {
        'status': 'Local source review; no publication or independent companion rebuild performed',
        'publicationActionsPerformed': False, 'game': 'vf3',
        'target': 'Virtua Fighter 3 Japan Revision D', 'upstreamCommit': REVISION,
        'upstreamArchiveSHA256': ARCHIVE_SHA256, 'scriptSHA256': sha(Path(__file__)),
        'contentScan': report, 'files': rows})
    print(json.dumps({'prepared': True, **report}))


def verify() -> None:
    manifest = json.loads((REVIEW / 'engine-companion-manifest.json').read_text())
    if manifest.get('game') != 'vf3': raise RuntimeError('Staging manifest belongs to another game')
    if manifest['scriptSHA256'] != sha(Path(__file__)): raise RuntimeError('Publication script changed')
    for row in manifest['files']:
        for root in [ROOT, PAYLOAD]:
            path = root / row['path']
            if path.is_symlink() or sha(path) != row['sha256'] or stat.S_IMODE(path.stat().st_mode) != row['mode']:
                raise RuntimeError('Reviewed source or file mode changed: ' + row['path'])
    if scan() != manifest['contentScan']: raise RuntimeError('Content scan changed')
    write_json(REVIEW / 'source-boundary-acceptance.json', {
        'passed': True, 'manifestSHA256': sha(REVIEW / 'engine-companion-manifest.json'),
        'scope': 'Exact reviewed source and local media content boundary only; no fresh build or gameplay acceptance claim.'})
    print('Source boundary verified; nothing published.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--verify', action='store_true')
    mode.add_argument('--inventory', action='store_true', help='Check only explicit source inventory; do not scan media or stage files')
    args = parser.parse_args()
    if args.inventory:
        print(json.dumps({'inventoryReady': True, 'files': [str(p) for p in inventory()], 'mediaScanned': False, 'publicationActionsPerformed': False}))
    elif args.verify: verify()
    else: prepare()

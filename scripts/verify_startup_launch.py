#!/usr/bin/env python3
"""Verify normal bundled credit cleanup using a disposable original-input save.

Keep the test app focused and leave its controls untouched. This launches the
real interactive bundle, without headless or replay flags. It never selects the
user's Application Support save directory.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import time
from import_assets import ROOT, sha, write_json


CREDIT_OFFSETS = (0x1e046, 0x1e047, 0x1e04a, 0x1e04b, 0x1e04e, 0x1e04f)


def blocks(data):
    """Independently locate the three original CBlockFile payloads."""
    result = {}
    cursor = 0
    for expected_name, expected_size in [('VF3 NVRAM', 0), ('93C46', 166), ('Backup RAM', 0x20000)]:
        if len(data) - cursor < 12:
            raise ValueError('Truncated original-save header')
        size, names, comments = struct.unpack_from('<III', data, cursor)
        header = 12 + names + comments
        if not names or not comments or size < header or size > len(data) - cursor or size - header != expected_size:
            raise ValueError('Unexpected original-save block sizes')
        name = data[cursor + 12:cursor + 12 + names]
        comment = data[cursor + 12 + names:cursor + header]
        if name != expected_name.encode() + b'\0' or comment[-1:] != b'\0' or b'\0' in comment[:-1]:
            raise ValueError('Unexpected original-save block metadata')
        result[expected_name] = (cursor + header, data[cursor + header:cursor + size])
        cursor += size
    if cursor != len(data):
        raise ValueError('Unexpected trailing original-save blocks')
    eeprom = result['93C46'][1]
    ram = result['Backup RAM'][1]
    if eeprom[:4] != b'ESAG' or eeprom[64:68] != b'ESAG' or ram[0x1e050:0x1e058] != b'GASESEGA':
        raise ValueError('Original cabinet identity signatures do not match')
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=Path, required=True, help='Immutable positive-credit save produced by original coin inputs')
    parser.add_argument('--output', type=Path, help='Fresh directory under build/; otherwise a unique directory is created')
    parser.add_argument('--seconds', type=float, default=30)
    args = parser.parse_args()
    if not 20 <= args.seconds <= 60:
        raise ValueError('Use a bounded 20–60 second interactive launch')
    seed = args.seed.resolve()
    if not seed.is_relative_to(ROOT/'build'):
        raise ValueError('Use an isolated original-input fixture under build/, never a real user save')
    original = seed.read_bytes()
    parsed = blocks(original)
    base = parsed['Backup RAM'][0]
    before = [original[base + offset] for offset in CREDIT_OFFSETS]
    if not any(before):
        raise ValueError('The fixture must contain positive credits or coin-conversion progress')
    expected = bytearray(original)
    for offset in CREDIT_OFFSETS:
        expected[base + offset] = 0
    expected = bytes(expected)

    app = ROOT/'build/Virtua Fighter 3.app'
    executable = app/'Contents/MacOS/VirtuaFighter3'
    package = ROOT/'build/package-manifest.json'
    engine = ROOT/'build/native/engine-build-manifest.json'
    archive = ROOT/'build/native/libvf3.a'
    helper = ROOT/'Sources/Mac/CabinetSave.swift'
    analysis = ROOT/'Documentation/startup-credit-analysis.json'
    manifest = json.loads(package.read_text())
    engine_manifest = json.loads(engine.read_text())
    if (manifest['executableSHA256'] != sha(executable) or manifest['engineManifestSHA256'] != sha(engine)
            or manifest['nativeArchiveSHA256'] != sha(archive) or not engine_manifest['shippingNative']
            or engine_manifest['diagnostics']):
        raise RuntimeError('Current packaged native identities are required')
    host_sources = {str(path.relative_to(ROOT)): sha(path) for path in sorted((ROOT/'Sources/Mac').glob('*.swift'))}
    if manifest['hostSources'] != host_sources:
        raise RuntimeError('Rebuild the app after its host sources change')
    with (app/'Contents/Info.plist').open('rb') as stream:
        if plistlib.load(stream)['CFBundleIdentifier'] != 'local.william.virtuafighter3':
            raise RuntimeError('The interactive launch policy requires the actual VF3 bundle identity')
    match = re.search(r'static let creditOffsets\s*=\s*\[([^\]]+)\]', helper.read_text())
    if not match or tuple(int(value.strip(), 0) for value in match[1].split(',')) != CREDIT_OFFSETS:
        raise RuntimeError('Credit-field configuration changed; review the verifier')
    if not json.loads(analysis.read_text())['passed']:
        raise RuntimeError('Original-input credit analysis must pass first')
    # Pinned SaveState writes 64 UINT16 EEPROM registers, followed by 38 bytes
    # of serial pins, shift buffers, latched address and control state. Original
    # reads during the attract loop may change that trailing serial state.
    eeprom_source = ROOT/'build/upstream/supermodel/Src/Model3/93C46.cpp'
    eeprom_header = ROOT/'build/upstream/supermodel/Src/Model3/93C46.h'
    sources = [executable, package, engine, archive, analysis, eeprom_source, eeprom_header, Path(__file__).resolve()]
    inputs = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    inputs.update(host_sources)
    # Do not interfere with another real or diagnostic instance of the app.
    inventory = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
    for line in inventory.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and (fields[1] == str(executable) or fields[1].startswith(str(executable) + ' ')):
            raise RuntimeError('Virtua Fighter 3 is already running; finish that session before this isolated test')

    if args.output:
        output = args.output.resolve()
        if not output.is_relative_to(ROOT/'build'):
            raise ValueError('Startup evidence and disposable saves must remain under ignored build/')
        output.mkdir(parents=True, exist_ok=False)
    else:
        parent = ROOT/'build/validation'
        parent.mkdir(parents=True, exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix='startup-launch-', dir=parent))
    saves = output/'saves'
    saves.mkdir()
    save = saves/'vf3.nv'
    shutil.copy2(seed, save)
    expected_backup = saves/'Backups'/('vf3-before-startup-' + digest(original) + '.nv')
    capture = output/'attract-candidate.png'
    telemetry = output/'telemetry.json'
    env = dict(os.environ, VF3_RTC_EPOCH='946684800')
    for name in ['VF3_FACTORY_SETTINGS', 'VIRTUA_FIGHTER_3_ASSET_DIR', 'VIRTUA_FIGHTER_3_SAVE_DIR']:
        env.pop(name, None)
    command = [str(executable), '--save-dir', str(saves), '--mute', '--audio-report', str(telemetry),
               '--capture', str(capture), '--capture-after', str(args.seconds - 1), '--quit-after', str(args.seconds)]
    cleanup_observed = False
    with (output/'run.log').open('w') as log:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + min(15, args.seconds - 2)
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError('Interactive app exited before startup cleanup was observed')
                observed = save.read_bytes()
                if expected_backup.is_file() and observed == expected:
                    if expected_backup.read_bytes() != original:
                        raise AssertionError('Startup backup does not exactly preserve the seed')
                    if any(stat.S_IMODE(path.stat().st_mode) != stat.S_IMODE(seed.stat().st_mode)
                           for path in [save, expected_backup]):
                        raise AssertionError('Startup cleanup did not preserve file permissions')
                    (output/'before-engine-exit.nv').write_bytes(observed)
                    cleanup_observed = True
                    break
                time.sleep(0.05)
            if not cleanup_observed:
                raise AssertionError('The bundled interactive launch did not clear only the expected credit bytes')
            status = process.wait(timeout=args.seconds + 30)
            if status != 0:
                raise RuntimeError(f'Interactive app failed with exit code {status}')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)

    report = json.loads(telemetry.read_text())
    final = save.read_bytes()
    final_blocks = blocks(final)
    final_values = [final_blocks['Backup RAM'][1][offset] for offset in CREDIT_OFFSETS]
    checks = {
        'normalInteractiveBundleWithoutReplay': True,
        'startupChangeObservedBeforeNativeExitSave': cleanup_observed,
        'exactOriginalBackup': expected_backup.read_bytes() == original,
        'allOtherBytesPreservedAtStartup': (output/'before-engine-exit.nv').read_bytes() == expected,
        'creditFieldsRemainZeroAfterNoInputRun': final_values == [0] * len(CREDIT_OFFSETS),
        'persistentEEPROMPreservedThroughExit': final_blocks['93C46'][1][:128] == parsed['93C46'][1][:128],
        'seedUnchanged': seed.read_bytes() == original,
        'visibleWindow': report['windowVisible'] and not report['windowOccluded'],
        'unpaused': not report['pausedByHost'],
        'nativeFramesRendered': report['gameFrames'] >= 600,
        'noNativeFault': report['gameState']['faultCode'] == 0,
        'invincibilityStartsOff': report['gameState']['invincible'] is False,
        'finalInputNeutral': report['lastInput'] == {'player1': 0, 'player2': 0},
        'nativeCallsOnDedicatedThread': report['engineCallsOnDedicatedThread'] is True,
        'frameCaptureWritten': capture.is_file() and capture.stat().st_size > 0,
        'inputsUnchanged': all(sha(ROOT/name) == value for name, value in inputs.items()),
    }
    changed = [hex(offset) for offset in CREDIT_OFFSETS if original[base + offset] != 0]
    result = {'passed': all(checks.values()), 'checks': checks, 'inputs': inputs,
              'evidenceDirectory': str(output.relative_to(ROOT)), 'seconds': args.seconds,
              'seedSHA256': digest(original), 'seedBytes': len(original),
              'backupSHA256': sha(expected_backup), 'startupSaveSHA256': digest(expected),
              'creditFieldOffsets': [hex(offset) for offset in CREDIT_OFFSETS],
              'creditFieldsBefore': before, 'creditFieldsAfterExit': final_values,
              'changedBackupRAMOffsetsAtStartup': changed,
              'allNonCreditBytesPreservedAtStartup': True,
              'finalSaveSHA256': digest(final), 'frameCaptureSHA256': sha(capture) if capture.is_file() else None,
              'eepromSerialStateChangedOffsets': [hex(offset) for offset in range(128, 166)
                                                   if parsed['93C46'][1][offset] != final_blocks['93C46'][1][offset]],
              'eepromExitComparison': 'Pinned C93C46::SaveState serializes all 128 persistent EEPROM bytes followed by 38 serial-interface state bytes. Persistent bytes must remain identical; original engine reads may change the trailing shift/latch state. The full 166-byte block is nevertheless preserved exactly by startup cleanup before the engine runs.',
              'telemetry': report,
              'visualReview': 'Capture retained for independent attract-mode inspection; no image classification is asserted by this script.',
              'realUserSaveRead': False, 'realUserSaveWritten': False, 'physicalControllerActuationTested': False,
              'scope': 'Actual bundled normal interactive startup on a copied original-input positive-credit fixture. Exact backup and only the authenticated six credit/remainder bytes cleared are observed before native shutdown can write bookkeeping. No input automation is supplied; final input telemetry is neutral. Capture supports separate visual review. No physical controller or complete-game claim.'}
    write_json(output/'acceptance.json', result)
    if not result['passed']:
        raise RuntimeError('Startup launch checks failed: ' + ', '.join(name for name, passed in checks.items() if not passed))
    write_json(ROOT/'Documentation/startup-launch-acceptance.json', result)
    print(json.dumps({'passed': True, 'evidenceDirectory': str(output.relative_to(ROOT)),
                      'gameFrames': report['gameFrames'], 'changedCreditFields': len(changed)}))


if __name__ == '__main__':
    main()

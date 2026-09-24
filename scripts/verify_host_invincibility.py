#!/usr/bin/env python3
"""Compare packaged assist replay and fresh sessions with the shipping C ABI."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
from import_assets import ROOT, sha, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'build/validation/host-invincibility')
    args = parser.parse_args()
    route = args.route.resolve()
    data = json.loads(route.read_text())
    frames = data['frames']
    if type(frames) is not int or not 1 <= frames <= 1000000:
        raise ValueError('A bounded route with an explicit frame count is required')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # Laboratory capture timestamps are not game input. Keep the product's
    # strict replay schema, and replay identical events in both implementations.
    if set(data) - {'frames', 'events', 'captures'}:
        raise ValueError('Unsupported laboratory replay metadata')
    product_route = out/'replay.json'
    write_json(product_route, {key: data[key] for key in ['frames', 'events']})
    executable = ROOT/'build/Virtua Fighter 3.app/Contents/MacOS/VirtuaFighter3'
    library = ROOT/'build/native/libvf3.dylib'
    engine = ROOT/'build/native/engine-build-manifest.json'
    package = ROOT/'build/package-manifest.json'
    replay = ROOT/'Tools/ReferenceLab/replay.py'
    semantics = ROOT/'Documentation/invincibility-acceptance.json'
    manifest = json.loads(package.read_text())
    if manifest['executableSHA256'] != sha(executable) or manifest['engineManifestSHA256'] != sha(engine):
        raise RuntimeError('Packaged artifact identity changed')
    native_manifest = json.loads(engine.read_text())
    if not native_manifest['shippingNative'] or native_manifest['diagnostics'] or native_manifest['dynamicLibrarySHA256'] != sha(library):
        raise RuntimeError('A current shipping native library is required')
    qualification = json.loads(semantics.read_text())
    if not qualification['passed']:
        raise RuntimeError('Separate invincibility semantics qualification is required')
    for name, digest in {**qualification['lockedInputs'], **qualification['provenance']}.items():
        if sha(ROOT/name) != digest:
            raise RuntimeError('Invincibility semantics evidence is stale: ' + name)
    for path in [library, engine]:
        if qualification['provenance'].get(str(path.relative_to(ROOT))) != sha(path):
            raise RuntimeError('Invincibility semantics do not bind the shipping engine')
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in
              [executable, library, engine, package, replay, route, product_route, semantics, Path(__file__).resolve()]}
    env = {**os.environ, 'VF3_RTC_EPOCH': '946684800'}
    for key in ['VF3_FACTORY_SETTINGS', 'VIRTUA_FIGHTER_3_ASSET_DIR', 'VIRTUA_FIGHTER_3_SAVE_DIR']:
        env.pop(key, None)
    commands = [
        ('native', [sys.executable, str(replay), '--library', str(library), '--route', str(product_route),
                    '--frames', str(frames), '--capture-every', str(frames), '--output', str(out/'native')]),
        ('packaged', [str(executable), '--self-test', '--diagnostic-run', str(product_route),
                      '--diagnostic-report', str(out/'packaged.json'),
                      '--diagnostic-frames', str(out/'packaged.jsonl'),
                      '--diagnostic-capture', str(out/'packaged.png')]),
    ]
    for name, command in commands:
        with (out/(name+'.log')).open('w') as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    expected = [json.loads(line) for line in (out/'native/trace.jsonl').read_text().splitlines()]
    actual = [json.loads(line) for line in (out/'packaged.jsonl').read_text().splitlines()]
    if len(expected) != frames or actual != expected:
        first = next((i + 1 for i, (a, b) in enumerate(zip(expected, actual)) if a != b), None)
        raise AssertionError(f'Packaged/native disagreement: {len(expected)}/{len(actual)} rows; first {first}')
    states = [row['invincible'] for row in actual]
    transitions = [i + 1 for i in range(1, frames) if states[i] != states[i - 1]]
    if (not all(type(value) is bool for value in states) or set(states) != {False, True}
            or len(transitions) < 2 or states[0] is not False or states[-1] is not False):
        raise AssertionError('Route must exercise assist OFF, ON and OFF again')
    report = json.loads((out/'packaged.json').read_text())
    native = json.loads((out/'native/report.json').read_text())
    if not (report['frames'] == frames and report['deterministic'] and report['comparedRuns'] == 2
            and report['finalState']['faultCode'] == 0
            and report['finalState']['invincible'] == states[-1] and report['nonzeroSamples'] > 0
            and report['pictureSHA256'] == native['rgbaSHA256']
            and report['audioSHA256'] == native['pcmSHA256']
            and report['sampleFrames'] == native['sampleFrames']):
        raise AssertionError('Packaged aggregate, fault or fresh-session check failed')
    if any(sha(ROOT/name) != digest for name, digest in inputs.items()):
        raise RuntimeError('Qualification input changed while running')
    result = {'passed': True, 'inputs': inputs, 'framesCompared': frames,
              'sameOriginalInputEvents': json.loads(product_route.read_text())['events'] == data['events'],
              'excludedLaboratoryMetadata': ['captures'] if 'captures' in data else [],
              'sampleFrames': report['sampleFrames'], 'freshPackagedRuns': 2,
              'exactRGBA_PCM_Count_AssistAgreement': True, 'enabledFrames': states.count(True),
              'assistTransitionFrames': transitions, 'finalFaultCode': 0,
              'nativeTraceSHA256': sha(out/'native/trace.jsonl'),
              'packagedTraceSHA256': sha(out/'packaged.jsonl'),
              'scope': 'Actual bundled Swift executable versus shipping C ABI on the same original inputs and explicit assist requests, plus two deterministic fresh Swift sessions. Invincibility game semantics are qualified separately. No GUI or physical controller actuation claim.'}
    write_json(out/'acceptance.json', result)
    write_json(ROOT/'Documentation/host-invincibility-acceptance.json', result)
    print(json.dumps({'passed': True, 'framesCompared': frames, 'enabledFrames': states.count(True)}))


if __name__ == '__main__':
    main()

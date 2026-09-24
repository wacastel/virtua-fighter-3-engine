#!/usr/bin/env python3
"""Compare the packaged Swift executable against an accepted direct-engine route."""
from pathlib import Path
import argparse, json, os, subprocess
from import_assets import ROOT, sha, write_json


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--route', type=Path, default=ROOT/'Configuration/replays/arcade.json')
    ap.add_argument('--output', type=Path, default=ROOT/'build/validation/host')
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = ROOT/'build/Virtua Fighter 3.app'
    binary = app/'Contents/MacOS/VirtuaFighter3'
    package = ROOT/'build/package-manifest.json'
    integration = ROOT/'Documentation/integration-acceptance.json'
    accepted = json.loads(integration.read_text())
    row = next(x for x in accepted['routes'] if x['routeSHA256'] == sha(args.route))
    if accepted['engineManifestSHA256'] != sha(ROOT/'build/native/engine-build-manifest.json'):
        raise RuntimeError('Integration acceptance is stale')
    identity = {str(p.relative_to(ROOT)): sha(p) for p in [binary, package, integration, args.route, Path(__file__).resolve()]}
    manifest = json.loads(package.read_text())
    if manifest['executableSHA256'] != sha(binary) or manifest['engineManifestSHA256'] != accepted['engineManifestSHA256']:
        raise RuntimeError('Packaged executable is not the accepted native engine')
    command = [str(binary), '--diagnostic-run', str(args.route), '--diagnostic-report', str(args.output/'replay.json'),
               '--diagnostic-frames', str(args.output/'trace.jsonl'), '--diagnostic-capture', str(args.output/'final.png')]
    environment = {**os.environ, 'VF3_RTC_EPOCH': '946684800'}
    environment.pop('VF3_FACTORY_SETTINGS', None)
    with (args.output/'run.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    baseline = ROOT/'build/validation/integration'/args.route.stem/'native/trace.jsonl'
    if sha(baseline) != row['perFrameTraceSHA256']:
        raise RuntimeError('Direct-engine trace identity changed')
    expected = [json.loads(x) for x in baseline.read_text().splitlines()]
    actual = [json.loads(x) for x in (args.output/'trace.jsonl').read_text().splitlines()]
    if actual != expected:
        differences = [i+1 for i, (x, y) in enumerate(zip(expected, actual)) if x != y]
        raise AssertionError(f'Packaged host frame mismatch: lengths {len(expected)}/{len(actual)}, first differences {differences[:10]}')
    replay = json.loads((args.output/'replay.json').read_text())
    if replay['frames'] != row['frames'] or replay['pictureSHA256'] != row['rgbaSHA256'] or replay['audioSHA256'] != row['pcmSHA256'] or replay['sampleFrames'] != row['sampleFrames']:
        raise AssertionError('Packaged host aggregate disagreement')
    lifecycle_command = [str(binary), '--self-test', '--diagnostic-run', str(args.route),
                         '--frames', '2400', '--diagnostic-report', str(args.output/'lifecycle.json')]
    with (args.output/'lifecycle.log').open('w') as log:
        subprocess.run(lifecycle_command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    lifecycle = json.loads((args.output/'lifecycle.json').read_text())
    if lifecycle.get('deterministic') is not True or lifecycle.get('comparedRuns') != 2:
        raise AssertionError('Fresh-session determinism was not established')
    if any(sha(ROOT/name) != value for name, value in identity.items()):
        raise RuntimeError('Inputs changed during packaged host validation')
    result = {'passed': True, 'inputs': identity, 'route': str(args.route.relative_to(ROOT)),
              'frames': len(actual), 'sampleFrames': replay['sampleFrames'],
              'exactPictureAudioCountAgreement': True, 'finalFaultCode': replay['finalState']['faultCode'],
              'elapsedSeconds': replay['elapsedSeconds'],
              'freshSessions': {'sameProcess': True, 'runs': 2, 'framesEach': lifecycle['frames'],
                                'pictureSHA256': lifecycle['pictureSHA256'], 'audioSHA256': lifecycle['audioSHA256'],
                                'sampleFramesEach': lifecycle['sampleFrames'], 'deterministic': True},
              'scope': 'Real packaged Swift executable and bundled media match every accepted direct-engine RGBA/PCM/count frame; two additional fresh sessions in one process agree on picture, PCM and count. These headless runs do not exercise the display or audio device.'}
    write_json(args.output/'acceptance.json', result)
    write_json(ROOT/'Documentation/host-acceptance.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()

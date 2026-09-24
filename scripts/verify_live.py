#!/usr/bin/env python3
"""Run a bounded visible fight and validate native display/audio-device telemetry."""
from pathlib import Path
import argparse, json, os, subprocess
from import_assets import ROOT, sha, write_json


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seconds', type=float, default=80)
    ap.add_argument('--output', type=Path, default=ROOT/'build/validation/live')
    args = ap.parse_args()
    if not 60 <= args.seconds <= 300:
        raise ValueError('Use a bounded 60–300 second visible run')
    args.output.mkdir(parents=True, exist_ok=True)
    binary = ROOT/'build/Virtua Fighter 3.app/Contents/MacOS/VirtuaFighter3'
    route = ROOT/'Configuration/replays/arcade.json'
    package = ROOT/'build/package-manifest.json'
    identities = {str(p.relative_to(ROOT)): sha(p) for p in [binary, route, package, Path(__file__).resolve()]}
    if json.loads(package.read_text())['executableSHA256'] != sha(binary):
        raise RuntimeError('Packaged executable identity mismatch')
    environment = {**os.environ, 'VF3_RTC_EPOCH': '946684800'}
    environment.pop('VF3_FACTORY_SETTINGS', None)
    command = [str(binary), '--audio-replay', str(route), '--sound',
               '--audio-report', str(args.output/'telemetry.json'),
               '--capture', str(args.output/'fight.png'), '--capture-after', str(args.seconds-5),
               '--quit-after', str(args.seconds)]
    with (args.output/'run.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                       timeout=args.seconds+60, check=True)
    result = json.loads((args.output/'telemetry.json').read_text())
    fps = result['gameFrames']/args.seconds
    display_fps = result.get('presentedFrames', 0)/args.seconds
    checks = {
        'visibleWindow': result['windowVisible'] and not result['windowOccluded'],
        'unpaused': not result['pausedByHost'],
        'noEngineFault': result['gameState']['faultCode'] == 0,
        'near60FramesPerSecond': 58 <= fps <= 60.1,
        'near60PresentedFramesPerSecond': 55 <= display_fps <= 60.1,
        'audioDeviceRunning': result['isRunning'] and result['isPlaying'],
        'audioOpenedWithoutFailure': result['engineStartCount'] >= 1 and result['engineFailureCount'] == 0,
        'audioRendered': result['renderedFrames'] > 44100,
        'noAudioBacklogRecovery': result['backlogRecoveryCount'] == 0,
        'noAudioUnderruns': result['underrunCount'] == 0,
        'boundedAudioQueue': result['peakPendingFrames'] <= 11025+735,
        'frameCaptureWritten': (args.output/'fight.png').is_file(),
        'mainThreadUpdates': result['updatesOnMainThread'],
        'nativeCallsOnDedicatedThread': result.get('engineCallsOnDedicatedThread') is True,
    }
    if any(sha(ROOT/name) != value for name, value in identities.items()):
        raise RuntimeError('Inputs changed during visible validation')
    report = {'passed': all(checks.values()), 'checks': checks, 'inputs': identities,
              'seconds': args.seconds, 'observedFramesPerSecond': fps,
              'presentedFramesPerSecond': display_fps,
              'telemetry': result, 'frameCaptureSHA256': sha(args.output/'fight.png'),
              'scope': 'Visible AppKit/SpriteKit fight and AVFoundation output-device counters. Keep the app focused and run without competing engine workloads. No subjective listening, physical button actuation or physical arcade-board accuracy claim.'}
    write_json(args.output/'acceptance.json', report)
    if not report['passed']:
        raise RuntimeError('Live acceptance failed: '+', '.join(k for k, v in checks.items() if not v))
    write_json(ROOT/'Documentation/live-acceptance.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()

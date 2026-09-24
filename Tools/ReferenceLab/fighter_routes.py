#!/usr/bin/env python3
"""Author and optionally capture ordinary paid arcade routes for all VF3 fighters."""
from pathlib import Path
import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIGHTERS = ['akira', 'pai', 'lau', 'wolf', 'jeffry', 'kage', 'sarah', 'jacky', 'shun', 'lion', 'aoi', 'taka']
FRAMES = 4500


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def route_for(fighter):
    index = FIGHTERS.index(fighter)
    row, column = divmod(index, 6)
    events = [dict(start=1200, end=1202, player1=512), dict(start=1210, end=1212, player1=512),
              dict(start=1240, end=1242, player1=256)]
    events += [dict(start=1480 + step*20, end=1482 + step*20, player1=8) for step in range(column)]
    if row:
        events.append(dict(start=1580, end=1582, player1=2))
    events.append(dict(start=1620, end=1622, player1=16))
    # Separate presses retain original game edge semantics. Include directional
    # strikes, crouching attacks, guard, escape, and ordinary button combinations.
    moves = [24, 40, 64, 80, 128, 136, 2, 18, 34, 33, 4, 48]
    for step, frame in enumerate(range(2100, 4390, 28)):
        events.append(dict(start=frame, end=frame+12, player1=moves[step % len(moves)]))
    return dict(frames=FRAMES, events=events)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fighters', nargs='+', choices=FIGHTERS, default=FIGHTERS)
    parser.add_argument('--capture', action='store_true')
    parser.add_argument('--jobs', type=int, choices=[1,2], default=2)
    args = parser.parse_args()
    fighters = list(dict.fromkeys(args.fighters))
    routes = ROOT/'Configuration/replays'
    routes.mkdir(parents=True, exist_ok=True)
    for fighter in fighters:
        (routes/f'fighter-{fighter}.json').write_text(json.dumps(route_for(fighter),indent=2)+'\n')
    if not args.capture:
        print(json.dumps({'authored':fighters,'framesEach':FRAMES,'capturePerformed':False}));return
    library = ROOT/'build/observer/libvf3.dylib'
    manifest = ROOT/'build/observer/engine-build-manifest.json'
    observer = json.loads(manifest.read_text())
    if observer['kind'] != 'observer' or observer['shippingNative'] or observer['dynamicLibrarySHA256'] != sha(library):
        raise ValueError('Capture requires a matching original-processor observer manifest')
    inputs = {str(p.relative_to(ROOT)):sha(p) for p in [library,manifest,Path(__file__).resolve(),ROOT/'Tools/ReferenceLab/replay.py']}
    def capture(fighter):
        route = routes/f'fighter-{fighter}.json'
        route_sha = sha(route)
        output = ROOT/'build/coverage'/f'fighter-{fighter}'
        output.mkdir(parents=True,exist_ok=True)
        ppc, sound = output/'ppc-observations.tsv', output/'sound-observations.jsonl'
        ppc.unlink(missing_ok=True);sound.unlink(missing_ok=True)
        environment = {**os.environ,'VF3_RTC_EPOCH':'946684800','VF3_PPC_TRACE':str(ppc),'VF3_SOUND_CAPTURE':str(sound)}
        environment.pop('VF3_FACTORY_SETTINGS',None)
        command = [sys.executable,str(ROOT/'Tools/ReferenceLab/replay.py'),'--library',str(library),'--frames',str(FRAMES),
                   '--route',str(route),'--output',str(output),'--capture-every','1600']
        with (output/'run.log').open('w') as log:
            subprocess.run(command,cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
        result = json.loads((output/'report.json').read_text())
        if not result['passed'] or result['frames'] != FRAMES or result['librarySHA256'] != inputs[str(library.relative_to(ROOT))]:
            raise RuntimeError('Incomplete original-processor replay: '+fighter)
        if sha(route) != route_sha or not ppc.stat().st_size or not sound.stat().st_size:
            raise RuntimeError('Route changed or observer output is empty: '+fighter)
        record = {'expectedFighter':fighter,'frames':FRAMES,'route':str(route.relative_to(ROOT)),'routeSHA256':route_sha,
                  'report':str((output/'report.json').relative_to(ROOT)),'reportSHA256':sha(output/'report.json'),
                  'ppc':str(ppc.relative_to(ROOT)),'ppcSHA256':sha(ppc),'sound':str(sound.relative_to(ROOT)),'soundSHA256':sha(sound),
                  'captures':{p.name:sha(p) for p in sorted(output.glob('frame-*.png'))},
                  'selectionVisuallyConfirmed':False}
        (output/'capture-provenance.json').write_text(json.dumps({'passed':True,'inputs':inputs,**record},indent=2)+'\n')
        print(json.dumps({'captured':fighter,'frames':FRAMES,'selectionCapture':str((output/'frame-001600.png').relative_to(ROOT))}),flush=True)
        return record
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        records = list(executor.map(capture,fighters))
    if any(sha(ROOT/name) != digest for name,digest in inputs.items()):
        raise RuntimeError('Observer or fixture inputs changed during fighter capture')
    report = {'passed':True,'inputs':inputs,'routes':records,'frames':FRAMES*len(records),
              'scope':'Bounded ordinary-input original-processor captures. Expected character labels still require visual confirmation from selection and fight screenshots; this is not native parity or complete-game proof.'}
    output = ROOT/'build/coverage/fighter-route-captures.json'
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'fighters':fighters,'frames':report['frames'],'report':str(output.relative_to(ROOT))}))


if __name__ == '__main__':
    main()

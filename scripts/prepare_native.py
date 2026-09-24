#!/usr/bin/env python3
"""Reproduce the fixed VF3 port from pinned source and locally supplied Revision D media."""
from pathlib import Path
import argparse, concurrent.futures, json, os, shutil, subprocess, sys
from import_assets import ROOT
FIGHTERS = ['akira','pai','lau','jeffry','wolf','kage','sarah','jacky','shun','lion','aoi','taka']
GAMEPLAY = ['attract','arcade','versus','late-start','challenger'] + ['fighter-'+name for name in FIGHTERS]

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',type=Path,default=ROOT/'Virtua Fighter 3 ROMs/vf3')
    ap.add_argument('--jobs',type=int,default=8)
    ap.add_argument('--capture-jobs',type=int,default=3,help='Concurrent isolated observer processes (1–3)')
    args=ap.parse_args()
    if not 1<=args.capture_jobs<=3 or args.jobs<1:raise ValueError('Invalid worker count')
    def run(name,*arguments,env=None):
        print('Running '+name,flush=True)
        subprocess.run([sys.executable,str(ROOT/name),*[str(x) for x in arguments]],cwd=ROOT,env=env,check=True)
    run('scripts/prepare_source.py')
    run('scripts/import_assets.py','--game',args.game.resolve())
    game=ROOT/'build/media-source'
    run('scripts/compile_ppc.py','--observer-only')
    run('scripts/build_engine.py','--kind','observer','--jobs',args.jobs)
    capture=ROOT/'build/qualification';capture.mkdir(parents=True,exist_ok=True)
    ppc=[];merge=[]
    # These are original processor observations, never a product fallback.
    # Input diagnostics uses the original cabinet Test Menu in the laboratory.
    def observe(name):
        route=ROOT/'Configuration/replays'/(name+'.json')
        frames=json.loads(route.read_text())['frames']
        instructions=capture/(name+'-ppc.tsv');sound=capture/(name+'-sound.jsonl')
        instructions.write_text('');sound.write_text('')
        environment={**os.environ,'VF3_PPC_TRACE':str(instructions),'VF3_SOUND_CAPTURE':str(sound),'VF3_RTC_EPOCH':'946684800'}
        environment.pop('VF3_FACTORY_SETTINGS',None)
        run('Tools/ReferenceLab/replay.py','--route',route,'--frames',frames,'--output',capture/name,'--capture-every','1600',env=environment)
        return instructions,['--run',sound,capture/name/'report.json']
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.capture_jobs) as pool:
        for instructions,arguments in pool.map(observe,GAMEPLAY+['input-diagnostics']):
            ppc.append(instructions);merge+=arguments
    observations=capture/'sound-observations.jsonl'
    run('Tools/ReferenceLab/sound_captures.py',*merge,'--output',observations)
    run('scripts/compile_ppc.py','--game',game,'--observations',*ppc)
    run('scripts/compile_sound.py','--rom-dir',game,'--observations',observations)
    run('scripts/compile_z80.py','--game',game)
    run('scripts/verify_ppc.py','--game',game,'--observations',*ppc)
    run('scripts/verify_z80.py','--game',game)
    run('scripts/verify_sound.py','--rom-dir',game,'--observations',observations,'--acceptance',ROOT/'Documentation/sound-acceptance.json')
    for name in ['ppc','z80']:
        shutil.copyfile(ROOT/'build/validation'/name/'report.json',ROOT/'Documentation'/(name+'-acceptance.json'))
    run('scripts/build_engine.py','--kind','native','--jobs',args.jobs)
    run('scripts/build_engine.py','--kind','reference','--jobs',args.jobs)
    run('scripts/verify_invincibility.py','--fixture','--output',ROOT/'build/validation/invincibility')
    run('scripts/build_engine.py','--kind','native','--diagnostic','--jobs',args.jobs)
    run('scripts/verify_invincibility.py','--output',ROOT/'build/verification/invincibility','--jobs','2')
    run('scripts/verify_integration.py','--jobs','3','--routes',*[ROOT/'Configuration/replays'/(name+'.json') for name in GAMEPLAY])
    run('scripts/verify_bridge.py')
    run('Tools/ReferenceLab/sound_lifecycle.py','--route',ROOT/'Configuration/replays/arcade.json','--baseline',ROOT/'build/validation/integration/arcade/reference/trace.jsonl')
    shutil.copyfile(ROOT/'build/audio-lifecycle/verified/report.json',ROOT/'Documentation/audio-lifecycle-acceptance.json')
    run('scripts/prepare_licenses.py')
    print('Fixed-native execution and current-game original-reference comparisons passed. Run scripts/build.sh --skip-engine to package.')
if __name__=='__main__':main()

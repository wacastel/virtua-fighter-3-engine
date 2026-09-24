#!/usr/bin/env python3
"""Compare actual reference/native picture and PCM at every authored frame."""
from pathlib import Path
import argparse, concurrent.futures, json, os, subprocess, sys
from import_assets import ROOT, sha, write_json
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--routes',nargs='+',type=Path,required=True);ap.add_argument('--output',type=Path,default=ROOT/'build/validation/integration');ap.add_argument('--jobs',type=int,default=1,help='Concurrent independent route pairs (1–3)');args=ap.parse_args()
 if not 1<=args.jobs<=3:raise ValueError('Use one to three concurrent route pairs')
 if len({p.stem for p in args.routes})!=len(args.routes):raise ValueError('Route names must be unique')
 args.output.mkdir(parents=True,exist_ok=True)
 native=ROOT/'build/native/libvf3.dylib';reference=ROOT/'build/reference/libvf3.dylib'
 identities={name:sha(path) for name,path in [('reference',reference),('native',native)]}
 evidence_paths=[Path(__file__).resolve(),ROOT/'Tools/ReferenceLab/replay.py',ROOT/'build/native/engine-build-manifest.json',ROOT/'build/assets/media-identity.json',*args.routes]
 evidence={str(p.resolve().relative_to(ROOT)):sha(p) for p in evidence_paths}
 def qualify(route):
  data=json.loads(route.read_text());frames=data['frames'];name=route.stem
  def replay(kind):
   output=args.output/name/kind;output.mkdir(parents=True,exist_ok=True)
   command=[sys.executable,str(ROOT/'Tools/ReferenceLab/replay.py'),'--library',str(native if kind=='native' else reference),'--route',str(route.resolve()),'--frames',str(frames),'--output',str(output),'--capture-every','600']
   env={**os.environ,'VF3_RTC_EPOCH':'946684800'};env.pop('VF3_FACTORY_SETTINGS',None)
   with (output/'run.log').open('w') as log:subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
   return output
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   ref,nat=list(pool.map(replay,['reference','native']))
  a=[json.loads(x) for x in (ref/'trace.jsonl').read_text().splitlines()];b=[json.loads(x) for x in (nat/'trace.jsonl').read_text().splitlines()]
  if len(a)!=frames or len(b)!=frames:raise AssertionError('Incomplete replay '+name)
  differences=[{'frame':i+1,'reference':x,'native':y} for i,(x,y) in enumerate(zip(a,b)) if x!=y]
  if differences:
   write_json(args.output/(name+'-differences.json'),differences[:30]);raise AssertionError(f'{name}: {len(differences)} frame differences; first {differences[0]}')
  report=json.loads((nat/'report.json').read_text())
  if not report['nonzeroPCMBytes']:raise AssertionError(name+': no audible-sample data produced')
  row={'route':str(route.relative_to(ROOT) if route.is_absolute() else route),'routeSHA256':sha(route),'frames':frames,'sampleFrames':report['sampleFrames'],'rgbaSHA256':report['rgbaSHA256'],'pcmSHA256':report['pcmSHA256'],'perFrameTraceSHA256':sha(nat/'trace.jsonl'),'distinctPictures':len({x['rgba'] for x in b}),'nonzeroPCMBytes':report['nonzeroPCMBytes'],'exactPictureAudioCountAgreement':True}
  print(json.dumps(row),flush=True);return row
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
  results=list(pool.map(qualify,args.routes))
 if any(sha(path)!=identities[name] for name,path in [('reference',reference),('native',native)]):raise RuntimeError('Engine changed during integration verification')
 if any(sha(ROOT/path)!=digest for path,digest in evidence.items()):raise RuntimeError('Replay input or validation source changed during integration verification')
 report={'passed':True,'evidenceInputs':evidence,'referenceLibrarySHA256':identities['reference'],'nativeLibrarySHA256':identities['native'],'nativeArchiveSHA256':sha(ROOT/'build/native/libvf3.a'),'engineManifestSHA256':sha(ROOT/'build/native/engine-build-manifest.json'),'scriptSHA256':sha(Path(__file__)),'mediaManifestSHA256':sha(ROOT/'build/assets/media-identity.json'),'clockEpoch':946684800,'routes':results,'totalFrames':sum(r['frames'] for r in results),'totalStereoFrames':sum(r['sampleFrames'] for r in results),'scope':'Every RGBA picture, stereo PCM block and block sample count on listed fresh-save routes. Independent processes share a GPU while checking, so elapsed replay time is not a live GUI performance measurement. No physical board or exhaustive gameplay claim.'}
 write_json(args.output/'report.json',report);write_json(ROOT/'Documentation/integration-acceptance.json',report)
 print('All integration routes match exactly.')
if __name__=='__main__':main()

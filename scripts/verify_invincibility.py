#!/usr/bin/env python3
"""Bounded native invincibility CPU and original-input gameplay validation."""
from pathlib import Path
import argparse, concurrent.futures, ctypes as C, hashlib, json, os, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Tools/ReferenceLab'))
from replay import png

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
def run(cmd,**kw):return subprocess.run([str(x) for x in cmd],check=True,**kw)
def fixture(out):
 from compile_ppc import verified_rom, verify_invincibility_contexts
 out=out.resolve();out.mkdir(parents=True,exist_ok=True);trace=out/'cases.tsv';trace.write_text('000104a4 7d445051\n')
 gen=out/'generated';run([sys.executable,ROOT/'scripts/compile_ppc.py','--game',ROOT/'build/media-source','--trace-only','--observations',trace,'--output',gen],stdout=subprocess.DEVNULL)
 up=ROOT/'build/upstream/supermodel/Src';source=ROOT/'Tools/ReferenceLab/invincibility_fixture.cpp';captures={}
 for kind,core in [('reference',up/'CPU/PowerPC/ppc.cpp'),('native',gen/'ppc.cpp')]:
  harness=out/(kind+'.cpp');harness.write_text(source.read_text().replace('FIXTURE_CORE',str(core)))
  cmd=['clang++','-std=c++17','-O2','-fno-strict-aliasing','-ffp-contract=off','-DSUPERMODEL_OSX','-I'+str(up),'-I'+str(up/'OSD/SDL'),harness,up/'BlockFile.cpp','-Wl,-dead_strip','-o',out/kind]
  if kind=='native':cmd.insert(1,'-DFIXTURE_NATIVE')
  run(cmd)
  with (out/(kind+'.bin')).open('wb') as f:run([out/kind],stdout=f)
  captures[kind]=sha(out/(kind+'.bin'))
 assert captures['reference']==captures['native'], 'Full CPU fixture mismatch'
 # Authentication must reject even one changed source byte; original files stay intact.
 rom,_=verified_rom(ROOT/'build/media-source');bad=bytearray(rom);bad[0x710000+0x104a4]^=1
 try:verify_invincibility_contexts(bytes(bad))
 except ValueError:pass
 else:raise AssertionError('Changed source accepted')
 report={'passed':True,'cases':26,'registerAndFlagSeeds':8,'comparisons':208,'positiveCases':4,'negativeCases':22,'changedInstructionAndUnknownAddressRejections':2,'sourceIdentityNegativeControls':1,'fixtureSHA256':sha(source),'generatorSHA256':sha(ROOT/'scripts/compile_ppc.py'),'configurationSHA256':sha(ROOT/'Configuration/invincibility-ppc.json'),'verifierSHA256':sha(Path(__file__)),'generatedFixtureSHA256':sha(gen/'ppc.cpp'),'harnessSHA256':{k:sha(out/(k+'.cpp')) for k in captures},'binarySHA256':{k:sha(out/k) for k in captures},'resultSHA256':captures['native'],'scope':'Full GPR/FPR/CR/control/cycle state and no bus writes, compared with independently compiled original subf. using literal zero damage for four prescribed positive cases and unchanged damage for 22 negative cases. OFF performs no added reads; ON reads only explicitly whitelisted ordinary RAM.'}
 write(out/'report.json',report);write(ROOT/'Documentation/invincibility-fixture-acceptance.json',report)

def capture(args):
 route=json.loads(args.route.read_text());out=args.output;out.mkdir(parents=True,exist_ok=True);os.environ['VF3_RTC_EPOCH']='946684800';lib=C.CDLL(str(args.library.resolve()));p=C.c_void_p
 specs={'create':([C.c_char_p,C.c_char_p],p),'destroy':([p],None),'step':([p,C.c_uint32,C.c_uint32],C.c_int),'error':([p],C.c_char_p),'pixels':([p],p),'audio':([p],p),'audio_count':([p],C.c_int),'set_invincible':([p,C.c_int],C.c_int),'get_invincible':([p],C.c_int),'diagnostic_read32':([p,C.c_uint32],C.c_uint32)}
 for n,(a,r) in specs.items():
  if n=='diagnostic_read32' and not hasattr(lib,'vf3_'+n):continue
  f=getattr(lib,'vf3_'+n);f.argtypes=a;f.restype=r
 with tempfile.TemporaryDirectory(prefix='vf3-invincibility-') as saves:
  ctx=lib.vf3_create(os.fsencode(ROOT/'build/assets'),os.fsencode(saves));assert ctx,lib.vf3_error(None)
  assert lib.vf3_get_invincible(ctx)==0
  reference=hasattr(lib,'vf3_reference_probe_marker')
  if reference:
   assert lib.vf3_set_invincible(ctx,1)==0 and lib.vf3_get_invincible(ctx)==0
  diagnostics=hasattr(lib,'vf3_diagnostic_read32')
  try:
   with (out/'frames.jsonl').open('w') as f:
    for frame in range(route['frames']):
     state={'player1':0,'player2':0,'invincible':None}
     for event in route['events']:
      if event['start']<=frame<event['end']:state.update({k:v for k,v in event.items() if k in state})
     if state['invincible'] is not None:
      assert type(state['invincible']) is bool
      assert lib.vf3_set_invincible(ctx,0 if args.assist_off else int(state['invincible']))==1,lib.vf3_error(ctx)
     assert lib.vf3_step(ctx,state['player1'],state['player2'])==1,lib.vf3_error(ctx)
     rgba=C.string_at(lib.vf3_pixels(ctx),496*384*4);n=lib.vf3_audio_count(ctx);pcm=C.string_at(lib.vf3_audio(ctx),n*4);read=lambda a:lib.vf3_diagnostic_read32(ctx,a) if diagnostics else 0
     r={'frame':frame+1,'rgba':hashlib.sha256(rgba).hexdigest(),'pcm':hashlib.sha256(pcm).hexdigest(),'audioFrames':n,'invincible':bool(lib.vf3_get_invincible(ctx)), 'state':{'phase':f'{read(0x102008):08x}','owner':(read(0x106028)>>16)&255,'pointer1':read(0x102108),'pointer2':read(0x10210c),'health':[read(0x1087d4)&65535,read(0x10a7d4)&65535],'actorFlags':[read(0x108780),read(0x10a780)],'timer':read(0x106014),'ending':read(0x106018)}}
     f.write(json.dumps(r,separators=(',',':'))+'\n')
     if frame+1 in route.get('captures',[]) or frame==route['frames']-1:png(out/f'frame-{frame+1:06d}.png',rgba)
   write(out/'report.json',{'passed':True,'librarySHA256':sha(args.library),'routeSHA256':sha(args.route),'frames':route['frames'],'assistOff':args.assist_off,'referenceEnableRejected':reference,'traceSHA256':sha(out/'frames.jsonl')})
  finally:lib.vf3_destroy(ctx)

def input_hashes():
 paths=[ROOT/'Sources/Bridge/vf3.cpp',ROOT/'Sources/Bridge/vf3.h',ROOT/'scripts/compile_ppc.py',ROOT/'scripts/build_engine.py',Path(__file__),ROOT/'Configuration/invincibility-ppc.json',ROOT/'Documentation/invincibility-fixture-acceptance.json',ROOT/'Documentation/invincibility-source-acceptance.json',ROOT/'build/generated/ppc/translation-manifest.json']
 paths += [ROOT/'build'/kind/name for kind in ['native','native-diagnostic','reference'] for name in ['libvf3.dylib','engine-build-manifest.json']]
 paths += sorted((ROOT/'Configuration/replays').glob('invincibility-*.json'))
 return {str(p.relative_to(ROOT)):sha(p) for p in paths}

def build_equivalence():
 ship=json.loads((ROOT/'build/native/engine-build-manifest.json').read_text());diag=json.loads((ROOT/'build/native-diagnostic/engine-build-manifest.json').read_text())
 assert ship['shippingNative'] and not ship['diagnostics'] and not diag['shippingNative'] and diag['diagnostics']
 for key in ['compiledSources','generatedSources','cpuReplacements','sources','headersSHA256','compiler','target','configuration']:
  assert ship[key]==diag[key], 'Shipping/diagnostic build mismatch: '+key
 return {'shippingManifestSHA256':sha(ROOT/'build/native/engine-build-manifest.json'),'diagnosticManifestSHA256':sha(ROOT/'build/native-diagnostic/engine-build-manifest.json'),'sameCompiledSources':True,'sameGeneratedSources':True}

def gameplay(out,jobs):
 out.mkdir(parents=True,exist_ok=True);locked=input_hashes();write(out/'inputs.json',locked);build_equivalence();routes=sorted((ROOT/'Configuration/replays').glob('invincibility-*.json'))
 libraries={'reference':ROOT/'build/reference/libvf3.dylib','off':ROOT/'build/native-diagnostic/libvf3.dylib','on':ROOT/'build/native-diagnostic/libvf3.dylib','shipping':ROOT/'build/native/libvf3.dylib'}
 tasks=[(route,mode) for route in routes for mode in ['reference','off','on']]
 tasks.append((ROOT/'Configuration/replays/invincibility-versus.json','shipping'))
 def work(task):
  route,mode=task;dest=out/route.stem/mode
  cmd=[sys.executable,Path(__file__),'--capture','--route',route,'--library',libraries[mode],'--output',dest]
  if mode in ['reference','off']:cmd.append('--assist-off')
  dest.mkdir(parents=True,exist_ok=True)
  with (dest/'process.log').open('w') as log:run(cmd,stdout=log,stderr=subprocess.STDOUT)
  return route.stem,mode
 with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
  for name,mode in pool.map(work,tasks):print(name,mode,'completed',flush=True)
 assert input_hashes()==locked,'Inputs changed during gameplay verification'
 analyze(out)

def analyze(out):
 assert input_hashes()==json.loads((out/'inputs.json').read_text()),'Acceptance inputs changed'
 equivalence=build_equivalence()
 results={};active=lambda r:r['state']['phase']=='07090709'
 def rows(path):return [json.loads(s) for s in path.read_text().splitlines()]
 def drops(rs,p,on=None):return [b['frame'] for a,b in zip(rs,rs[1:]) if active(a) and active(b) and a['state']['health'][p]>b['state']['health'][p] and (on is None or a['invincible']==b['invincible']==on)]
 for route in sorted((ROOT/'Configuration/replays').glob('invincibility-*.json')):
  name=route.stem;ref,off,on=[rows(out/name/m/'frames.jsonl') for m in ['reference','off','on']]
  for mode in ['reference','off','on']:
   meta=json.loads((out/name/mode/'report.json').read_text())
   library=ROOT/('build/reference/libvf3.dylib' if mode=='reference' else 'build/native-diagnostic/libvf3.dylib')
   assert meta['librarySHA256']==sha(library) and meta['routeSHA256']==sha(route)
   assert meta['traceSHA256']==sha(out/name/mode/'frames.jsonl') and meta['frames']==json.loads(route.read_text())['frames']
  assert len(ref)==len(off)==len(on)==json.loads(route.read_text())['frames'],name+' truncated trace'
  assert json.loads((out/name/'reference/report.json').read_text())['referenceEnableRejected']
  assert ref==off,name+' OFF/reference mismatch'
  enabled=[r for r in on if r['invincible'] and active(r)]
  assert enabled or (name.endswith('attract') and any(r['invincible'] for r in on)),name+' no ON interval'
  report={'frames':len(ref),'originalOFFExactFrameComparisons':len(ref),'p1DropsReference':drops(ref,0),'p1DropsON':drops(on,0,True),'p2DropsON':drops(on,1,True),'traces':{m:sha(out/name/m/'frames.jsonl') for m in ['reference','off','on']},'routeSHA256':sha(route)}
  if name.endswith(('attract','p2','timeout','ringout')):
   assert all({k:v for k,v in a.items() if k!='invincible'}=={k:v for k,v in b.items() if k!='invincible'} for a,b in zip(ref,on)),name+' should remain original'
  else:
   assert drops(ref,0),name+' reference must take damage'
   assert not drops(on,0,True),name+' protected incoming damage'
   assert drops(on,1,True),name+' opponent should take damage'
   enable=next(i for i,r in enumerate(on) if r['invincible']);assert on[enable]['state']['health']==on[enable-1]['state']['health'],name+' healed on enable'
   assert on[enable]['state']['health'][0]>0 and on[enable]['state']['health'][0]<201,name+' enable after damage'
   disable=next(r['frame'] for a,r in zip(on,on[1:]) if a['invincible'] and not r['invincible'])
   assert any(f>disable for f in drops(on,0,False)),name+' OFF must restore damage after disabling'
   report['enableHealth']=on[enable]['state']['health'][0];report['disabledFrame']=disable;report['damageResumedFrames']=[f for f in drops(on,0,False) if f>disable]
  if name.endswith(('timeout','ringout')):
   reason=2 if name.endswith('timeout') else 1
   end=next((i for i,r in enumerate(on) if r['state']['ending']>>24==reason),None)
   assert end is not None and on[end]['invincible'] and on[end-1]['state']['health'][0]>0,'Original non-damage ending not reached while ON'
   if reason==2:assert on[end]['state']['timer']==0 and min(on[end]['state']['health'])>0
   else:assert on[end]['state']['health'][0]==0,'Original ringout zero-health bookkeeping changed'
   report['originalEnding']={'reason':'timeout' if reason==2 else 'ringout','frame':on[end]['frame'],'healthBefore':on[end-1]['state']['health'],'healthAfter':on[end]['state']['health'],'timer':on[end]['state']['timer'],'invincible':True}
   capture=3900 if reason==2 else 2700
   report['endingCaptureSHA256']=sha(out/name/'on'/f'frame-{capture:06d}.png')
  results[name]=report
 shipping=rows(out/'invincibility-versus/shipping/frames.jsonl');diagnostic=rows(out/'invincibility-versus/on/frames.jsonl')
 sm=json.loads((out/'invincibility-versus/shipping/report.json').read_text())
 assert sm['librarySHA256']==sha(ROOT/'build/native/libvf3.dylib') and sm['routeSHA256']==sha(ROOT/'Configuration/replays/invincibility-versus.json')
 assert sm['traceSHA256']==sha(out/'invincibility-versus/shipping/frames.jsonl') and len(shipping)==len(diagnostic)==sm['frames']
 assert all({k:v for k,v in a.items() if k!='state'}=={k:v for k,v in b.items() if k!='state'} for a,b in zip(shipping,diagnostic)), 'Shipping/diagnostic ON mismatch'
 equivalence['shippingONFrameComparisons']=len(shipping);equivalence['shippingONTraceSHA256']=sm['traceSHA256']
 inputs=[ROOT/'Sources/Bridge/vf3.cpp',ROOT/'Sources/Bridge/vf3.h',ROOT/'scripts/compile_ppc.py',ROOT/'scripts/build_engine.py',Path(__file__),ROOT/'Configuration/invincibility-ppc.json',ROOT/'Documentation/invincibility-fixture-acceptance.json',ROOT/'Documentation/invincibility-source-acceptance.json',ROOT/'build/generated/ppc/translation-manifest.json',ROOT/'build/native/libvf3.dylib',ROOT/'build/native/engine-build-manifest.json',ROOT/'build/native-diagnostic/libvf3.dylib',ROOT/'build/native-diagnostic/engine-build-manifest.json',ROOT/'build/reference/libvf3.dylib',ROOT/'build/reference/engine-build-manifest.json']
 report={'passed':True,'routes':results,'shippingDiagnosticEquivalence':equivalence,'lockedInputs':input_hashes(),'provenance':{str(p.relative_to(ROOT)):sha(p) for p in inputs},'scope':'Fresh saves and ordinary inputs only. Exact per-frame original/reference to OFF-native RGBA/PCM/count/state equality; bounded native ON ownership/damage and non-health-ending semantics. No physical hardware or exhaustive move coverage claim.'}
 write(out/'acceptance.json',report);write(ROOT/'Documentation/invincibility-acceptance.json',report)

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,default=ROOT/'build/verification/invincibility');ap.add_argument('--fixture',action='store_true');ap.add_argument('--capture',action='store_true');ap.add_argument('--analyze',action='store_true');ap.add_argument('--assist-off',action='store_true');ap.add_argument('--library',type=Path);ap.add_argument('--route',type=Path);ap.add_argument('--jobs',type=int,default=2);a=ap.parse_args()
 if a.fixture:fixture(a.output)
 elif a.capture:capture(a)
 elif a.analyze:analyze(a.output)
 else:gameplay(a.output,a.jobs)
if __name__=='__main__':main()

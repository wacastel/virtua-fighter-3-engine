#!/usr/bin/env python3
"""Run a bounded, fresh-save serial game replay through the real C ABI."""
from pathlib import Path
import argparse, ctypes as C, hashlib, json, os, struct, sys, tempfile, time, zlib
ROOT=Path(__file__).resolve().parents[2]
def png(path,data):
 def chunk(k,b): return struct.pack('>I',len(b))+k+b+struct.pack('>I',zlib.crc32(k+b))
 raw=b''.join(b'\0'+data[y*496*4:(y+1)*496*4] for y in range(384))
 path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',496,384,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--library',type=Path,default=ROOT/'build/observer/libvf3.dylib');ap.add_argument('--frames',type=int,default=1200);ap.add_argument('--route',type=Path);ap.add_argument('--output',type=Path,default=ROOT/'build/replay');ap.add_argument('--saves',type=Path);ap.add_argument('--capture-every',type=int,default=300);args=ap.parse_args()
 args.output.mkdir(parents=True,exist_ok=True)
 os.environ.setdefault('VF3_RTC_EPOCH','946684800')
 library_sha=hashlib.sha256(args.library.read_bytes()).hexdigest()
 lib=C.CDLL(str(args.library));ptr=C.c_void_p
 signatures={'create':([C.c_char_p,C.c_char_p],ptr),'destroy':([ptr],None),'step':([ptr,C.c_uint32,C.c_uint32],C.c_int),'error':([ptr],C.c_char_p),'fault_code':([ptr],C.c_uint32),'pixels':([ptr],ptr),'audio':([ptr],ptr),'audio_count':([ptr],C.c_int)}
 for name,(inputs,result) in signatures.items():f=getattr(lib,'vf3_'+name);f.argtypes=inputs;f.restype=result
 route=json.loads(args.route.read_text()) if args.route else {'events':[]}
 temp=tempfile.TemporaryDirectory(prefix='vf3-replay-');saves=args.saves or Path(temp.name)
 context=lib.vf3_create(os.fsencode(ROOT/'build/assets'),os.fsencode(saves))
 if not context:raise RuntimeError(lib.vf3_error(None).decode())
 pictures=hashlib.sha256();audio=hashlib.sha256();samples=0;nonzero=0;start=time.monotonic()
 try:
  with (args.output/'trace.jsonl').open('w') as trace:
   for frame in range(args.frames):
    state=dict(player1=0,player2=0)
    for event in route['events']:
     if event['start']<=frame<event['end']:state.update({k:v for k,v in event.items() if k in state})
    if lib.vf3_step(context,state['player1'],state['player2'])!=1:raise RuntimeError(f'Frame {frame}: '+lib.vf3_error(context).decode())
    rgba=C.string_at(lib.vf3_pixels(context),496*384*4);n=lib.vf3_audio_count(context);pcm=C.string_at(lib.vf3_audio(context),n*4)
    pictures.update(rgba);audio.update(pcm);samples+=n;nonzero+=sum(b!=0 for b in pcm)
    trace.write(json.dumps({'frame':frame+1,'rgba':hashlib.sha256(rgba).hexdigest(),'pcm':hashlib.sha256(pcm).hexdigest(),'audioFrames':n})+'\n')
    if frame==0 or (frame+1)%args.capture_every==0 or frame==args.frames-1:
     png(args.output/f'frame-{frame+1:06d}.png',rgba)
     pc=''
     if hasattr(lib,'vf3_diagnostic_pc'):
      lib.vf3_diagnostic_pc.argtypes=[ptr];lib.vf3_diagnostic_pc.restype=C.c_uint32
      pc=f', PPC={lib.vf3_diagnostic_pc(context):08x}'
      lib.vf3_diagnostic_gpr.argtypes=[ptr,C.c_uint32];lib.vf3_diagnostic_gpr.restype=C.c_uint32
      lib.vf3_diagnostic_read32.argtypes=[ptr,C.c_uint32];lib.vf3_diagnostic_read32.restype=C.c_uint32
      pc+=f', r3={lib.vf3_diagnostic_gpr(context,3):08x}'
     print(f'Frame {frame+1}/{args.frames}: {(frame+1)/(time.monotonic()-start):.1f} fps, {samples} stereo samples'+pc,file=sys.stderr,flush=True)
  result={'passed':True,'frames':args.frames,'rgbaSHA256':pictures.hexdigest(),'pcmSHA256':audio.hexdigest(),'sampleFrames':samples,'nonzeroPCMBytes':nonzero,'elapsedSeconds':time.monotonic()-start,'librarySHA256':library_sha,'clockEpoch':os.environ['VF3_RTC_EPOCH'],'route':route}
  (args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
 finally:lib.vf3_destroy(context);temp.cleanup()
if __name__=='__main__':main()

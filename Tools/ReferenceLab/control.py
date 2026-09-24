#!/usr/bin/env python3
"""Interactive laboratory route authoring through ordinary game controls."""
from pathlib import Path
import argparse, ctypes as C, json, os, sys
from replay import ROOT, png
ap=argparse.ArgumentParser();ap.add_argument('--library',type=Path,default=ROOT/'build/observer/libvf3.dylib');ap.add_argument('--saves',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
lib=C.CDLL(str(args.library.resolve()));ptr=C.c_void_p
for name,inputs,result in [('create',[C.c_char_p,C.c_char_p],ptr),('destroy',[ptr],None),('step',[ptr,C.c_uint32,C.c_uint32],C.c_int),('error',[ptr],C.c_char_p),('pixels',[ptr],ptr)]:
 f=getattr(lib,'vf3_'+name);f.argtypes=inputs;f.restype=result
ctx=lib.vf3_create(os.fsencode(ROOT/'build/assets'),os.fsencode(args.saves.resolve()))
if not ctx:raise RuntimeError(lib.vf3_error(None).decode())
frame=0;events=[]
print('READY',flush=True)
try:
 for line in sys.stdin:
  command=json.loads(line)
  if command.get('quit'):break
  count=command.get('frames',1)
  state={key:command.get(key,0) for key in ['player1','player2']}
  events.append(dict(start=frame,end=frame+count,**{k:v for k,v in state.items() if v}))
  for _ in range(count):
   if lib.vf3_step(ctx,state['player1'],state['player2'])!=1:raise RuntimeError(lib.vf3_error(ctx).decode())
   frame+=1
  path=args.output/f'frame-{frame:06d}.png';png(path,C.string_at(lib.vf3_pixels(ctx),496*384*4))
  (args.output/'route.json').write_text(json.dumps({'frames':frame,'events':events},indent=2)+'\n')
  print(str(path),flush=True)
finally:lib.vf3_destroy(ctx)

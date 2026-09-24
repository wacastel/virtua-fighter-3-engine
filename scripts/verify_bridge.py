#!/usr/bin/env python3
"""Exercise the actual native bridge's lifecycle, media and input boundaries."""
from pathlib import Path
import ctypes as C, hashlib, json, os, tempfile
from import_assets import ROOT, sha, write_json
def main():
 libpath=ROOT/'build/native/libvf3.dylib';lib=C.CDLL(str(libpath));ptr=C.c_void_p
 definitions={'create':([C.c_char_p,C.c_char_p],ptr),'destroy':([ptr],None),'step':([ptr,C.c_uint32,C.c_uint32],C.c_int),'frame_number':([ptr],C.c_uint64),'fault_code':([ptr],C.c_uint32),'audio_count':([ptr],C.c_int),'error':([ptr],C.c_char_p)}
 for name,(args,result) in definitions.items():f=getattr(lib,'vf3_'+name);f.argtypes=args;f.restype=result
 checks=[]
 def check(name,value):
  if not value:raise AssertionError(name)
  checks.append(name)
 os.environ['VF3_RTC_EPOCH']='946684800'
 with tempfile.TemporaryDirectory(prefix='vf3-boundary-') as work:
  directory=Path(work);saves=directory/'saves'
  check('null asset path rejected',not lib.vf3_create(None,os.fsencode(saves)))
  check('absent media rejected',not lib.vf3_create(os.fsencode(directory),os.fsencode(saves)))
  (directory/'vf3.zip').write_bytes(b'not canonical media')
  (directory/'Games.xml').write_bytes((ROOT/'build/assets/Games.xml').read_bytes())
  check('changed media rejected',not lib.vf3_create(os.fsencode(directory),os.fsencode(saves)))
  context=lib.vf3_create(os.fsencode(ROOT/'build/assets'),os.fsencode(saves));check('canonical media accepted',bool(context))
  try:
   check('second context rejected',not lib.vf3_create(os.fsencode(ROOT/'build/assets'),os.fsencode(directory/'other')))
   for name,p1,p2 in [('opposed vertical P1',3,0),('opposed horizontal P1',12,0),('opposed vertical P2',0,3),('opposed horizontal P2',0,12),('unexposed test',1<<16,0),('unexposed service',1<<17,0),('unknown P1 bit',1<<31,0),('unknown P2 bit',0,1<<31)]:
    check(name+' rejected',lib.vf3_step(context,p1,p2)==0)
    check(name+' does not advance',lib.vf3_frame_number(context)==0)
   check('valid recovery step',lib.vf3_step(context,16,32)==1)
   check('one frame',lib.vf3_frame_number(context)==1)
   check('735 stereo frames',lib.vf3_audio_count(context)==735)
   check('no fault',lib.vf3_fault_code(context)==0)
   for _ in range(2399):
    if lib.vf3_step(context,0,0)!=1:raise RuntimeError(lib.vf3_error(context).decode())
   check('first session reaches 2400 frames',lib.vf3_frame_number(context)==2400)
  finally:lib.vf3_destroy(context)
  check('cabinet state saved',(saves/'vf3.nv').is_file())
  context=lib.vf3_create(os.fsencode(ROOT/'build/assets'),os.fsencode(saves));check('recreate existing save',bool(context))
  if context:
   try:
    check('cold restart frame zero',lib.vf3_frame_number(context)==0)
    for _ in range(2400):
     if lib.vf3_step(context,0,0)!=1:raise RuntimeError(lib.vf3_error(context).decode())
    check('cold restart plays 2400 frames',lib.vf3_frame_number(context)==2400)
    check('cold restart sound ready',lib.vf3_audio_count(context)==735)
   finally:lib.vf3_destroy(context)
 report={'passed':True,'checks':checks,'checkCount':len(checks),'librarySHA256':sha(libpath),'scriptSHA256':sha(Path(__file__)),'scope':'Real fixed-native lifecycle and boundary checks; no stub, no gameplay or physical-controller claim.'}
 write_json(ROOT/'Documentation/bridge-acceptance.json',report);print(json.dumps({'passed':True,'checks':len(checks)}))
if __name__=='__main__':main()

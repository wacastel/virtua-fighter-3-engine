#!/usr/bin/env python3
"""Build isolated original-CPU reference or fixed-native Model 3 hardware."""
from pathlib import Path
import argparse, concurrent.futures, hashlib, json, re, shutil, subprocess
from import_assets import ROOT, sha, write_json
from prepare_source import verify_source
UPSTREAM=ROOT/'build/upstream/supermodel'
REVISION='24d2ffcfc7f14229337f05f4920fe26b56633d9d'
def run(args,**kwargs): return subprocess.run([str(a) for a in args],check=True,**kwargs)
def put(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists() or path.read_text()!=text:path.write_text(text)
def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--kind',choices=['reference','observer','native'],default='reference');ap.add_argument('--jobs',type=int,default=8);ap.add_argument('--output',type=Path);args=ap.parse_args()
 kind=args.kind; out=args.output.resolve() if args.output else ROOT/'build'/kind;out.mkdir(parents=True,exist_ok=True)
 upstream_report=verify_source()
 derived=ROOT/'build/derived'/kind; derived.mkdir(parents=True,exist_ok=True)
 musashi=ROOT/'build/derived/musashi';musashi.mkdir(parents=True,exist_ok=True)
 if not (musashi/'m68kops.c').exists():
  run(['clang','-O2',UPSTREAM/'Src/CPU/68K/Musashi/m68kmake.c','-o',musashi/'m68kmake'])
  run([musashi/'m68kmake',musashi,UPSTREAM/'Src/CPU/68K/Musashi/m68k_in.c'],stdout=subprocess.DEVNULL)
 rules=(UPSTREAM/'Makefiles/Rules.inc').read_text().split('SRC_FILES =',1)[1].split('ifeq',1)[0]
 sources=re.findall(r'Src/[A-Za-z0-9_./]+\.cpp',rules)
 sources=[s for s in sources if not any(x in s for x in ['OSD/SDL/','Network/','Pkgs/imgui/','PPCDisasm.cpp'])]
 sources += ['Src/CPU/68K/Musashi/m68kcpu.c']
 def resolve(s):
  p=UPSTREAM/s
  if p.exists():return p
  if p.with_suffix('.c').exists():return p.with_suffix('.c')
  matches=list((UPSTREAM/'Src').rglob(p.name))
  if len(matches)!=1:raise RuntimeError('Cannot resolve upstream source '+s)
  return matches[0]
 sources=[resolve(s) for s in sources]+list(musashi.glob('m68kop*.c'))
 # Fixed configuration removes detached cabinet networking and its SDL dependency.
 m=(UPSTREAM/'Src/Model3/Model3.cpp').read_text()
 m=m.replace('#include "Network/NetBoard.h"','#include "DetachedNetwork.h"').replace('#include "Network/SimNetBoard.h"','')
 m=re.sub(r'  if \(m_config\["SimulateNet"\].ValueAs<bool>\(\)\)\s+NetBoard = new CSimNetBoard\(m_config\);\s+else\s+NetBoard = new CNetBoard\(m_config\);','  NetBoard = new DetachedNetwork();',m)
 m=re.sub(r'SDL_ShowSimpleMessageBox\(SDL_MESSAGEBOX_ERROR, "Info", "([^"]+)", NULL\);',r'ErrorLog("\1");',m)
 put(derived/'Model3.cpp',m)
 replacements={'Src/Model3/Model3.cpp':derived/'Model3.cpp'}
 # Sample the real clock once on boot, then advance at game-frame boundaries.
 # An explicit epoch makes independently paced replay processes reproducible.
 rtc=(UPSTREAM/'Src/Model3/RTC72421.cpp').read_text()
 rtc='#include <ctime>\nextern std::time_t vf3_clock();\n'+rtc.replace('\ttime(&currentTime);','\tcurrentTime = vf3_clock();').replace('localtime(&currentTime)','gmtime(&currentTime)')
 put(derived/'RTC72421.cpp',rtc);replacements['Src/Model3/RTC72421.cpp']=derived/'RTC72421.cpp'
 # A new board must start with the original process's zero cycle debt. The
 # upstream function-static value otherwise leaks across destroy/create.
 scsp=(UPSTREAM/'Src/Sound/SCSP.cpp').read_text()
 local='\tstatic int lastdiff = 0;\n'
 init='Result SCSP_Init(const Util::Config::Node &config, int n)\n{\n'
 assert scsp.count(local)==1 and scsp.count(init)==1
 scsp=scsp.replace(local,'').replace('lastdiff','vf3_sound_cycle_remainder')
 scsp=scsp.replace(init,'static int vf3_sound_cycle_remainder = 0;\n\n'+init+'\tvf3_sound_cycle_remainder = 0;\n')
 put(derived/'SCSP.cpp',scsp);replacements['Src/Sound/SCSP.cpp']=derived/'SCSP.cpp'
 # Upstream checks the default window framebuffer after unbinding its depth
 # target. A surfaceless CGL context must check the actual depth target.
 fbo=(UPSTREAM/'Src/Graphics/New3D/R3DFrameBuffers.cpp').read_text()
 old='\tglBindFramebuffer(GL_FRAMEBUFFER, 0);\n\n\t// check setup was successful\n\tauto fboStatus = glCheckFramebufferStatus(GL_FRAMEBUFFER);'
 assert fbo.count(old)==1
 fbo=fbo.replace(old,'\tglDrawBuffer(GL_NONE);\n\tglReadBuffer(GL_NONE);\n\tauto fboStatus = glCheckFramebufferStatus(GL_FRAMEBUFFER);\n\tglBindFramebuffer(GL_FRAMEBUFFER, 0);')
 put(derived/'R3DFrameBuffers.cpp',fbo);replacements['Src/Graphics/New3D/R3DFrameBuffers.cpp']=derived/'R3DFrameBuffers.cpp'
 # Redirect default-window compositing to the native offscreen framebuffer.
 for relative in ['Src/Graphics/New3D/R3DFrameBuffers.cpp','Src/Graphics/New3D/New3D.cpp','Src/Graphics/Render2D.cpp']:
  original=replacements.get(relative,UPSTREAM/relative)
  render=original.read_text()
  render='extern unsigned vf3_default_framebuffer();\n'+render.replace('glBindFramebuffer(GL_FRAMEBUFFER, 0);','glBindFramebuffer(GL_FRAMEBUFFER, vf3_default_framebuffer());').replace('glDrawBuffer(GL_BACK);','glDrawBuffer(GL_COLOR_ATTACHMENT0);')
  target=derived/Path(relative).name;put(target,render);replacements[relative]=target
 for name,board in [('SoundBoard.cpp',0),('DSB.cpp',1)]:
  text=(UPSTREAM/'Src/Model3'/name).read_text()
  text='extern "C" { extern unsigned vf3_m68k_board; }\n'+text.replace('M68KSetContext(&M68K);',f'vf3_m68k_board={board}; M68KSetContext(&M68K);')
  put(derived/name,text);replacements['Src/Model3/'+name]=derived/name
 if kind=='observer':
  ppc=ROOT/'build/generated/ppc/ppc-observer.cpp'
  if ppc.exists():replacements['Src/CPU/PowerPC/ppc.cpp']=ppc
  cpu=(UPSTREAM/'Src/CPU/68K/Musashi/m68kcpu.c').read_text()
  cpu='#include "sound_observe.h"\n'+cpu.replace('REG_IR = m68ki_read_imm_16();','vf3_sound_observe68k(vf3_m68k_board, REG_PC, M68KFetch16);\n\t\t\tREG_IR = m68ki_read_imm_16();')
  put(derived/'m68kcpu.c',cpu);replacements['Src/CPU/68K/Musashi/m68kcpu.c']=derived/'m68kcpu.c'
  dsp=(UPSTREAM/'Src/Sound/SCSPDSP.cpp').read_text()
  dsp='#include "sound_observe.h"\n'+dsp.replace('if (DSP->Stopped)\n\t\treturn;','if (DSP->Stopped)\n\t\treturn;\n vf3_sound_observe_dsp(DSP->MPRO);')
  put(derived/'SCSPDSP.cpp',dsp);replacements['Src/Sound/SCSPDSP.cpp']=derived/'SCSPDSP.cpp'
  sources.append(ROOT/'Tools/ReferenceLab/sound_observe.cpp')
 if kind=='native':
  replacements.update({'Src/CPU/PowerPC/ppc.cpp':ROOT/'build/generated/ppc/ppc.cpp','Src/CPU/Z80/Z80.cpp':ROOT/'build/generated/z80/Z80.cpp','Src/Sound/SCSPDSP.cpp':ROOT/'build/generated/sound/SCSPDSP.cpp'})
  sources=[p for p in sources if not p.is_relative_to(musashi) and p!=UPSTREAM/'Src/CPU/68K/Musashi/m68kcpu.c']
  sources+=sorted((ROOT/'build/generated/sound/musashi').glob('*.c'))
  if not sources or not (ROOT/'build/generated/sound/musashi/m68kcpu.c').exists():raise RuntimeError('Fixed sound CPU missing')
 sources=[replacements.get(str(p.relative_to(UPSTREAM)),p) if p.is_relative_to(UPSTREAM) else p for p in sources]
 sources += [ROOT/'Sources/Bridge/Platform.cpp',ROOT/'Sources/Bridge/vf3.cpp']
 # Same hardware configuration and platform for reference and product.
 main=(UPSTREAM/'Src/OSD/SDL/Main.cpp').read_text(); config=main.split('Util::Config::Node DefaultConfig()',1)[1].split('\nstatic ',1)[0]
 end=config.index('//\n  // Input sensitivity')
 config=config[:end]+'return config;\n}\n'
 config=config.replace('s_gameXMLFilePath','std::string("Games.xml")')
 config=config.replace('"MultiThreaded", true','"MultiThreaded", false').replace('"GPUMultiThreaded", true','"GPUMultiThreaded", false')
 put(derived/'DefaultConfig.h','inline Util::Config::Node DefaultConfig()'+config)
 inc=[derived,ROOT/'Sources/Bridge',ROOT/'build/generated',ROOT/'Tools/ReferenceLab',musashi,UPSTREAM/'Src/CPU/68K/Musashi',UPSTREAM/'Src/Pkgs']
 if kind=='native':inc.insert(0,ROOT/'build/generated/sound/musashi')
 inc += sorted(set(p.parent for p in (UPSTREAM/'Src').rglob('*') if p.suffix in ['.h','.cpp']))
 flags=['-O2','-arch','arm64','-mmacosx-version-min=14.0','-fexceptions','-fno-strict-aliasing','-ffp-contract=off','-DGLEW_STATIC','-DSUPERMODEL_OSX','-Wno-deprecated-declarations','-Wno-unused-result','-Wno-register','-Wno-incompatible-pointer-types-discards-qualifiers']+['-I'+str(p) for p in inc]
 if kind!='native':flags+=['-DVF3_REFERENCE']
 headers=sorted(set((UPSTREAM/'Src').rglob('*.h'))|set((ROOT/'Sources/Bridge').glob('*.h'))|set((ROOT/'build/generated').rglob('*.h'))|set(derived.glob('*.h'))|set(musashi.glob('*.h')))
 header_digest=hashlib.sha256(''.join(str(p.relative_to(ROOT))+sha(p) for p in headers).encode()).hexdigest()
 compiler=subprocess.check_output(['clang','--version'],text=True).strip()
 objectdir=out/'objects';objectdir.mkdir(exist_ok=True)
 def compile(p):
  obj=objectdir/(p.stem+'-'+hashlib.sha256(str(p).encode()).hexdigest()[:8]+'.o')
  command=['clang++' if p.suffix!='.c' else 'clang']+flags+(['-std=c++17'] if p.suffix!='.c' else ['-std=c11','-DINLINE=static inline'])+['-c',str(p),'-o',str(obj)]
  signature=hashlib.sha256((json.dumps(command)+sha(p)+header_digest+compiler).encode()).hexdigest()
  stamp=obj.with_suffix('.sha256')
  if not obj.exists() or not stamp.exists() or stamp.read_text()!=signature:
   result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
   if result.returncode:raise RuntimeError(str(p)+'\n'+result.stdout[-10000:])
   stamp.write_text(signature)
  return obj
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:objects=list(pool.map(compile,sources))
 archive=out/'libvf3.a';run(['libtool','-static','-o',archive]+objects,stdout=subprocess.DEVNULL)
 run(['clang++','-dynamiclib','-arch','arm64','-mmacosx-version-min=14.0','-Wl,-dead_strip','-o',out/'libvf3.dylib']+objects+['-framework','OpenGL','-framework','Foundation','-lz'])
 fingerprints={str(p.relative_to(ROOT)):sha(p) for p in sources if not p.is_relative_to(ROOT/'build')}
 fingerprints['scripts/build_engine.py']=sha(Path(__file__))
 manifest={'kind':kind,'shippingNative':kind=='native','diagnostics':kind!='native','staticArchiveSHA256':sha(archive),'dynamicLibrarySHA256':sha(out/'libvf3.dylib'),'upstreamCommit':REVISION,'upstreamArchiveSHA256':upstream_report['archiveSHA256'],'sources':fingerprints,'compiledSources':{str(p.relative_to(ROOT)):sha(p) for p in sources},'headersSHA256':header_digest,'compiler':compiler,'target':'arm64-apple-macos14.0','configuration':'Single-threaded hardware, detached networking, offscreen OpenGL 4.1, stereo downmix, boot-sampled UTC clock'}
 if kind=='native':
  manifest['generatedSources']={str(p.relative_to(ROOT)):sha(p) for p in sources if p.is_relative_to(ROOT/'build/generated')}
  manifest['cpuReplacements']={name:{'path':str(path.relative_to(ROOT)),'sha256':sha(path)} for name,path in [('PowerPC',ROOT/'build/generated/ppc/translation-manifest.json'),('Musashi-SCSP',ROOT/'build/generated/sound/manifest.json'),('Z80',ROOT/'build/generated/z80/translation-manifest.json')]}
 write_json(out/'engine-build-manifest.json',manifest)
 print(json.dumps({'built':kind,'objects':len(objects),'archive':str(archive.relative_to(ROOT))}))
if __name__=='__main__':main()

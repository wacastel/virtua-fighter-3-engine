#!/usr/bin/env python3
"""Compare every admitted billboard Z80 start and five register/interrupt states."""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from compile_ppc import ROOT, sha
from compile_z80 import verified_rom, MAPPED_ROM_BYTES


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,default=ROOT/'build/upstream/supermodel')
    p.add_argument('--native',type=Path,default=ROOT/'build/generated/z80/Z80.cpp')
    p.add_argument('--game',type=Path,required=True)
    p.add_argument('--rom',type=Path,help='Explicit shared billboard ROM outside the game directory')
    p.add_argument('--output',type=Path,default=ROOT/'build/validation/z80')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    up=a.upstream.resolve();src=up/'Src'
    rom_path,rom=verified_rom(a.game,a.rom)
    inputs=[Path(__file__).resolve(),ROOT/'scripts/compile_z80.py',ROOT/'Tools/ReferenceLab/ppc_z80_fixture.cpp',
            a.native.resolve(),src/'CPU/Z80/Z80.cpp',src/'CPU/Z80/Z80.h',
            src/'Model3/DriveBoard/DriveBoard.cpp',src/'Model3/DriveBoard/BillBoard.cpp']
    input_hashes={str(path.relative_to(ROOT)):sha(path) for path in inputs}
    fixture=(ROOT/'Tools/ReferenceLab/ppc_z80_fixture.cpp').read_text()
    results={}
    for kind,path in [('reference',src/'CPU/Z80/Z80.cpp'),('native',a.native.resolve())]:
        code=path.read_text()
        if kind=='reference':code=code.replace('#include "Z80.h"',f'#include "{src}/CPU/Z80/Z80.h"')
        marker='  } // end while'
        if code.count(marker)!=1:raise ValueError('Pinned single-step boundary changed')
        code=code.replace(marker,'    goto HALTExit; // laboratory: exactly one instruction, including its interrupts\n'+marker)
        core=out/f'{kind}-core.cpp';core.write_text(code)
        harness=out/f'{kind}.cpp';harness.write_text(fixture.replace('FIXTURE_CORE',str(core)))
        binary=out/kind
        command=['clang++','-std=c++17','-O2','-fno-strict-aliasing','-ffp-contract=off','-DSUPERMODEL_OSX','-I'+str(src),'-I'+str(src/'OSD/SDL'),str(harness),str(src/'BlockFile.cpp'),'-Wl,-dead_strip','-o',str(binary)]
        if kind=='native':command.insert(3,'-DFIXTURE_NATIVE')
        subprocess.run(command,check=True)
        capture=out/f'{kind}.bin'
        with capture.open('wb')as f:subprocess.run([str(binary),str(rom_path)],stdout=f,check=True)
        results[kind]={'sha256':sha(capture),'bytes':capture.stat().st_size}
    if results['reference']!=results['native']:
        ref=(out/'reference.bin').read_bytes();native=(out/'native.bin').read_bytes()
        offset=next(i for i,(x,y)in enumerate(zip(ref,native))if x!=y)
        case=offset//(21*8);raise ValueError(f'Z80 mismatch PC={case//5:04x} seed={case%5} byte={offset}')
    report={'passed':True,'fixedStarts':MAPPED_ROM_BYTES,'registerInterruptStates':5,'comparisons':MAPPED_ROM_BYTES*5,
            'interruptStates':['no pending interrupt','enabled IM0 with RST 38 callback','enabled IM1','enabled IM2 with RAM vector','NMI'],
            'romSHA256':hashlib.sha256(rom).hexdigest(),'nativeSourceSHA256':sha(a.native), 'faultChecks':5, 'results':results,
            'scope':'One instruction including its immediate interrupt boundary at every admitted billboard ROM byte start; each of four changed guard bytes and unknown PC reject; no full-game or physical billboard claim.'}
    if input_hashes!={str(path.relative_to(ROOT)):sha(path) for path in inputs} or sha(rom_path)!=hashlib.sha256(rom).hexdigest():
        raise ValueError('Fixture inputs changed during verification')
    report['provenance']={'inputs':input_hashes,
        'harnesses':{kind:sha(out/f'{kind}.cpp') for kind in results},
        'binaries':{kind:sha(out/kind) for kind in results},
        'cores':{kind:sha(out/f'{kind}-core.cpp') for kind in results},
        'compiler':subprocess.check_output(['clang++','--version'],text=True).strip(),
        'flags':['-std=c++17','-O2','-fno-strict-aliasing','-ffp-contract=off','-DSUPERMODEL_OSX']}
    manifest=a.native.resolve().parent/'translation-manifest.json'
    if manifest.exists():
        product=json.loads(manifest.read_text())
        if product['outputSHA256']==sha(a.native) and product['generatorSHA256']==sha(ROOT/'scripts/compile_z80.py'):
            report['provenance']['translationManifestSHA256']=sha(manifest)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()

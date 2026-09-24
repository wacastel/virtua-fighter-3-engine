#!/usr/bin/env python3
"""Differential operation test of fixed PowerPC handlers against pinned upstream."""
from __future__ import annotations
import argparse
import json
import struct
import subprocess
from pathlib import Path
from compile_ppc import ROOT, decode_tables, handler, verified_rom, sha, observed, ram_images, verify_image_observations, static_word_at


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',type=Path,default=ROOT/'build/upstream/supermodel')
    p.add_argument('--game',type=Path,required=True)
    p.add_argument('--observations',type=Path,nargs='*',default=[])
    p.add_argument('--ram-image',action='append',default=[],metavar='ADDRESS:PATH')
    p.add_argument('--output',type=Path,default=ROOT/'build/validation/ppc')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    up=a.upstream.resolve();src=up/'Src';cpu=src/'CPU/PowerPC'
    inputs=[Path(__file__).resolve(),ROOT/'scripts/compile_ppc.py',ROOT/'Tools/ReferenceLab/ppc_operation_fixture.cpp']
    inputs += [cpu/name for name in ('ppc.cpp','ppc603.c','ppc_ops.c','ppc_ops.h','ppc.h')]
    inputs += [path.resolve() for path in a.observations]
    input_hashes={str(path.relative_to(ROOT)):sha(path) for path in inputs}
    source=(cpu/'ppc.cpp').read_text();table=decode_tables(source,(cpu/'ppc_ops.h').read_text())
    rom,_=verified_rom(a.game);words=struct.unpack('>524288I',rom[0x600000:])
    # One representative of every handler occurring in verified code/data plus
    # deterministic samples throughout the fixed words. No synthetic ROM edits.
    selected={};covered=set();seen=set()
    for i,word in enumerate(words):
        fn=handler(table,word)
        if not fn or word in seen:continue
        seen.add(word)
        if fn not in covered or len(seen)%41==0:
            selected[0xffe00000+i*4]=word;covered.add(fn)
    # Every fixed uploaded operation receives the same varied-state comparison.
    # Preserve distinct address/word cases, including multiple immutable upload
    # versions admitted at one PC; the fixture reads sequential rows.
    uploads=observed(a.observations)
    observation_checks=[]
    for path in a.observations:
        identities=observed([path]);rom_matches=ram_matches=extra=0
        for pc,values in identities.items():
            expected=static_word_at(pc,words)
            for word in values:
                if expected != word:extra+=1
                elif pc >= 0xffe00000:rom_matches+=1
                else:ram_matches+=1
        observation_checks.append({'path':str(path),'sha256':sha(path),
            'identities':sum(map(len,identities.values())),
            'romMatches':rom_matches,'ramCopyMatches':ram_matches,'extraIdentities':extra})
    images,image_manifest=ram_images(a.ram_image,table)
    image_checks=verify_image_observations(uploads,image_manifest)
    for pc,values in images.items():uploads.setdefault(pc,set()).update(values)
    cases=list(selected.items());upload_cases=[]
    for pc,values in sorted(uploads.items()):
        for word in sorted(values):
            if handler(table,word) is None:raise ValueError(f'Unsupported observed opcode {word:08x} at {pc:08x}')
            original=static_word_at(pc,words)
            if word!=original:
                upload_cases.append((pc,word));covered.add(handler(table,word))
    cases+=upload_cases
    trace=out/'cases.tsv';trace.write_text(''.join(f'{pc:08x} {word:08x}\n'for pc,word in cases))
    native=out/'generated'
    subprocess.run(['python3',str(ROOT/'scripts/compile_ppc.py'),'--upstream',str(up),'--game',str(a.game.resolve()),'--observations',str(trace),'--trace-only','--output',str(native)],check=True)
    fixture=(ROOT/'Tools/ReferenceLab/ppc_operation_fixture.cpp').read_text()
    results={}
    for kind,path in [('reference',cpu/'ppc.cpp'),('native',native/'ppc.cpp')]:
        harness=out/f'{kind}.cpp';harness.write_text(fixture.replace('FIXTURE_CORE',str(path)))
        binary=out/kind
        command=['clang++','-std=c++17','-O2','-fno-strict-aliasing','-ffp-contract=off','-DSUPERMODEL_OSX','-I'+str(src),'-I'+str(src/'OSD/SDL'),str(harness),str(src/'BlockFile.cpp'),'-Wl,-dead_strip','-o',str(binary)]
        if kind=='native':command.insert(3,'-DFIXTURE_NATIVE')
        subprocess.run(command,check=True)
        capture=out/f'{kind}.bin'
        with capture.open('wb')as f:subprocess.run([str(binary),str(trace)],stdout=f,check=True)
        results[kind]={'sha256':sha(capture),'bytes':capture.stat().st_size}
    if results['reference']!=results['native']:
        ref=(out/'reference.bin').read_bytes();nat=(out/'native.bin').read_bytes()
        offset=next(i for i,(x,y)in enumerate(zip(ref,nat))if x!=y)
        case=offset//(83*8);pc,word=cases[case//8]
        raise ValueError(f'PPC mismatch PC={pc:08x} word={word:08x} seed={case%8} byte={offset}')
    report={'passed':True,'instructionVariants':len(cases),'staticSampleVariants':len(selected),'fixedUploadVariants':len(upload_cases),'handlerFamilies':len(covered),'registerStates':8,
            'comparisons':len(cases)*8,'faultChecks':2,'ramImageObservationChecks':image_checks,
            'observationChecks':observation_checks,'observedAddresses':len(uploads),
            'observedIdentities':sum(map(len,uploads.values())),
            'results':results,'scope':'Fixed arithmetic, branches, flags, floating point and bus writes compared with the unchanged instruction implementation; supplied observations are bound and compared with the admitted static mapping, and all supplied fixed upload variants are included; changed opcode and unknown PC reject; separate full frame comparison still required.'}
    if input_hashes!={str(path.relative_to(ROOT)):sha(path) for path in inputs}:raise ValueError('Fixture inputs changed during verification')
    report['provenance']={'inputs':input_hashes,'fixtureCasesSHA256':sha(trace),
        'generatedFixtureSHA256':sha(native/'ppc.cpp'),'fixtureTranslationManifestSHA256':sha(native/'translation-manifest.json'),
        'harnesses':{kind:sha(out/f'{kind}.cpp') for kind in results},
        'binaries':{kind:sha(out/kind) for kind in results},
        'compiler':subprocess.check_output(['clang++','--version'],text=True).strip(),
        'flags':['-std=c++17','-O2','-fno-strict-aliasing','-ffp-contract=off','-DSUPERMODEL_OSX']}
    product_manifest=ROOT/'build/generated/ppc/translation-manifest.json'
    if product_manifest.exists():
        product=json.loads(product_manifest.read_text())
        if product['generatorSHA256']==sha(ROOT/'scripts/compile_ppc.py') and product['outputSHA256']==sha(product_manifest.parent/'ppc.cpp'):
            product_observations={(str(Path(entry['path']).resolve()),entry['sha256']) for entry in product['observations']}
            verified_observations={(str(path.resolve()),sha(path)) for path in a.observations}
            if product_observations != verified_observations:
                raise ValueError('Product observations differ from the supplied differential evidence')
            report['provenance']['productTranslationManifestSHA256']=sha(product_manifest)
            report['provenance']['productGeneratedSourceSHA256']=product['outputSHA256']
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()

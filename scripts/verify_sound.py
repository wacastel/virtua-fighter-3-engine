#!/usr/bin/env python3
"""Compare fixed sound operations against the untouched pinned reference core."""
from __future__ import annotations
import argparse
import ctypes
import json
import random
import resource
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from compile_sound import ROOT, SOURCE, MUSASHI, ROM_NAMES, ROM_BYTES, captures, sha, build_dsp, dsp_upload_variants
from prepare_source import REVISION

PRODUCT_FLAGS=['-O2','-arch','arm64','-mmacosx-version-min=14.0','-fexceptions',
               '-fno-strict-aliasing','-ffp-contract=off','-DSUPERMODEL_OSX']


def build(output, generated):
    output.mkdir(parents=True,exist_ok=True)
    fixture=ROOT/'Tools/ReferenceLab/sound68k_probe.c'
    reference=[MUSASHI/'m68kcpu.c']+list((generated/'musashi-original').glob('m68kop*.c'))
    native=list((generated/'musashi').glob('*.c'))
    commands=[]
    for kind,inputs,includes in [('reference',reference,[MUSASHI,generated/'musashi-original']),('native',native,[generated/'musashi'])]:
        commands.append(['cc','-dynamiclib','-std=c11','-DINLINE=static inline']+PRODUCT_FLAGS+['-Wno-unused-function','-I'+str(SOURCE/'Src/OSD/SDL')]+['-I'+str(i) for i in includes]+[str(p) for p in inputs+[fixture]]+['-o',str(output/f'{kind}.dylib')])
    synthetic=output/'synthetic'; synthetic.mkdir(exist_ok=True)
    random_fields=random.Random(20260924)
    programs=[]
    for _ in range(3):
        words=[]
        for _ in range(128):
            row=[random_fields.randrange(65536) for _ in range(4)]
            row[1]=(row[1]&~0xfc0)|(random_fields.randrange(0x32)<<6)
            words+=row
        programs.append({'kind':'scspdsp','words':words})
    (synthetic/'programs.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in programs))
    build_dsp(synthetic,programs,upload_closure=False)
    for kind,dsp in [('reference',SOURCE/'Src/Sound/SCSPDSP.cpp'),('native',generated/'SCSPDSP.cpp'),('synthetic',synthetic/'SCSPDSP.cpp')]:
        commands.append(['c++','-dynamiclib','-std=c++17']+PRODUCT_FLAGS+['-I'+str(SOURCE/'Src'),'-I'+str(SOURCE/'Src/OSD/SDL'),'-I'+str(SOURCE/'Src/Sound')]+[str(dsp),str(ROOT/'Tools/ReferenceLab/sound_dsp_probe.cpp'),'-o',str(output/f'{kind}_dsp.dylib')])
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda cmd:subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True),commands):
            if result.returncode: raise RuntimeError(result.stderr)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,default=ROOT/'build/generated/sound')
    parser.add_argument('--output',type=Path,default=ROOT/'build/verification/sound')
    parser.add_argument('--rom-dir',type=Path,default=ROOT/'build/media-source')
    parser.add_argument('--observations',type=Path,default=ROOT/'build/reference/sound-observations.jsonl')
    parser.add_argument('--no-build',action='store_true')
    parser.add_argument('--held-out',nargs=2,action='append',default=[],metavar=('CAPTURE_JSONL','REPLAY_REPORT'),help='Validate a separate original-processor capture without adding it to static admission')
    parser.add_argument('--acceptance',type=Path,help='Publish the complete report here; otherwise keep it with fixture output')
    parser.add_argument('--guard-probe',choices=('opcode','extension','unknown_pc','absent_board','odd_pc','dsp_program','dsp_slot','dsp_cached_change','dsp_limit'))
    args=parser.parse_args()
    if args.guard_probe:
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        if args.guard_probe.startswith('dsp_'):
            core=ctypes.CDLL(str(args.output/'native_dsp.dylib'))
            core.sound_dsp_probe.argtypes=[ctypes.POINTER(ctypes.c_uint16),ctypes.c_uint,ctypes.c_uint]
            code=(ctypes.c_uint16*512)()
            if args.guard_probe=='dsp_limit':
                core.sound_dsp_probe_limit.argtypes=[ctypes.POINTER(ctypes.c_uint16),ctypes.c_uint,ctypes.c_uint,ctypes.c_int]
                core.sound_dsp_probe_limit(code,0,1,129)
            elif args.guard_probe=='dsp_cached_change':
                core.sound_dsp_cache_guard()
            else:
                if args.guard_probe=='dsp_slot':
                    _,slots=dsp_upload_variants(captures(args.observations))
                    source,target,quad=next((a,b,quad) for a in range(128) for b in range(128) if a!=b for quad in slots[a] if quad not in set(slots[b]))
                    for word,value in enumerate(quad):code[4*target+word]=value
                else:code[0]=0xffff
                core.sound_dsp_probe(code,0,1)
        else:
            core=ctypes.CDLL(str(args.output/'native.dylib'))
            core.sound_probe_load.argtypes=[ctypes.c_uint,ctypes.c_void_p]
            core.sound_probe_run.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_uint64)]
            raw=bytearray((args.rom_dir/ROM_NAMES[0]).read_bytes())
            if args.guard_probe in ('opcode','extension'): raw[0x120 if args.guard_probe=='opcode' else 0x122]^=1
            core.sound_probe_load(0,ctypes.create_string_buffer(bytes(raw)))
            result=(ctypes.c_uint64*44)()
            core.sound_probe_run(1 if args.guard_probe=='absent_board' else 0,
                                 0x500000 if args.guard_probe=='unknown_pc' else 0x600121 if args.guard_probe=='odd_pc' else 0x600120,1,result)
        raise RuntimeError('Guard incorrectly accepted unknown or changed code')
    from prepare_source import verify_source
    verify_source(create=False)
    manifest=json.loads((args.generated/'manifest.json').read_text())
    assert manifest['game']=='vf3' and manifest['generatorSHA256']==sha(ROOT/'scripts/compile_sound.py')
    capture_hash=sha(args.observations) if args.observations.exists() else None
    assert manifest['observations_sha256']==capture_hash, 'Capture does not match generated program manifest'
    for filename,digest in manifest['outputs'].items(): assert sha(args.generated/filename)==digest, filename
    source_inputs=[ROOT/'scripts/compile_sound.py',Path(__file__).resolve(),ROOT/'Tools/ReferenceLab/sound68k_probe.c',ROOT/'Tools/ReferenceLab/sound_dsp_probe.cpp']
    source_hashes={str(path.relative_to(ROOT)):sha(path) for path in source_inputs}
    build_identity={'sourceInputs':source_hashes,'manifestSHA256':sha(args.generated/'manifest.json'),
                    'compiler':subprocess.check_output(['cc','--version'],text=True).strip(),'flags':PRODUCT_FLAGS,
                    'referenceGeneratedSources':{p.name:sha(p) for p in sorted((args.generated/'musashi-original').glob('*')) if p.suffix in ('.c','.h')}}
    receipt=args.output/'fixture-build.json'
    if not args.no_build:
        build(args.output,args.generated)
        receipt.write_text(json.dumps({'inputs':build_identity,'binaries':{p.name:sha(p) for p in args.output.glob('*.dylib')}},indent=2)+'\n')
    else:
        previous=json.loads(receipt.read_text())
        assert previous['inputs']==build_identity, 'Fixture build inputs changed'
        assert previous['binaries']=={p.name:sha(p) for p in args.output.glob('*.dylib')}, 'Fixture binary changed'
    cores=[ctypes.CDLL(str(args.output/f'{kind}.dylib'),mode=ctypes.RTLD_LOCAL) for kind in ('reference','native')]
    for core in cores:
        core.sound_probe_load.argtypes=[ctypes.c_uint,ctypes.c_void_p]
        core.sound_probe_run.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_uint64)]
    trial_count=0
    for board,name in enumerate(ROM_NAMES):
        raw=(args.rom_dir/name).read_bytes()
        assert len(raw)==ROM_BYTES and sha(raw)==manifest['m68k']['roms'][board]['sha256']
        for core in cores: core.sound_probe_load(board,ctypes.create_string_buffer(raw))
        # Every distinct bound opcode is exercised in two register/flag states.
        positions={}
        for offset in range(0,len(raw)-32,2): positions.setdefault(int.from_bytes(raw[offset:offset+2],'little'),offset)
        assert set(positions)=={int.from_bytes(raw[i:i+2],'little') for i in range(0,len(raw),2)}, 'Boundary exclusion omitted a distinct ROM word'
        for opcode,offset in positions.items():
            pc=offset+(0x600000 if board==0 else 0)
            for seed in (0x12345678,0xdeadbeef):
                results=[]
                for core in cores:
                    result=(ctypes.c_uint64*44)()
                    core.sound_probe_run(board,pc,seed,result)
                    results.append(list(result))
                assert results[0]==results[1], {'board':board,'pc':hex(pc),'word':hex(opcode),'seed':hex(seed),'differing':[(i,a,b) for i,(a,b) in enumerate(zip(*results)) if a!=b]}
                trial_count+=1
    dsps=[ctypes.CDLL(str(args.output/f'{kind}_dsp.dylib'),mode=ctypes.RTLD_LOCAL) for kind in ('reference','native')]
    for core in dsps:
        core.sound_dsp_probe.argtypes=[ctypes.POINTER(ctypes.c_uint16),ctypes.c_uint,ctypes.c_uint]
        core.sound_dsp_probe.restype=ctypes.c_uint64
        core.sound_dsp_probe_limit.argtypes=[ctypes.POINTER(ctypes.c_uint16),ctypes.c_uint,ctypes.c_uint,ctypes.c_int]
        core.sound_dsp_probe_limit.restype=ctypes.c_uint64
    programs={tuple([0]*512)}|{tuple(x['words']) for x in captures(args.observations) if x['kind']=='scspdsp'}
    limit_trials=0
    for index,program in enumerate(sorted(programs)):
        code=(ctypes.c_uint16*512)(*program)
        for seed in range(16):
            results=[core.sound_dsp_probe(code,seed,13) for core in dsps]
            assert results[0]==results[1], {'dsp_program':index,'seed':seed,'results':results}
        # LastStep is a latched execution limit, not a decoder-derived property
        # of the currently visible image while an upload is in progress.
        last=max((i//4+1 for i,word in enumerate(program) if word),default=0)
        for limit in sorted({0,1,last//2,last,128}):
            results=[core.sound_dsp_probe_limit(code,0x12345678,13,limit) for core in dsps]
            assert results[0]==results[1], {'dsp_program':index,'latched_limit':limit,'results':results}
            limit_trials+=1
    # Every exact statically admitted instruction is checked in its original
    # slot, embedded in a nonzero, valid observed surrounding program. This
    # exercises scratch-register carry, delayed memory reads and slot parity.
    _,slot_variants=dsp_upload_variants(captures(args.observations))
    valid_programs=[p for p in programs if all(((p[4*slot+1]>>6)&63)<50 for slot in range(128))]
    base=max(valid_programs,key=lambda p:sum(bool(word) for word in p))
    closure_trials=0
    for slot,variants in enumerate(slot_variants):
        for quad in variants:
            words=list(base);words[4*slot:4*slot+4]=quad
            code=(ctypes.c_uint16*512)(*words)
            for seed in (0x12345678,0xdeadbeef):
                results=[core.sound_dsp_probe_limit(code,seed,3,128) for core in dsps]
                assert results[0]==results[1], {'closure_slot':slot,'quad':quad,'seed':seed,'results':results}
                closure_trials+=1
    held_out=[]
    admitted=[set(variants) for variants in slot_variants]
    observed=[{p[4*slot:4*slot+4] for p in programs} for slot in range(128)]
    for capture_name,report_name in args.held_out:
        capture_path,report_path=Path(capture_name).resolve(),Path(report_name).resolve()
        replay=json.loads(report_path.read_text())
        assert replay.get('passed') is True and replay['frames']>0 and replay['librarySHA256']
        additional={tuple(item['words']) for item in captures(capture_path) if item['kind']=='scspdsp'}
        assert additional, 'Held-out capture contains no DSP images'
        new_quads=set()
        for program in additional:
            for slot in range(128):
                quad=program[4*slot:4*slot+4]
                assert quad in admitted[slot], {'held_out':capture_name,'unsupported_slot':slot,'quad':quad}
                if quad not in observed[slot]:new_quads.add((slot,quad))
            code=(ctypes.c_uint16*512)(*program)
            for seed in (0x12345678,0xdeadbeef):
                results=[core.sound_dsp_probe(code,seed,13) for core in dsps]
                assert results[0]==results[1], {'held_out':capture_name,'seed':seed,'results':results}
        held_out.append({'capture':str(capture_path.relative_to(ROOT)),'captureSHA256':sha(capture_path),
                         'replayReport':str(report_path.relative_to(ROOT)),'replayReportSHA256':sha(report_path),
                         'observerLibrarySHA256':replay['librarySHA256'],'frames':replay['frames'],
                         'capturedDSPImages':len(additional),'unseenObservedSlotQuads':len(new_quads),
                         'unsupportedSlotQuads':0,'differentialTrials':2*len(additional),
                         'includedInAuthorizingCorpus':False})
    # Mixed instructions and independent byte-write progress produce new whole
    # images. Exercise cache hits, changing cached quads and persistent memory
    # across an entire sequence with changing latched execution limits.
    for core in dsps:
        core.sound_dsp_sequence_probe.argtypes=[ctypes.POINTER(ctypes.c_uint16),ctypes.POINTER(ctypes.c_int),ctypes.c_uint,ctypes.c_uint]
        core.sound_dsp_sequence_probe.restype=ctypes.c_uint64
    rng=random.Random(20260925)
    sequence=[];limits=[];mixed_trials=0
    for index in range(128):
        words=[word for variants in slot_variants for word in rng.choice(variants)]
        code=(ctypes.c_uint16*512)(*words)
        for seed in (0x76543210,0xbaadf00d):
            results=[core.sound_dsp_probe_limit(code,seed,13,128) for core in dsps]
            assert results[0]==results[1], {'mixed_program':index,'seed':seed,'results':results}
            mixed_trials+=1
        # A repeated image exercises a cache hit; another byte update changes
        # an instruction without replacing the context or resetting scratch RAM.
        sequence.extend((words,words))
        limits.extend((128,index%129))
    packed=(ctypes.c_uint16*(512*len(sequence)))(*(word for words in sequence for word in words))
    latched=(ctypes.c_int*len(limits))(*limits)
    for seed in range(16):
        results=[core.sound_dsp_sequence_probe(packed,latched,len(sequence),seed) for core in dsps]
        assert results[0]==results[1], {'changing_program_sequence_seed':seed,'results':results}
    synthetic=ctypes.CDLL(str(args.output/'synthetic_dsp.dylib'),mode=ctypes.RTLD_LOCAL)
    synthetic.sound_dsp_probe.argtypes=dsps[0].sound_dsp_probe.argtypes
    synthetic.sound_dsp_probe.restype=ctypes.c_uint64
    for index,item in enumerate(captures(args.output/'synthetic/programs.jsonl')):
        code=(ctypes.c_uint16*512)(*item['words'])
        for seed in range(16):
            reference=dsps[0].sound_dsp_probe(code,seed,13)
            native=synthetic.sound_dsp_probe(code,seed,13)
            assert reference==native, {'synthetic_dsp_program':index,'seed':seed}
    report={'passed':True,'m68k_instruction_trials':trial_count,'m68k_compared':['registers','flags','pc','cycles','ordered_bus_reads','ordered_bus_writes','stop_state'], 'scspdsp_programs':len(programs),'scspdsp_trials':len(programs)*16,'scspdsp_compared':['entire_dsp_state','entire_512K_word_sample_ram'],'manifest_sha256':sha(args.generated/'manifest.json')}
    mirror_trials=0
    # The full512KiB ROM is mirrored by the pinned board without zero padding.
    raw=(args.rom_dir/ROM_NAMES[0]).read_bytes()
    for offset in (0x120,0x20000,0x40000,0x7ffe0):
        for seed in (0x12345678,0xdeadbeef):
            results=[]
            for core in cores:
                result=(ctypes.c_uint64*44)();core.sound_probe_run(0,0x680000+offset,seed,result);results.append(list(result))
            assert results[0]==results[1], {'mirror_pc':hex(0x680000+offset),'seed':seed}
            mirror_trials+=1
    report['m68k_mirror_trials']=mirror_trials
    report['scspdsp_slot_instruction_variants']=sum(map(len,slot_variants))
    report['scspdsp_closure_instruction_trials']=closure_trials
    report['scspdsp_held_out_trials']=sum(row['differentialTrials'] for row in held_out)
    report['scspdsp_mixed_program_trials']=mixed_trials
    report['scspdsp_changing_cached_sequence_trials']=16
    report['scspdsp_samples_per_cached_sequence']=len(sequence)
    report['scspdsp_synthetic_trials']=48
    report['scspdsp_latched_limit_trials']=limit_trials
    for probe in ('opcode','extension','unknown_pc','absent_board','odd_pc','dsp_program','dsp_slot','dsp_cached_change','dsp_limit'):
        child=subprocess.run([sys.executable,__file__,'--output',str(args.output),'--rom-dir',str(args.rom_dir),'--observations',str(args.observations),'--guard-probe',probe],capture_output=True,text=True)
        assert child.returncode<0 and ('guard failed' in child.stderr or 'Untranslated SCSP DSP instruction' in child.stderr or 'Invalid SCSP DSP execution limit' in child.stderr), (probe,child.returncode,child.stderr)
    report['negative_guards']=['changed opcode rejected','changed extension rejected','unknown PC rejected','absent DSB board rejected','odd PC rejected','unknown DSP instruction rejected','instruction at unknown slot rejected','changed cached instruction rejected','invalid DSP execution limit rejected']
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest=json.loads((args.generated/'manifest.json').read_text())
    acceptance={'format':1,'passed':True,'target':'arm64-apple-macosx','upstreamCommit':REVISION,
                'compiler':subprocess.check_output(['cc','--version'],text=True).strip(),
                'flags':PRODUCT_FLAGS,
                'game':'vf3','revision':'Japan Revision D',
                'cpus':['SCSP sound-board 68000','two SCSP DSPs'],'absentHardware':['DSB MPEG daughterboard'],
                'generatorSHA256':sha(ROOT/'scripts/compile_sound.py'),
                'verifierSHA256':sha(Path(__file__).resolve()),
                'fixtures':{p.name:sha(p) for p in [ROOT/'Tools/ReferenceLab/sound68k_probe.c',ROOT/'Tools/ReferenceLab/sound_dsp_probe.cpp']},
                'media':manifest['m68k']['roms'],
                'originalSources':manifest['inputs'],
                'generation':{'m68k':manifest['m68k'],'scspdsp':{k:v for k,v in manifest['scspdsp'].items() if k!='program_sha256'}},
                'captureSHA256':capture_hash,'productTranslationManifestSHA256':sha(args.generated/'manifest.json'),
                'differential':report,
                'limitations':['68000 comparison covers every distinct word from the verified 512 KiB sound ROM as an opcode at a representative address in two register/flag states; it does not enumerate every address or machine state.',
                               'DSP comparison covers captured images, every exact slot-specific instruction from the finite per-byte upload closure, mixed programs and changing cached instructions, plus three synthetic programs. This admits new combinations of known byte values at their observed positions, not only observed whole images.',
                               'The original board permits independent 8-, 16-, and 32-bit program-memory writes while LastStep remains latched. The offline Cartesian byte closure supports arbitrary progress/interruption between observed uploads. Unknown slot-specific quads, byte values, and invalid execution limits fail explicitly.',
                               'A zero LastStep executes no DSP instructions during program upload. Nonzero limits select only exact guarded offline-specialized operations; no runtime instruction-field decoding occurs.',
                               'Full-game frame/audio replay and physical audio/controller acceptance are separate integration requirements.']}
    source_inventory=args.observations.with_name('sound-capture-sources.json')
    if source_inventory.exists():
        inventory=json.loads(source_inventory.read_text())
        assert inventory['game']=='vf3' and inventory['upstreamCommit']==REVISION
        assert inventory['mergedCaptureSHA256']==capture_hash, 'Capture inventory mismatch'
        assert inventory['mergeScriptSHA256']==sha(ROOT/'Tools/ReferenceLab/sound_captures.py'), 'Capture merger changed'
        assert inventory['observerBuildManifestSHA256']==sha(ROOT/inventory['observerBuildManifest']), 'Observer manifest changed'
        for run in inventory['runs']:
            assert sha(ROOT/run['capture'])==run['captureSHA256'], 'Source capture changed'
            assert sha(ROOT/run['report'])==run['reportSHA256'], 'Source replay report changed'
        acceptance['captureSources']=inventory
        if held_out:
            for run in held_out:
                assert run['observerLibrarySHA256']==inventory['runs'][0]['observerLibrarySHA256']
                assert sha(ROOT/run['capture'])==run['captureSHA256']
                assert sha(ROOT/run['replayReport'])==run['replayReportSHA256']
            acceptance['heldOutCaptures']=held_out
    assert source_hashes=={str(path.relative_to(ROOT)):sha(path) for path in source_inputs}, 'Sound qualification inputs changed'
    assert build_identity['manifestSHA256']==sha(args.generated/'manifest.json'), 'Generated manifest changed during qualification'
    acceptance['sourceInputs']=source_hashes
    acceptance['fixturesAndBinaries']={p.name:sha(p) for p in args.output.glob('*.dylib')}
    acceptance['fixtureBuildReceiptSHA256']=sha(receipt)
    acceptance['referenceGeneratedSources']=build_identity['referenceGeneratedSources']
    acceptance['captureReady']=args.observations.exists() and any(x['kind']=='scspdsp' and any(x['words']) for x in captures(args.observations))
    assert capture_hash==(sha(args.observations) if args.observations.exists() else None), 'Capture changed during qualification'
    destination=args.acceptance or args.output/'acceptance.json'
    if args.acceptance: assert acceptance['captureReady'] and 'captureSources' in acceptance, 'Published acceptance needs current-game capture provenance'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(acceptance,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()

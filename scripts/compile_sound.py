#!/usr/bin/env python3
"""Offline Virtua Fighter 3 sound-program specialization from local licensed media.

Generated ROM-dependent C and observations stay under ignored build/. Musashi's
operation selection is performed here, never by the native player. SCSP programs
are emitted as straight-line constant operations from reference captures.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import re
import shutil
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'build/upstream/supermodel'
MUSASHI = SOURCE / 'Src/CPU/68K/Musashi'
ROM_NAMES = ('epr-19231.21',)
ROM_SHA256 = ('33b02da29908f4b348c3442ecd2118ffafba8bb6ebcae862ffe708f58ab15a0a',)
ROM_BYTES = 0x80000
ROM_CRC32 = 0xb416fe96


def sha(data):
    if isinstance(data, Path): data = data.read_bytes()
    if isinstance(data, str): data = data.encode()
    return hashlib.sha256(data).hexdigest()


def replace_function(source, signature, body):
    start = source.index(signature)
    opening = source.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[:opening] + '{\n' + body + '\n}' + source[end:]


def captures(path):
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []
    for item in rows:
        if not isinstance(item, dict) or item.get('kind') not in ('m68k', 'scspdsp'):
            raise ValueError('Unknown sound capture record')
        expected = 12 if item['kind'] == 'm68k' else 512
        if len(item.get('words', [])) != expected or any(type(word) is not int or not 0 <= word <= 65535 for word in item['words']):
            raise ValueError('Invalid sound capture words')
    return rows


def build_musashi(output, rom_dir, observations):
    out = output / 'musashi'
    out.mkdir(parents=True, exist_ok=True)
    original = output / 'musashi-original'
    original.mkdir(exist_ok=True)
    subprocess.run(['cc','-O2',str(MUSASHI/'m68kmake.c'),'-o',str(output/'m68kmake')],check=True)
    subprocess.run([str(output/'m68kmake'),str(original),str(MUSASHI/'m68k_in.c')],check=True,stdout=subprocess.DEVNULL)
    # Reproduce the original table-builder's overwrite order offline.
    table = [('m68k_op_illegal',0)] * 65536
    rows = re.findall(r'\{(m68k_op_\w+)\s*,\s*0x([0-9a-f]+),\s*0x([0-9a-f]+),\s*\{\s*(\d+),\s*\d+,\s*\d+\}\}', (original/'m68kops.c').read_text())
    assert len(rows) == 1962, len(rows)
    for name,mask,match,cycles in rows:
        mask,match,cycles = int(mask,16),int(match,16),int(cycles)
        free = (~mask)&65535
        sub = 0
        while True:
            word = match | sub
            extra = 2*(((word >> 9)&7) or 8) if mask == 0xf1f8 and (word&0xf000)==0xe000 and not word&0x20 else 0
            table[word] = (name,cycles+extra)
            sub = (sub-free)&free
            if not sub: break
    functions = {}
    for name in ('m68kopac.c','m68kopdm.c','m68kopnz.c'):
        pp = subprocess.check_output(['cc','-E','-P','-I'+str(MUSASHI),'-I'+str(SOURCE/'Src/OSD/SDL'),str(original/name)],text=True)
        functions.update(re.findall(r'void (m68k_op_\w+)\(void\)\s*\{(.*?)\n\}',pp,re.S))
    assert len(functions) == 1962, len(functions)
    roms = []
    identities = []
    for name,expected in zip(ROM_NAMES,ROM_SHA256):
        path = rom_dir / name
        raw = path.read_bytes()
        assert len(raw)==ROM_BYTES, (name,len(raw))
        assert zlib.crc32(raw)==ROM_CRC32, f'Wrong sound program CRC: {name}'
        assert sha(raw)==expected, f'Wrong revision or damaged sound program: {name}'
        roms.append([int.from_bytes(raw[i:i+2],'little') for i in range(0,len(raw),2)])
        identities.append({'name':name,'bytes':len(raw),'crc32':f'{zlib.crc32(raw):08x}','sha256':sha(raw)})
    extra_words = {}
    for item in observations:
        if item['kind'] != 'm68k': continue
        board, pc = item['board'],item['pc']
        if board != 0: raise ValueError('VF3 has no DSB 68000: captured board '+str(board))
        if type(pc) is not int or pc & 1 or not 0 <= pc < 0x1000000: raise ValueError('Invalid captured sound PC')
        if len(item['words']) != 12 or any(type(word) is not int or not 0 <= word <= 65535 for word in item['words']): raise ValueError('Invalid captured sound words')
        for i, word in enumerate(item['words']):
            addr = (pc+2*i)&0xffffff
            if board == 0 and 0x600000 <= addr < 0x700000:
                offset=(addr-0x600000)&0x7ffff
                assert word==roms[0][offset//2], (board,hex(addr),word)
                continue
            key=(board,addr)
            if key in extra_words and extra_words[key] != word:
                raise RuntimeError(f'Mutable captured sound code {key}: {extra_words[key]:04x}/{word:04x}; requires explicit program variants')
            extra_words[key] = word
    words = sorted(set(roms[0]+list(extra_words.values())))
    bodies = {}
    word_function = {}
    for word in words:
        body = functions[table[word][0]].replace('m68ki_cpu.ir',f'0x{word:04x}U')
        # The preprocessor expanded DX/DY/AX/AY and addressing macros, so every
        # opcode-derived operand/register selector is now a literal expression.
        key = sha(body)
        if key not in bodies: bodies[key] = (f'vf3_sound_op_{len(bodies):05d}',body)
        word_function[word] = bodies[key][0]
    header = (MUSASHI/'m68kcpu.h').read_text()
    interface = '''
/* Offline-bound program entries; lookup uses board and instruction address. */
typedef struct vf3_sound_entry {
    void (*operation)(void);
    unsigned short word;
    unsigned char cycles, index_register, index_long;
    signed char displacement;
} vf3_sound_entry;
extern unsigned vf3_m68k_board;
extern unsigned vf3_m68k_current_cycles;
const vf3_sound_entry *vf3_sound_entry_at(unsigned pc);
void vf3_sound_fault(unsigned pc, unsigned actual, unsigned expected);
'''
    pos = header.index('/* Handles all immediate reads')
    header = header[:pos] + interface + '\n' + header[pos:]
    header = replace_function(header,'INLINE uint m68ki_read_imm_16(void)\n{', '''
    unsigned pc = ADDRESS_68K(REG_PC);
    const vf3_sound_entry *entry = vf3_sound_entry_at(pc);
    unsigned actual = m68k_read_immediate_16(pc);
    if (actual != entry->word) vf3_sound_fault(pc, actual, entry->word);
    m68ki_set_fc(FLAG_S | FUNCTION_CODE_USER_PROGRAM);
    m68ki_check_address_error(REG_PC, MODE_READ, FLAG_S | FUNCTION_CODE_USER_PROGRAM);
    REG_PC += 2;
    return entry->word;''')
    header = replace_function(header,'INLINE uint m68ki_read_imm_32(void)\n{', '''
    unsigned pc = ADDRESS_68K(REG_PC);
    const vf3_sound_entry *high = vf3_sound_entry_at(pc);
    const vf3_sound_entry *low = vf3_sound_entry_at(ADDRESS_68K(pc+2));
    unsigned expected = ((unsigned)high->word << 16) | low->word;
    unsigned actual = m68k_read_immediate_32(pc);
    if (actual != expected) vf3_sound_fault(pc, actual, expected);
    m68ki_set_fc(FLAG_S | FUNCTION_CODE_USER_PROGRAM);
    m68ki_check_address_error(REG_PC, MODE_READ, FLAG_S | FUNCTION_CODE_USER_PROGRAM);
    REG_PC += 4;
    return expected;''')
    header = replace_function(header,'INLINE uint m68ki_get_ea_ix(uint An)\n{', '''
    const vf3_sound_entry *entry = vf3_sound_entry_at(ADDRESS_68K(REG_PC));
    unsigned index;
    (void)m68ki_read_imm_16();
    index = REG_DA[entry->index_register];
    if (!entry->index_long) index = MAKE_INT_16(index);
    return An + index + entry->displacement;''')
    header = header.replace('CYC_INSTRUCTION[REG_IR]','vf3_m68k_current_cycles')
    (out/'m68kcpu.h').write_text(header)
    core = (MUSASHI/'m68kcpu.c').read_text()
    core = core.replace('''REG_IR = m68ki_read_imm_16();
\t\t\tm68ki_instruction_jump_table[REG_IR]();
\t\t\tUSE_CYCLES(CYC_INSTRUCTION[REG_IR]);''','''{
                const vf3_sound_entry *entry = vf3_sound_entry_at(ADDRESS_68K(REG_PC));
                (void)m68ki_read_imm_16();
                REG_IR = entry->word;
                vf3_m68k_current_cycles = entry->cycles;
                entry->operation();
                USE_CYCLES(entry->cycles);
            }''')
    core = core.replace('m68ki_build_opcode_table();','/* Operation selection was completed offline. */')
    core = re.sub(r'CYC_INSTRUCTION\s*= m68ki_cycles\[\d\];', 'CYC_INSTRUCTION = NULL;',core)
    core = core.replace('REG_SP = m68ki_read_imm_32();\n\tREG_PC = m68ki_read_imm_32();','REG_SP = m68k_read_immediate_32(0);\n\tREG_PC = m68k_read_immediate_32(4);')
    assert 'm68ki_instruction_jump_table' not in core
    (out/'m68kcpu.c').write_text(core)
    for name in ('m68k.h','m68kconf.h','m68kctx.h'): shutil.copyfile(MUSASHI/name,out/name)
    (out/'m68kops.h').write_text('/* Fixed-program build: no runtime opcode table. */\n')
    for old in out.glob('m68k_fixed_ops_*.c'): old.unlink()
    notice=(MUSASHI/'m68k_in.c').read_text().split('/* Input file for m68kmake')[0]
    values = list(bodies.values())
    for start in range(0,len(values),256):
        lines = [notice,'/* Generated offline; derived from the pinned Supermodel Musashi core. */\n#include "m68kcpu.h"\n']
        for name,body in values[start:start+256]: lines.append(f'void {name}(void)\n{{{body}\n}}\n')
        (out/f'm68k_fixed_ops_{start//256:03}.c').write_text(''.join(lines))
    def entry(word):
        return '{%s,0x%04x,%d,%d,%d,%d}'%(word_function[word],word,table[word][1],word>>12,1 if word&0x800 else 0,(word&255)-(256 if word&128 else 0))
    lines = [notice,'#include "m68kcpu.h"\n#include <stdio.h>\nvoid vf3_native_fault(const char *message) __attribute__((noreturn));\nunsigned vf3_m68k_current_cycles;\n']
    lines += [f'void {name}(void);\n' for name,_ in values]
    for board in range(1):
        lines.append(f'static const vf3_sound_entry board_{board}[262144] = {{\n')
        lines += [entry(word)+',\n' for word in roms[board]]
        lines.append('};\n')
    for (board,addr),word in sorted(extra_words.items()): lines.append(f'static const vf3_sound_entry extra_{board}_{addr:06x} = '+entry(word)+';\n')
    lines.append('''void vf3_sound_fault(unsigned pc, unsigned actual, unsigned expected) {
    char message[192];
    snprintf(message,sizeof(message),"Fixed sound program guard failed: board=%u pc=%06x actual=%04x expected=%04x",vf3_m68k_board,pc,actual,expected);
    vf3_native_fault(message);
}
const vf3_sound_entry *vf3_sound_entry_at(unsigned pc) {
    if (vf3_m68k_board != 0 || pc >= 0x1000000 || (pc & 1)) vf3_sound_fault(pc,0,0xffffffff);
    if (vf3_m68k_board == 0 && pc >= 0x600000 && pc < 0x700000) {
        unsigned offset = (pc-0x600000)&0x7ffff;
        return &board_0[offset>>1];
    }
    switch ((vf3_m68k_board << 24) | pc) {
''')
    for (board,addr),word in sorted(extra_words.items()): lines.append(f'case 0x{(board<<24)|addr:08x}: return &extra_{board}_{addr:06x};\n')
    lines.append('default: vf3_sound_fault(pc,0,0xffffffff); return 0;\n}\n}\n')
    (out/'m68k_fixed_table.c').write_text(''.join(lines))
    return {'roms':identities,'boards':[0],'absentBoards':[1],'otherBoardsFailClosed':True,'canonicalRange':'0x600000..0x67ffff','mirrorRange':'0x680000..0x6fffff','romWordOrder':'little-endian raw halfwords after pinned loader/board transformations','aligned_rom_entries':ROM_BYTES//2,'ram_word_entries':len(extra_words),'specialized_operation_bodies':len(bodies),'runtime_opcode_decoder':False,'fallback':False}


def dsp_upload_variants(observations):
    """Finite per-slot byte-write closure of observed program images and reset.

    The pinned SCSP_w8/16/32 handlers write MPRO without stopping execution;
    LastStep changes only at the start-register write. Therefore a sample may
    see arbitrary upload progress. Each byte is restricted to values observed
    at that exact slot/byte position, including the authenticated zero reset.
    The Cartesian closure is computed offline; the player admits exact quads.
    """
    programs = sorted({tuple([0]*512)} | {tuple(item['words']) for item in observations if item['kind']=='scspdsp'})
    slots=[]
    for slot in range(128):
        positions=[sorted({(program[slot*4+word] >> shift)&255 for program in programs})
                   for word in range(4) for shift in (0,8)]
        quads={tuple(row[2*word] | (row[2*word+1]<<8) for word in range(4))
               for row in itertools.product(*positions)}
        slots.append(sorted(quads))
    return programs,slots


def dsp_key(quad):
    return sum(word << (16*index) for index,word in enumerate(quad))


def build_dsp(output, observations, upload_closure=True):
    source=(SOURCE/'Src/Sound/SCSPDSP.cpp').read_text()
    original=source[source.index('void SCSPDSP_Step('):source.index('void SCSPDSP_SetSample(')]
    if upload_closure:
        programs,slots=dsp_upload_variants(observations)
    else:
        # Synthetic operation fixtures intentionally admit only their supplied
        # instructions, without multiplying random test bytes into a vocabulary.
        programs=sorted({tuple([0]*512)} | {tuple(item['words']) for item in observations if item['kind']=='scspdsp'})
        slots=[sorted({p[4*slot:4*slot+4] for p in programs}) for slot in range(128)]
    dec_start=original.index('\t\tUINT16 *IPtr')
    operations=original[original.index('\t\tINT64 v;',dec_start):original.rindex('\n\t}\n\t--DSP->DEC;')]
    declarations=re.findall(r'UINT32 (\w+) = \(IPtr\[(\d)\] >> (\d+)\) & (0x[0-9A-Fa-f]+);',original)
    assert len(declarations)==25,len(declarations)
    assert len(re.findall(r'\bstep\b',operations))==2 and operations.count('(step & 1)')==2
    locals_=('ACC','SHIFTED','X','Y','B','INPUTS','MEMVAL','FRC_REG','Y_REG','ADDR','ADRS_REG')
    blocks=['struct FixedDSPState { INT32 ACC=0, SHIFTED=0, X=0, Y=0, B=0, INPUTS=0, MEMVAL=0, FRC_REG=0, Y_REG=0; UINT32 ADDR=0, ADRS_REG=0; };\n']
    # The sole use of step is memory-access parity. Bind it offline alongside
    # all 25 instruction fields; identical constant bodies share one function.
    bodies={};slot_entries=[]
    for slot,quads in enumerate(slots):
        entries=[]
        for quad in sorted(quads,key=dsp_key):
            fields={name:(quad[int(word)]>>int(shift))&int(mask,16) for name,word,shift,mask in declarations}
            fields['step']=slot & 1
            body=operations
            for name,value in fields.items():body=re.sub(r'(?<!->)\b'+name+r'\b',str(value),body)
            for name in locals_:body=re.sub(r'(?<!->)\b'+name+r'\b','state.'+name,body)
            # Invalid IRA returns from the entire original sample immediately.
            body=body.replace('return;','return false;')
            identity=sha(body)
            if identity not in bodies:bodies[identity]=(len(bodies),body)
            entries.append((dsp_key(quad),bodies[identity][0]))
        slot_entries.append(entries)
    for index,body in bodies.values():
        blocks.append(f'static bool fixed_dsp_op_{index}(_SCSPDSP *DSP, FixedDSPState &state) {{{body}\n return true;\n}}\n')
    blocks.append('struct FixedDSPInstruction { UINT64 words; bool (*run)(_SCSPDSP *, FixedDSPState &); };\n')
    offsets=[0]
    blocks.append('static const FixedDSPInstruction fixed_dsp_instructions[] = {\n')
    for entries in slot_entries:
        blocks.extend(f'{{0x{key:016x}ULL, fixed_dsp_op_{index}}},\n' for key,index in entries)
        offsets.append(offsets[-1]+len(entries))
    blocks.append('};\nstatic const unsigned fixed_dsp_slot_offsets[129] = {'+','.join(map(str,offsets))+'};\n')
    blocks.append(r"""
void SCSPDSP_Step(_SCSPDSP *DSP) {
    if (DSP->Stopped) return;
    if (DSP->LastStep < 0 || DSP->LastStep > 128)
        vf3_native_fault("Invalid SCSP DSP execution limit");
    memset(DSP->EFREG, 0, sizeof(DSP->EFREG));
    FixedDSPState state;
    // Cache only exact slot-bound instructions already compiled offline. Every
    // executing quad is checked on every sample, including after state loads.
    struct Cache { _SCSPDSP *dsp; const FixedDSPInstruction *instructions[128]; };
    static Cache cached[2] = {};
    unsigned cache_slot = cached[0].dsp==DSP ? 0 : cached[1].dsp==DSP ? 1 : !cached[0].dsp ? 0 : 1;
    if (cached[cache_slot].dsp != DSP) {
        cached[cache_slot].dsp = DSP;
        memset(cached[cache_slot].instructions, 0, sizeof(cached[cache_slot].instructions));
    }
    for (int slot=0; slot<DSP->LastStep; ++slot) {
        const UINT16 *words = DSP->MPRO+4*slot;
        // Packing an exact identity is not instruction-field decoding.
        const UINT64 identity = (UINT64)words[0] | ((UINT64)words[1]<<16) |
                                ((UINT64)words[2]<<32) | ((UINT64)words[3]<<48);
        const FixedDSPInstruction *instruction = cached[cache_slot].instructions[slot];
        if (!instruction || instruction->words != identity) {
            unsigned low=fixed_dsp_slot_offsets[slot], high=fixed_dsp_slot_offsets[slot+1];
            while (low<high) {
                unsigned middle=low+(high-low)/2;
                if (fixed_dsp_instructions[middle].words<identity) low=middle+1;
                else high=middle;
            }
            if (low==fixed_dsp_slot_offsets[slot+1] || fixed_dsp_instructions[low].words!=identity) {
                char message[192];
                snprintf(message,sizeof(message),"Untranslated SCSP DSP instruction: slot=%d words=%04x/%04x/%04x/%04x",slot,words[0],words[1],words[2],words[3]);
                vf3_native_fault(message);
            }
            instruction=&fixed_dsp_instructions[low];
            cached[cache_slot].instructions[slot]=instruction;
        }
        if (!instruction->run(DSP,state)) return;
    }
    --DSP->DEC;
    memset(DSP->MIXS, 0, sizeof(DSP->MIXS));
}

""")
    source=source.replace(original,'\n'.join(blocks))
    source=source.replace('#include "SCSPDSP.h"','#include "SCSPDSP.h"\n#include <cstdio>\nextern "C" void vf3_native_fault(const char *message) __attribute__((noreturn));\n#if defined(__clang__)\n#pragma clang diagnostic ignored "-Wconstant-logical-operand"\n#endif')
    (output/'SCSPDSP.cpp').write_text(source)
    assert 'UINT16 *IPtr = DSP->MPRO + step * 4' not in source
    return {'captured_program_images':len(programs),'program_sha256':[sha(b''.join(w.to_bytes(2,'little') for w in p)) for p in programs],
            'admission':'Exact slot-specific four-word instructions from the offline per-byte upload closure of observed images and zero reset',
            'observed_slot_instructions':sum(len({p[4*slot:4*slot+4] for p in programs}) for slot in range(128)),
            'static_slot_instruction_variants':sum(map(len,slots)),'specialized_operation_bodies':len(bodies),
            'slot_variant_counts':list(map(len,slots)),
            'upload_write_widths':[8,16,32],'unknown_byte_values_rejected':True,'instruction_slot_bound':True,
            'runtime_instruction_decoder':False,'fallback':False,'original_execution_limit_preserved':True,
            'zero_length_uploads_execute_no_instructions':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/generated/sound')
    parser.add_argument('--rom-dir',type=Path,default=ROOT/'build/media-source')
    parser.add_argument('--observations',type=Path,default=ROOT/'build/reference/sound-observations.jsonl')
    args=parser.parse_args()
    from prepare_source import verify_source, REVISION
    original_source=verify_source(create=False)
    args.output.mkdir(parents=True,exist_ok=True)
    observed=captures(args.observations)
    report={'schema':1,'m68k':build_musashi(args.output,args.rom_dir,observed),'scspdsp':build_dsp(args.output,observed),'observations_sha256':sha(args.observations) if args.observations.exists() else None}
    report['game']='vf3'
    report['revision']='Japan Revision D'
    report['upstreamCommit']=REVISION
    report['upstreamArchiveSHA256']=original_source['archiveSHA256']
    report['generatorSHA256']=sha(Path(__file__).resolve())
    report['inputs']={str(p.relative_to(SOURCE)):sha(p) for p in list(MUSASHI.glob('*.*'))+[SOURCE/'Src/Sound/SCSPDSP.cpp',SOURCE/'Src/Sound/SCSPDSP.h',SOURCE/'Src/Model3/SoundBoard.cpp',SOURCE/'Src/Model3/Model3.cpp',SOURCE/'Config/Games.xml']}
    report['outputs']={str(p.relative_to(args.output)):sha(p) for p in sorted(args.output.rglob('*')) if p.suffix in ('.c','.cpp','.h') and 'musashi-original' not in str(p)}
    (args.output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    summary={k:dict(report[k]) for k in ('m68k','scspdsp')}
    summary['scspdsp'].pop('program_sha256')
    print(json.dumps(summary,indent=2))


if __name__=='__main__': main()

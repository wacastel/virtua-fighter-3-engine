#!/usr/bin/env python3
"""Offline-specialize the supplied Virtua Fighter 3 billboard-board Z80 ROM."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import zlib
from pathlib import Path
from compile_ppc import ROOT, PIN, block, exact_replace, sha

ROM_NAME = "epr-18022.ic2"
ROM_CRC32 = 0x0ca70f80
ROM_SHA256 = "111427213e2635b18753cbfb7cc4a0bffdd7c71cedec5cacadb11eec0211afda"
MAPPED_ROM_BYTES = 0x9000  # Pinned CDriveBoard::Read8; BillBoard inherits it.


def verified_rom(game: Path, explicit: Path | None = None) -> tuple[Path, bytes]:
    path = (explicit or game / ROM_NAME).resolve()
    rom = path.read_bytes()
    if len(rom) != 0x10000 or zlib.crc32(rom) != ROM_CRC32 or hashlib.sha256(rom).hexdigest() != ROM_SHA256:
        raise ValueError(f"Wrong Virtua Fighter 3 billboard ROM: {path}")
    return path, rom


def without_comments(source: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: "\n" * m.group().count("\n"), source, flags=re.S)


def cases(source: str, start: int) -> tuple[dict[int | None, str], int]:
    first, end = block(source, start)
    content = source[first + 1:end - 1]
    depth, at, labels = 0, 0, []
    for match in re.finditer(r"\bcase\s+(0[xX][0-9a-fA-F]+|[0-9]+)\s*:|\bdefault\s*:", content):
        for char in content[at:match.start()]:
            depth += (char == "{") - (char == "}")
        at = match.end()
        if depth == 0:
            labels.append((int(match[1], 0) if match[1] else None, match.start(), match.end()))
    result = {}
    for index, (value, _, begin) in enumerate(labels):
        stop = labels[index + 1][1] if index + 1 < len(labels) else len(content)
        body = content[begin:stop].strip()
        result[value] = body
    return result, end


def strip_break(source: str) -> str:
    return re.sub(r"\bbreak;\s*$", "", source).strip()


def expand_branch_macro(source: str, name: str, make) -> str:
    while match := re.search(r"\b" + name + r"\(", source):
        begin = match.end()
        depth, end = 1, begin
        while depth:
            depth += (source[end] == "(") - (source[end] == ")")
            end += 1
        source = source[:match.start()] + make(source[begin:end - 1]) + source[end:]
    return source


def operation(source_cases: dict, sequence: bytes) -> str:
    code = strip_break(source_cases[sequence[0]])
    consumed = 1
    preamble = "++pc;\n"
    fixed_op = sequence[0]
    if sequence[0] in (0xdd, 0xed, 0xfd):
        sub, _ = cases(code, code.index("switch (op)"))
        code = strip_break(sub.get(sequence[1], sub.get(None, "")))
        preamble += "++pc;\n"
        consumed = 2
        fixed_op = sequence[1]
    code = expand_branch_macro(code, "Jpc", lambda cond: f"pc = ({cond}) ? GetWORD(pc) : pc+2")
    code = expand_branch_macro(code, "CALLC", lambda cond:
        f"{{ if ({cond}) {{ unsigned int adrr=GetWORD(pc); PUSH(pc+2); pc=adrr; }} else pc+=2; }}")
    # Preserve reads from data addresses, while replacing every instruction-stream
    # read with the specific verified bytes and the original PC increment.
    def replace_fetch(match):
        nonlocal consumed
        kind = match[1]
        if kind == "WORD":
            value = sequence[consumed] | sequence[consumed + 1] << 8
            return f"0x{value:04x}U"
        value = sequence[consumed]
        if kind == "BYTE_pp":
            consumed += 1
            return f"(++pc, 0x{value:02x}U)"
        return f"0x{value:02x}U"
    code = re.sub(r"Get(WORD|BYTE_pp|BYTE)\(pc\)", replace_fetch, code)
    # CB nested selector switches now take a compile-time literal. Their shared
    # flag labels and exact arithmetic are retained, and compile away at -O2.
    if sequence[0] == 0xcb or (sequence[0] in (0xdd, 0xfd) and sequence[1] == 0xcb):
        fixed_op = sequence[1] if sequence[0] == 0xcb else sequence[3]
        code = re.sub(r"\bop\s*=\s*0x[0-9a-f]+U;", "", code)
        code = re.sub(r"\bop\b", f"0x{fixed_op:02x}U", code)
    else:
        # CPIR/CPDR reuse op for a runtime flag; that flag is architectural data.
        preamble += f"op=0x{fixed_op:02x}U;\n"
    if re.search(r"Get(?:WORD|BYTE_pp|BYTE)\(pc\)", code):
        raise ValueError("Runtime instruction operand fetch remains")
    return preamble + code


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream", type=Path, default=ROOT / "build/upstream/supermodel")
    p.add_argument("--game", type=Path, required=True)
    p.add_argument("--rom", type=Path, help="Explicit shared billboard ROM when it is outside the game directory")
    p.add_argument("--output", type=Path, default=ROOT / "build/generated/z80")
    a = p.parse_args()
    cpu = a.upstream.resolve() / "Src/CPU/Z80"
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    _, rom = verified_rom(a.game, a.rom)
    original = (cpu / "Z80.cpp").read_text()
    clean = without_comments(original)
    start = clean.index("  switch(op) {")
    op_cases, end = cases(clean, start)
    if len(op_cases) != 256:
        raise ValueError("Pinned Z80 base opcode cases changed")
    sequences, mapping = [], {}
    address_ids = []
    # BillBoard inherits CDriveBoard's ROM0..8fff and RAMe000..ffff map.
    # Preserve that pinned map (including its upstream TODO about 0x7fff).
    image = rom[:MAPPED_ROM_BYTES] + b"\xff" * 3
    bodies = []
    for pc in range(MAPPED_ROM_BYTES):
        sequence = image[pc:pc + 4]
        if sequence not in mapping:
            mapping[sequence] = len(sequences)
            sequences.append(sequence)
            bodies.append(operation(op_cases, sequence))
        address_ids.append(mapping[sequence])
    generated = ["\n// Fixed ROM addresses, exact four-byte identity guards, no instruction decoder.\n",
                 "static const unsigned char vf3_z80_words[][4] = {\n"]
    generated += ["{" + ",".join(map(str, sequence)) + "},\n" for sequence in sequences]
    generated.append("};\nstatic const unsigned short vf3_z80_program[0x9000] = {\n")
    for base in range(0, len(address_ids), 64):
        generated.append(",".join(map(str, address_ids[base:base + 64])) + ",\n")
    generated.append("};\n")
    dispatch = ["  if (pc >= 0x9000) throw std::runtime_error(\"Untranslated Virtua Fighter 3 Z80 PC\");\n",
                "  const unsigned fixed_id=vf3_z80_program[pc];\n",
                "  for (unsigned byte=0;byte<4;++byte) if (GetBYTE(pc+byte)!=vf3_z80_words[fixed_id][byte])\n",
                "    throw std::runtime_error(\"Changed Virtua Fighter 3 Z80 instruction\");\n",
                "  switch(fixed_id) {\n"]
    for index, body in enumerate(bodies):
        body = re.sub(r"\bcbshflg([123])\b", lambda m: f"cbshflg{m[1]}_{index}", body)
        dispatch.append(f"case {index}: {{\n{body}\n break; }}\n")
    dispatch.append("  }\n")
    original_start = original.index("  op = GetBYTE_pp(pc);", original.index("int CZ80::Run"))
    original_switch = original.index("  switch(op) {", original_start)
    _, original_end = block(original, original_switch)
    native = original[:original_start] + "".join(dispatch) + original[original_end:]
    insert = native.index("int CZ80::Run")
    native = native[:insert] + "".join(generated) + native[insert:]
    native = native.replace('#include "Z80.h"', f'#include "{cpu / "Z80.h"}"\n#include <stdexcept>')
    (out / "Z80.cpp").write_text(native)
    manifest = {"format": 1, "cpu": "billboard-board Z80", "upstreamCommit": PIN, "romName": ROM_NAME,
                "romBytes": len(rom), "romCRC32": f"{ROM_CRC32:08x}", "romSHA256": hashlib.sha256(rom).hexdigest(),
                "sourceSHA256": sha(cpu / "Z80.cpp"), "generatorSHA256": sha(Path(__file__)),
                "sourceHeaderSHA256": sha(cpu / "Z80.h"),
                "boardSources": {str(p.relative_to(a.upstream.resolve())): sha(p) for p in [cpu.parent.parent/'Model3/DriveBoard/DriveBoard.cpp',cpu.parent.parent/'Model3/DriveBoard/BillBoard.cpp']},
                "outputSHA256": sha(out / "Z80.cpp"), "fixedStarts": len(address_ids), "fixedVariants": len(sequences),
                "scope": "All 0x9000 ROM byte starts of the pinned billboard map; four-byte guards including unmapped FF after 8fff; fixed generated operands; RAM execution fails closed; inherited interrupt modes, HALT and prefix behavior."}
    (out / "translation-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(out), **manifest}))


if __name__ == "__main__":
    main()

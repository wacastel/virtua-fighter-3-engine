#!/usr/bin/env python3
"""Specialize pinned Virtua Fighter 3 PowerPC operations and operands offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = "24d2ffcfc7f14229337f05f4920fe26b56633d9d"
ROM_FILES = [
    ("epr-19230d.20", 0x43C08240, "18c9d8e94e8c7f42bccbf9eccb2d195e792ca3ba527266e2de1c1fe3fadf185f"),
    ("epr-19229d.19", 0x6773F715, "12e2f266a055824e52b6b2463fe516cbad60c648fb7971bfeda00d2e82ce1615"),
    ("epr-19228d.18", 0xA2470C78, "e6b4d25104c41c4ee1d86df512cf68aa97035b1f92e8df5ff7c5ed97304d33ca"),
    ("epr-19227d.17", 0x8B650966, "36ff587199304ad19c49c97537bae931f76bc2ecb2e1b02d2ec9e1866e4f3e95"),
]
PROGRAM_ROM_BASE = 0xffe00000
PROGRAM_BYTES = 0x200000
# The authenticated reset loop at fff00198 copies 0x28000 words from
# fff10000 to RAM zero, then branches to 0x100. This is VF3's code copy.
RAM_COPY_BYTES = 0xa0000
RAM_COPY_PROGRAM_OFFSET = 0x110000



def verify_invincibility_contexts(rom: bytes) -> dict:
    path = ROOT / "Configuration/invincibility-ppc.json"
    config = json.loads(path.read_text())
    if config["upstreamCommit"] != PIN:
        raise ValueError("Invincibility source pin changed")
    for context in config["contexts"]:
        first, end = int(context["firstPC"], 0), int(context["endPC"], 0)
        actual = hashlib.sha256(rom[0x710000 + first:0x710000 + end]).hexdigest()
        if actual != context["sha256"]:
            raise ValueError(f"Original invincibility context changed at {first:08x}")
    if struct.unpack_from(">I", rom, 0x710000 + 0x104a4)[0] != 0x7d445051:
        raise ValueError("Original incoming-damage subtraction changed")
    return {"implemented": True, "configuration": str(path.relative_to(ROOT)),
            "configurationSHA256": sha(path), "entry": config["entry"],
            "contexts": config["contexts"], "predicate": config["predicate"]}

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def block(text: str, start: int) -> tuple[int, int]:
    first = text.index("{", start)
    depth, end = 1, first + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return first, end


def exact_replace(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f"Pinned source boundary changed: {old[:80]!r}")
    return text.replace(old, new)


def decode_tables(source: str, ops_header: str) -> dict[tuple[int, int], str]:
    result = {}
    for major, minor, fn in re.findall(r"\{\s*(\d+),\s*([^,]+),\s*(ppc_\w+)\s*\}", ops_header):
        if not re.fullmatch(r"[\d\s|+-]+", minor):
            raise ValueError("Unexpected table expression")
        result[int(major), int(eval(minor, {"__builtins__": {}}, {}))] = fn
    for table, code, fn in re.findall(r"optable(19|31|59|63)?\[(\d+)\]\s*=\s*(ppc_\w+);", source):
        result[(int(table), int(code)) if table else (int(code), -1)] = fn
    for table, code, fn in re.findall(r"optable(59|63)\[i \* 32 \| (\d+)\]\s*=\s*(ppc_\w+);", source):
        for i in range(32):
            result[int(table), i * 32 | int(code)] = fn
    return result


def handler(tables: dict, word: int) -> str | None:
    major = word >> 26
    return tables.get((major, (word >> 1) & 1023 if major in (19, 31, 59, 63) else -1))


def verified_rom(game: Path) -> tuple[bytes, list[dict]]:
    data = bytearray(0x800000)
    identities = []
    for lane, (name, crc, digest) in enumerate(ROM_FILES):
        path = game / name
        raw = path.read_bytes()
        if len(raw) != 0x80000 or zlib.crc32(raw) != crc or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"Wrong Virtua Fighter 3 Japan Revision D ROM: {path}")
        # The pinned loader swaps each source halfword while interleaving four lanes.
        # Its 2 MiB CROM region is loaded at the top of the fixed 8 MiB window.
        # The lower 6 MiB contains banked CROM data, not admitted by this image.
        data[0x600000 + lane * 2::8] = raw[1::2]
        data[0x600000 + lane * 2 + 1::8] = raw[0::2]
        identities.append({"name": name, "size": len(raw), "crc32": f"{crc:08x}", "sha256": sha(path)})
    return bytes(data), identities


def static_word_at(pc: int, words: tuple[int, ...]) -> int | None:
    if pc & 3:
        return None
    if PROGRAM_ROM_BASE <= pc <= 0xfffffffc:
        return words[(pc - PROGRAM_ROM_BASE) >> 2]
    if 0 <= pc < RAM_COPY_BYTES:
        return words[(RAM_COPY_PROGRAM_OFFSET + pc) >> 2]
    return None


def observed(paths: list[Path]) -> dict[int, set[int]]:
    result: dict[int, set[int]] = {}
    for path in paths:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 2:
                raise ValueError(f"Bad observation {path}:{number}")
            pc, word = (int(x, 16) for x in fields)
            if pc & 3 or not (0 <= pc < 0x800000 or 0xff800000 <= pc <= 0xfffffffc) or not 0 <= word <= 0xffffffff:
                raise ValueError(f"Out-of-range observation {path}:{number}")
            result.setdefault(pc, set()).add(word)
    return result


def ram_images(specifications: list[str], tables: dict) -> tuple[dict[int, set[int]], list[dict]]:
    result: dict[int, set[int]] = {}
    manifest = []
    for specification in specifications:
        address, filename = specification.split(":", 1)
        base, path = int(address, 0), Path(filename).resolve()
        data = path.read_bytes()
        if base & 3 or len(data) & 3 or base < 0 or base + len(data) > 0x800000:
            raise ValueError(f"Invalid fixed RAM image range: {specification}")
        admitted = 0
        for offset in range(0, len(data), 4):
            word = struct.unpack_from(">I", data, offset)[0]
            if handler(tables, word) is not None:
                result.setdefault(base + offset, set()).add(word)
                admitted += 1
        manifest.append({"base": f"0x{base:08x}", "bytes": len(data), "sha256": sha(path), "path": str(path), "admittedWords": admitted})
    return result, manifest


def verify_image_observations(observations: dict[int, set[int]], images: list[dict]) -> list[dict]:
    """An immutable image must agree with every observed execution in its range."""
    checks = []
    for entry in images:
        data = Path(entry['path']).read_bytes()
        base = int(entry['base'], 16)
        addresses = identities = 0
        for pc, words in observations.items():
            if base <= pc < base + len(data):
                expected = struct.unpack_from('>I', data, pc - base)[0]
                if words != {expected}:
                    raise ValueError(f"Observed PPC identity disagrees with fixed RAM image at {pc:08x}: "
                                     f"expected {expected:08x}, observed {sorted(words)}")
                addresses += 1
                identities += len(words)
        checks.append({'base': entry['base'], 'bytes': len(data), 'imageSHA256': entry['sha256'],
                       'observedAddresses': addresses, 'observedIdentities': identities, 'allMatch': True})
    return checks


def observer_source(source: str, executor: str, cpu: Path, out: Path) -> None:
    hook = (ROOT / "Tools/ReferenceLab/ppc_observer.inc").read_text()
    executor = exact_replace(executor, "\t\tppc.npc = ppc.pc + 4;", "\t\tppc.npc = ppc.pc + 4;\n\t\tvf3_ppc_observe(ppc.pc, opcode);")
    source = exact_replace(source, '#include "ppc603.c"', hook + "\n" + executor)
    for name in ("ppc.h", "ppc_ops.c", "ppc_ops.h"):
        source = source.replace(f'#include "{name}"', f'#include "{cpu / name}"')
    (out / "ppc-observer.cpp").write_text(source)


def native_source(source: str, executor: str, operations: str, cpu: Path, out: Path,
                  tables: dict, rom: bytes, observations: dict[int, set[int]], trace_only: bool) -> dict:
    # The 2 MiB CROM maps at ffe00000. VF3's authenticated reset loop copies
    # fff10000..fffaffff to RAM0..9ffff. Every admitted address checks exact
    # instruction identity; other uploads require independent offline evidence.
    static_words = () if trace_only else struct.unpack(">524288I", rom[0x600000:])
    variants = {pc: set(words) for pc, words in observations.items()}
    for pc, words in list(variants.items()):
        for word in words:
            if handler(tables, word) is None:
                raise ValueError(f"Observed unsupported opcode {word:08x} at {pc:08x}")
    supported = {word for word in static_words if handler(tables, word) is not None}
    supported.update(word for words in variants.values() for word in words)
    unique = sorted(supported)
    ids = {word: index + 1 for index, word in enumerate(unique)}
    # Separate fixed templates instantiate the original arithmetic/bus semantics
    # with an encoded word known at compilation. No handler accepts an opcode.
    operations, count = re.subn(r"static void (ppc_\w+)\(UINT32 op\)",
                                r"template<UINT32 op> static void \1()", operations)
    if count < 100:
        raise ValueError("Pinned operation declarations changed")
    operations = operations.replace("ppc_unimplemented(op);", "ppc_unimplemented<op>();")
    # The upstream expression shifts a 32-bit value by 32 when SH=0. Dynamic
    # arm64 execution masks this shift, but constexpr specialization exposes C++
    # undefined behavior. Express the identical PowerPC zero-rotate explicitly.
    if operations.count("(rs << sh) | (rs >> (32-sh))") != 3:
        raise ValueError("Pinned rotate expressions changed")
    operations = operations.replace("(rs << sh) | (rs >> (32-sh))", "(rs << sh) | (rs >> ((32-sh) & 31))")
    if re.search(r"\bppc_\w+\(op\)", operations):
        raise ValueError("Unspecialized instruction call remains")
    invincibility = verify_invincibility_contexts(rom)
    assist = '''
extern "C" bool vf3_player_one_invincible();
static void vf3_ppc_incoming_damage() {
 const UINT32 damage = ppc.r[4];
 const bool protect = vf3_player_one_invincible()
     && ppc.pc == 0x000104a4 && ppc.r[13] == 0x00108000
     && INT32(ppc.r[10]) > 0 && ppc.r[10] <= 0xffff && INT32(damage) > 0
     && ppc.r[14] >= 0x00100000 && ppc.r[14] <= 0x001ff000
     && ppc.r[14] == READ32(0x00102108) && READ8(ppc.r[14] + 4) == 0
     && READ32(0x00102008) == 0x07090709
     && (READ8(0x00106029) == 1 || READ8(0x00106029) == 3);
 // Preserve the original arithmetic implementation and flags for zero damage.
 // The original operand register is restored; no RAM or program writes occur.
 if (protect) ppc.r[4] = 0;
 ppc_subfx<0x7d445051U>();
 if (protect) ppc.r[4] = damage;
}
'''
    generated = [operations, assist, "\nstruct VF3PPCOperation { UINT32 word; void (*run)(); };\n",
                 "static const VF3PPCOperation vf3_ppc_operations[] = {\n{0,nullptr},\n"]
    generated += [f"{{0x{word:08x}U, &vf3_ppc_incoming_damage}},\n" if word == 0x7d445051 else
                  f"{{0x{word:08x}U, &{handler(tables, word)}<0x{word:08x}U>}},\n" for word in unique]
    generated.append("};\n")
    if static_words:
        generated.append("static const UINT32 vf3_ppc_program[524288] = {\n")
        for base in range(0, len(static_words), 32):
            generated.append(",".join(str(ids.get(word, 0)) for word in static_words[base:base + 32]) + ",\n")
        generated.append("};\n")
    # Sparse page tables keep lookup constant-time without a 4 GiB dispatch map.
    pages = {}
    for pc, words in variants.items():
        expected = None
        if static_words:
            expected = static_word_at(pc, static_words)
        extra = sorted(word for word in words if word != expected)
        if extra:
            pages.setdefault(pc >> 16, {})[(pc & 0xffff) >> 2] = extra
    generated.append("struct VF3PPCVariant { UINT32 operation; UINT32 next; };\n")
    chains = [(0, 0)]
    for page, entries in sorted(pages.items()):
        heads = [0] * 16384
        for slot, words in sorted(entries.items()):
            head = 0
            for word in words:
                chains.append((ids[word], head))
                head = len(chains) - 1
            heads[slot] = head
        generated.append(f"static const UINT32 vf3_ppc_page_{page:04x}[16384] = {{\n")
        for base in range(0, len(heads), 64):
            generated.append(",".join(map(str, heads[base:base + 64])) + ",\n")
        generated.append("};\n")
    generated.append("static const VF3PPCVariant vf3_ppc_variants[] = {\n")
    generated += [f"{{{operation},{nxt}}},\n" for operation, nxt in chains]
    generated.append("};\nstatic inline const UINT32 *vf3_ppc_page(UINT32 page) {\n switch(page) {\n")
    generated += [f"case 0x{page:04x}: return vf3_ppc_page_{page:04x};\n" for page in sorted(pages)]
    generated.append("default: return nullptr;\n }\n}\n")
    generated.append("static void vf3_ppc_fixed(UINT32 pc, UINT32 actual) {\n if (!(pc & 3)) {\n")
    if static_words:
        generated.append(" if (pc < 0xa0000 || pc >= 0xffe00000) {\n"
                         "  const UINT32 offset = pc < 0xa0000 ? 0x110000 + pc : pc - 0xffe00000;\n"
                         "  const auto &entry = vf3_ppc_operations[vf3_ppc_program[offset >> 2]];\n"
                         "  if (entry.run && actual == entry.word) { entry.run(); return; }\n }\n")
    generated.append(" if (const UINT32 *page=vf3_ppc_page(pc >> 16)) {\n"
                     "  for (UINT32 id=page[(pc & 0xffff) >> 2]; id; id=vf3_ppc_variants[id].next) {\n"
                     "   const auto &entry=vf3_ppc_operations[vf3_ppc_variants[id].operation];\n"
                     "   if (actual == entry.word) { entry.run(); return; }\n  }\n }\n }\n"
                     ' ErrorLog("Untranslated Virtua Fighter 3 PowerPC instruction at %08X: %08X", pc, actual);\n'
                     ' ppc.fatalError=true;\n throw std::runtime_error("Untranslated or changed Virtua Fighter 3 PowerPC instruction");\n}\n')
    # Preserve precise original scheduler, exception, timer and interrupt behavior.
    switch_start = executor.index("\t\tswitch(opcode >> 26)")
    _, switch_end = block(executor, switch_start)
    executor = executor[:switch_start] + "\t\tvf3_ppc_fixed(ppc.pc, opcode);" + executor[switch_end:]
    executor = exact_replace(executor, "\treturn executed;", '\tif (ppc.fatalError) throw std::runtime_error("Virtua Fighter 3 PowerPC hardware fault");\n\treturn executed;')
    # Function definitions must precede their fixed dispatcher, and executor last.
    source = re.sub(r"^static void \(\* optable(?:19|31|59|63)?\[\d+\]\)\(UINT32\);\n", "", source, flags=re.M)
    source = exact_replace(source, '#include "ppc603.c"', "\n".join(generated) + "\n" + executor)
    source = exact_replace(source, '#include "ppc_ops.c"', "")
    source = exact_replace(source, '#include "ppc_ops.h"', "")
    base = source.index("void ppc_base_init(void)")
    first = source.index("\tfor( i=0; i < 64; i++ )", base)
    last = source.index("\t/* Calculate rotate mask table */", first)
    source = source[:first] + source[last:]
    start = source.index("\toptable[48] = ppc_lfs;")
    loop = source.index("\tfor(i = 0; i < 32; i++)", start)
    _, end = block(source, loop)
    # There are two loops in ppc_init: opcode aliases followed by PLL tables.
    source = source[:start] + source[end:]
    source = source.replace('#include "ppc.h"', f'#include "{cpu / "ppc.h"}"\n#include <stdexcept>')
    if re.search(r"\boptable|opcode\s*>>", source):
        raise ValueError("Runtime opcode decoder remains")
    (out / "ppc.cpp").write_text(source)
    return {"fixedOperations": len(unique), "staticProgramWords": len(static_words),
            "observedAddresses": len(observations), "observedVariants": sum(map(len, observations.values())),
            "extraVariants": len(chains) - 1, "extraPages": len(pages), "templateHandlers": count, "invincibility": invincibility}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, default=ROOT / "build/upstream/supermodel")
    parser.add_argument("--game", type=Path)
    parser.add_argument("--observations", type=Path, nargs="*", default=[])
    parser.add_argument("--ram-image", action="append", default=[], metavar="ADDRESS:PATH",
                        help="Exact offline reference upload image, big-endian words; address must lie in RAM")
    parser.add_argument("--output", type=Path, default=ROOT / "build/generated/ppc")
    parser.add_argument("--observer-only", action="store_true")
    parser.add_argument("--trace-only", action="store_true", help="Small laboratory fixture; omits static ROM/RAM expansion")
    args = parser.parse_args()
    cpu = args.upstream.resolve() / "Src/CPU/PowerPC"
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, executor, operations, ops_header = [(cpu / name).read_text() for name in ("ppc.cpp", "ppc603.c", "ppc_ops.c", "ppc_ops.h")]
    observer_source(source, executor, cpu, out)
    if args.observer_only:
        print(json.dumps({"observer": str(out / "ppc-observer.cpp")}))
        return
    if not args.game:
        parser.error("--game is required for native generation")
    rom, media = verified_rom(args.game)
    tables = decode_tables(source, ops_header)
    identities = observed(args.observations)
    uploads, upload_manifest = ram_images(args.ram_image, tables)
    upload_checks = verify_image_observations(identities, upload_manifest)
    for pc, values in uploads.items():
        identities.setdefault(pc, set()).update(values)
    stats = native_source(source, executor, operations, cpu, out, tables, rom, identities, args.trace_only)
    manifest = {"format": 1, "cpu": "PowerPC 603R", "upstreamCommit": PIN,
                "generatorSHA256": sha(Path(__file__)), "media": media,
                "originalSources": {name: sha(cpu / name) for name in ("ppc.cpp", "ppc603.c", "ppc_ops.c", "ppc_ops.h", "ppc.h")},
                "observations": [{"path": str(path), "sha256": sha(path)} for path in args.observations],
                "fixedRAMImages": upload_manifest,
                "ramImageObservationChecks": upload_checks,
                "outputSHA256": sha(out / "ppc.cpp"), **stats,
                "scope": "Exact fixed program addresses plus observed fixed reset/upload variants; instruction identity guards fail closed; no runtime decoding, dynamic compilation, or interpreter fallback.",
                "staticRanges": [] if args.trace_only else ["0xffe00000..0xffffffff", "0x00000000..0x0009ffff guarded copy of ROM0xfff10000..0xfffaffff"],
                "ramCopy": {"source": "0xfff10000", "destination": "0x00000000", "bytes": RAM_COPY_BYTES,
                            "bootLoopPC": "0xfff00198", "bootLoopSHA256": hashlib.sha256(rom[0x700198:0x7001c8]).hexdigest()},
                "processorConfiguration": {"sourceModel": "PPC_MODEL_603R", "stepping": "1.0", "busMHz": 66, "multiplier": 1}}
    (out / "translation-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(out), **stats}))


if __name__ == "__main__":
    main()

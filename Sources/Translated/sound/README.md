# Fixed Virtua Fighter 3 sound programs

The target is Virtua Fighter 3 Japan Revision D (`vf3`), using the original
Supermodel sources pinned by `scripts/prepare_source.py`. The sound hardware is
one SCSP-board 68000 and two SCSP DSPs. This game has no MPEG/DSB daughterboard;
any attempt to execute a second sound-board CPU is rejected by the native
program lookup.

The verified program is `epr-19231.21`, exactly 524,288 bytes, CRC32 `b416fe96`,
SHA-256 `33b02da29908f4b348c3442ecd2118ffafba8bb6ebcae862ffe708f58ab15a0a`.
The original loader and board accessors expose raw little-endian halfwords as
68000 instruction words. All 262,144 aligned words are bound offline to compiled
operations at `0x600000..0x67ffff`; the board's `0x680000..0x6fffff` mirror uses
the same entries. The entire window contains verified VF3 program data. There
is no inherited short-ROM zero padding or dummy second-board program.

`compile_sound.py` performs Musashi's operation-table selection offline and
specializes every encoded operand into generated C. The native CPU chooses an
entry by the original instruction address and authenticates both opcode and
extension words before execution. Indexed extension operands are likewise
fixed. Captured RAM execution, if present, must have one consistent instruction
identity at each admitted address. Unknown addresses, modified instructions,
odd addresses and absent sound boards fail explicitly. Native execution has no
original opcode table, decoder, dynamic compiler or interpreter fallback.

SCSP DSP program observations establish a separate byte vocabulary at each of
128 instruction slots and each of the eight byte positions within a slot. Zero
reset memory is included. The pinned `CSoundBoard::Write8/16/32` methods reach
`SCSP_w8/16/32`, which update program memory while execution remains enabled;
only the start-register write relatches `LastStep`. A sample can consequently
see a partially completed or interrupted upload. Authenticating only complete
1,024-byte images would incorrectly reject ordinary changes in input timing.

The compiler enumerates the finite Cartesian product of those known bytes at
each exact slot **offline**. Every admitted four-word instruction, including
possible byte/word upload fragments, becomes a constant operation body. This is
an explicit expansion from observed whole images: new combinations of known
bytes at their observed positions are supported. It does not permit arbitrary
instructions, new byte values, or moving an instruction to an unsupported slot.
The product compares the full 64-bit instruction identity at every executing
slot on every sample, then calls its precompiled body. Per-slot cached pointers
avoid repeated searches while retaining the identity check. No opcode fields
are extracted, no operation is generated, and no interpreter runs at runtime.

Scratch registers and delayed memory values persist across slots within a
sample. `LastStep`, zero-length uploads, early returns and sample-memory effects
retain the pinned implementation's behavior. Unknown executing quads or invalid
limits fail explicitly. The SCSP slots, registers, mixing, interrupts and
original scheduling remain the pinned hardware implementation.

`VF3_SOUND_CAPTURE` selects the observer JSONL output. Each CPU observation
records board, PC and twelve fetched words; each DSP observation records the
complete image. Current-game boot, menus, fighting, stage/round transitions and
restart observations should be merged with their source identities before final
generation. Local captures, generated operation arrays and compiled outputs stay
under ignored `build/`. No Daytona program captures or acceptance records are
reused for VF3.

`verify_sound.py` independently compiles the original and fixed processors. It
compares every distinct verified ROM word as an instruction in two register/flag
states, representative mirrored addresses, the full state and sample RAM of
captured DSP images, latched execution limits and synthetic DSP programs. It
also compares every admitted closure instruction at its original slot in a
nonzero surrounding program, new mixed programs, and persistent DSP sessions
whose cached instructions change without a reset. Negative cases check changed
opcodes and extensions, unknown/odd PCs, absent boards, unknown DSP instructions,
wrong-slot instructions, changed cached instructions and invalid limits. A run without current nonzero DSP captures can
produce only a preliminary local record, not published sound acceptance.
Reference equality remains bounded by these cases; full-game picture/PCM replay,
fresh-context lifecycle and actual output-device checks are separate evidence.

Merge completed captures with `Tools/ReferenceLab/sound_captures.py --run
CAPTURE_JSONL REPLAY_REPORT` repeated for each run. The adjacent inventory binds
each capture, route, replay result, observer library and build-source manifest.
After generation, `verify_sound.py --observations MERGED_JSONL --acceptance
Documentation/sound-acceptance.json` publishes the bounded proof only after
checking that inventory. Without `--acceptance`, the report stays with local
fixture outputs. `--no-build` additionally requires an unchanged fixture-build
receipt and binary hashes. `--held-out CAPTURE_JSONL REPLAY_REPORT` checks a
separate original-processor capture without admitting any of its new identities.
The late-start and challenger regressions contain previously unseen quads, but
all of their bytes are within the earlier sixteen-run vocabulary. Their
provenance and differential results are recorded separately from admission.

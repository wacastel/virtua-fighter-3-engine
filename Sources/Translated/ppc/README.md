# Fixed PowerPC and billboard execution

This target uses the supplied Virtua Fighter 3 Japan Revision D (`vf3`) media.
Original sources remain pinned to Supermodel commit
`24d2ffcfc7f14229337f05f4920fe26b56633d9d` and are not edited in place. The pinned
Step 1.0 implementation configures its PowerPC core as `PPC_MODEL_603R` with a
66 MHz bus and 1× multiplier; the differential fixture uses that configuration.
This describes the selected reference implementation, not physical-board proof.

`scripts/compile_ppc.py` verifies the lengths, CRC32 and SHA-256 of the four
512 KiB program sockets, interleaves their halfwords and applies the loader's
byte order. Their 2 MiB region maps at `0xffe00000..0xffffffff`. The lower 6 MiB
of the hardware's fixed CROM window mirrors banked CROM data; it is not included
in this automatically admitted program region.

VF3's original reset loop at `0xfff00198` copies `0x28000` words from
`0xfff10000` to RAM zero and branches to `0x00000100`. The generated executor
therefore admits `0x00000000..0x0009ffff` as an exact guarded copy of
`0xfff10000..0xfffaffff`. The translation manifest records this source/destination
range and the original loop's hash. Any other executed address or changed word
requires fixed offline evidence from this game. No previous game's uploaded
program or RAM-helper image is reused.

Each supported instruction is a C++ template instance with the entire encoded
operation bound at compilation. Dispatch selects a compiled entry by original
address and checks exact instruction identity. No operation accepts a runtime
opcode. Unknown addresses or changed instructions throw a host-visible fault;
there is no interpreter, runtime decoder or dynamic compilation fallback.
Original scheduling, register, interrupt, exception and bus behavior remains.
Three inherited rotate expressions mask the complementary shift count when the
rotation is zero, preserving the original arm64 behavior without a C++ shift by
32. The processor fixture compares this behavior with the unchanged original.

The optional player-one invincibility assist wraps one authenticated incoming
damage subtraction. The generator verifies the original damage, phase, player
ownership and ring-out contexts recorded in `Configuration/invincibility-ppc.json`.
When enabled for a living human-owned P1 actor in an active round, it executes
the same fixed subtraction with a temporary zero damage operand, then restores
that operand register. No program memory is changed. With the assist off, the
original operation runs without added predicate memory reads. Opponent damage,
ring-out stores and timeouts remain original. The separate invincibility fixture
checks complete processor state and guard failures; ordinary-input gameplay
checks qualify health preservation, ownership, no healing and damage after OFF.

The separately generated `ppc-observer.cpp` belongs only to the reference lab.
Set `VF3_PPC_TRACE` to collect executed address/word identities. `--observations`
admits only those fixed identities, while `--ram-image ADDRESS:PATH` admits
supported starts in an independently captured bounded image of big-endian words.
Observed identities must agree with any supplied immutable image. Runtime code
never reads those captures or discovers new instructions. Images, traces and
generated program arrays remain outside the published source inventory.

`scripts/compile_z80.py` verifies `epr-18022.ic2`, the 64 KiB billboard ROM
identified by CRC32 `0ca70f80` and its recorded SHA-256. The pinned billboard
inherits `CDriveBoard`'s ROM range `0x0000..0x8fff`, unmapped `0xff` reads through
`0xdfff`, and RAM `0xe000..0xffff`. The generator preserves that mapping, including
its upstream TODO about the ROM boundary; it does not silently substitute a
physical-hardware assumption. Every mapped ROM byte start has a fixed operation,
constant instruction operands and a four-byte guard. Guard bytes past `0x8fff`
use the original unmapped value. RAM instruction execution fails explicitly.
Inherited prefix, interrupt and HALT behavior remains. `--rom PATH` can name the
shared billboard ROM before import; normalized media uses `--game build/media-source`.

`scripts/verify_ppc.py` compares representative arithmetic, branch, floating-point,
flag and bus-write behavior over eight register states, adding supplied fixed
upload variants. `scripts/verify_z80.py` compares all 36,864 mapped billboard ROM
starts in five register/interrupt states through the immediate interrupt boundary:
no pending interrupt, enabled IM0, IM1 and IM2, and NMI. The maskable cases use a
real interrupt-vector callback; IM2 reads its vector through the fixture RAM.
It uses billboard port values and checks rejection of an unknown PC and changes
to each of the four guarded bytes. Both reports bind current generators, fixtures,
original/generated sources, binaries and captured differential results.

The current PowerPC acceptance binds eighteen completed original-processor
captures: extended attract, two-player fighting, arcade and input routes, and
separate paid routes for all twelve fighters, plus delayed-start and challenger
regressions. Their union contains 60,373
executed address/word identities, all matching the fixed ROM or reset RAM copy;
none requires an extra admitted variant. Fighter selection and fight labels were
visually checked against each route. The differential fixture passes 22,512
varied-state comparisons and two rejection checks. Observation hashes and their
static-map comparisons are recorded in the report, and its observation set must
match the product translation manifest. These counts describe the captured and
tested paths only.

Processor tests establish bounded operation comparisons. Full original/native
frame and PCM replay, uploaded-image consistency, rendering, controls and audio
still require their own current-game validation. No prior port's acceptance
counts or completion claims apply to VF3. Original copyright and GPL notices
remain in generated derivatives.

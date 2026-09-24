# Native execution boundary

The app is a single arm64 executable using Apple's AppKit, SpriteKit, AVFoundation, GameController, Foundation and system OpenGL frameworks. A persistent engine thread owns all CGL and Model 3 operations. Rendering returns immutable RGBA snapshots; the main thread handles presentation and UI. A separate audio queue feeds the output device from the same emulated frame clock.

The game is Virtua Fighter 3 Japan Revision D, Model 3 Step 1.0. Four authenticated 512 KiB CROM sockets map to addresses `0xffe00000..0xffffffff`. The reset code copies `0xa0000` bytes from `0xfff10000` to RAM zero. The translator admits the fixed ROM words and matching words in that specific RAM copy. It does not inherit Daytona's RAM mapping or helper code.

The full 512 KiB single-board sound program maps at `0x600000..0x67ffff`, with the hardware mirror at `0x680000..0x6fffff`. Fixed 68000 operations check fetched words and extension data; no DSB second processor is admitted. SCSP instructions are specialized as exact four-word values at their original instruction slots. Its original memory interface allows independently writable bytes during uploads. The offline compiler forms the finite combinations of already observed byte values at each slot and emits constant operation bodies for those exact instructions. This supports upload timing combinations without decoding instruction fields at runtime. Every executing slot checks its exact instruction identity; values outside that static catalog are rejected. The billboard Z80 has its own authenticated shared ROM and fixed execution guard.

Original CPU implementations are used only in isolated observer/reference builds. Their role is to discover exact code identities and compare register/bus effects, RGBA frames, stereo PCM and sample counts. They are not linked into the shipped app as a fallback. The package checks native architecture, system-only dependencies, required fixed symbols and absence of known original processor dispatchers and laboratory symbols.

The pinned upstream archive is extracted and verified byte for byte. All platform, clock, framebuffer, network and sound lifecycle adaptations are derived under `build/`. No supplied ROM or upstream file is edited. An explicit deterministic cabinet clock is used for comparisons; ordinary play samples current UTC at startup and advances it with game frames.

Restart saves cabinet NVRAM, destroys the current context and creates a new one on the owning engine thread. The sound cycle remainder is reset during board initialization to prevent state from leaking between sessions. The app uses its own preferences and save identity, separate from earlier ports.

Player-one invincibility is an optional native-context flag, initially off and
cleared by restart. Triangle or I queues a toggle in the input router; the engine
worker applies it when reserving a frame and publishes its actual state for the
menu and visible indicator. The authenticated fixed PowerPC damage operation
substitutes zero incoming damage only for a living, human-owned player-one actor
during an active round. It retains the original arithmetic flags and restores
the operand register. It does not heal, write game instructions, protect the
opponent, or replace ring-out and timeout rules. The original reference rejects
enabling the assist; separate guarded-operation and gameplay checks qualify the
intentional difference, while ordinary assist-off routes retain reference parity.

On a new bundled interactive launch, the host validates the cabinet save structure
and clears only the two credit banks and their four coin-conversion remainders.
It first preserves an exact SHA-named backup. Scores, settings, EEPROM and
lifetime accounting remain byte-for-byte unchanged by this cleanup. Missing or
already-clear saves need no migration; malformed saves are left unchanged and
reported. In-session restart and diagnostic replay bypass this startup policy.

These choices preserve the existing bounded validation method. Matching the reference does not establish accuracy against physical arcade hardware, and the listed routes do not exhaust every possible input or game state. The DSP instruction boundary is intentionally strict: an instruction outside its slot-specific catalog produces a reported fault instead of falling back to decoding. The finite upload closure admits some combinations not previously observed as complete programs; it is documented and differentially tested, rather than being represented as full-program observation.

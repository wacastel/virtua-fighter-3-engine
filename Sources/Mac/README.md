# Virtua Fighter 3 macOS host

Native AppKit/SpriteKit frontend for the fixed Virtua Fighter 3 Japan Revision D
engine. The host calls the `vf3_*` C ABI and contains no processor decoder or
fallback. It presents the engine's 496×384 RGBA image at the original 4:3 display
aspect and submits signed 16-bit stereo PCM at the engine's queried sample rate.

One persistent engine thread owns creation, every frame, cold restart and
teardown, including the CGL context. The main thread owns SpriteKit and UI input.
Each engine frame reserves both players' input under the routing lock; new taps
arriving while that frame runs remain pending for the next frame. Audio follows
the engine clock independently of display updates. Immutable picture snapshots
cross to the main thread, and each engine iteration drains an autorelease pool.

Reset saves the current cabinet NVRAM, destroys the native context and creates a
fresh context on that same engine thread with the same save directory. It clears
both players' pending controls and player-one invincibility. A processor fault stops the session; reset does
not bypass unknown-instruction checks.

## Controls

The first two assigned controllers control players 1 and 2 independently.
Surviving assignments remain stable when discovery order changes or another
controller connects. Controller player indicators show the assigned slot.

| Action | DualSense, either player | Player 1 keyboard | Player 2 keyboard |
| --- | --- | --- | --- |
| Move / crouch / jump | D-pad or left stick | Arrow keys | W / A / S / D |
| Punch | Square | Z | F |
| Kick | Circle | X | G |
| Guard | Cross | C | H |
| Evade | L1 | V | J |
| Insert coin | R1 | 5 | 6 |
| Start / resume | Options | 1 or Return | 2 |
| Pause / resume | Create, left of the touchpad | P or Escape | P or Escape |
| Player 1 invincibility | Triangle | I | I |

Triangle/I toggles player-one protection independently of both arcade button
masks. The routing lock preserves toggle edges until the engine reserves an
input frame; the engine thread applies the request and publishes its actual
state. A persistent P1 INVINCIBLE indicator and Game menu checkmark reflect
that state. Fresh launch and Reset select OFF. Paused/inactive shortcuts and
held buttons cannot create repeated toggles.

Stick clicks are unassigned. The D-pad overrides both analog movement axes;
analog values within ±0.3 are neutral. Opposing directions cancel independently
for each player. Attacks can be combined, including Punch+Guard and Kick+Guard.

Focus loss, sleep or disconnection of an assigned controller pauses both players
and clears input. Release connected controls to neutral before resuming. A Start
press used to resume is not passed through to the original game. Short taps are
retained until an engine frame, while held fighting buttons remain held across
frames.

## Native input and diagnostic replay

`vf3_step(context, player1, player2)` receives one independent 32-bit mask per
player. Shipping masks contain only these flags:

| Flag | Value |
| --- | ---: |
| Up / Down / Left / Right | 1 / 2 / 4 / 8 |
| Punch / Kick / Guard / Evade | 16 / 32 / 64 / 128 |
| Start / Coin | 256 / 512 |

JSON replay accepts either `steps` with `frames`, `player1`, and `player2`, or
`events` with half-open `start` / `end` frame ranges and optional player masks.
An optional Boolean `invincible` requests the assist state; omission preserves
the last selection, so ending an ON event requires an explicit OFF request.
Active events merge each player's mask in file order; an omitted player retains
the earlier active event's mask. A top-level `frames` value includes a neutral
tail and bounds all events. Masks reject unknown bits. Unknown input/replay
fields are rejected, and absent player fields are neutral. Opposed directions
are normalized before engine submission.

`--diagnostic-run` and `--self-test` execute the real linked native engine and
record picture, PCM and per-block sample-count digests. `--audio-replay` drives
the visible app with the same replay format. Use `--help` for capture, bounded
playback and telemetry options. Tests of these paths establish only the scope
recorded by their current Virtua Fighter 3 reports.

## Build, media and isolation

`scripts/build_host.sh --typecheck` checks all real host sources. `--self-test`
runs the two-player input router against Apple synthetic GameController values,
without linking an engine. `--test-link-guard` rejects reference, diagnostic and
test engine markers and a failed archive-symbol inspection. These checks do not
establish physical controller actuation or game execution.

The app loads `Resources/Media/vf3.zip`, `Games.xml`, and
`media-identity.json`. A verified `default.nv` is optional when provided by the
current game's asset preparation. Both the host and engine validate media
identity. Normal saves and preferences use `local.william.virtuafighter3`;
diagnostic runs use disposable saves unless explicitly overridden.
`--assets DIRECTORY` / `VIRTUA_FIGHTER_3_ASSET_DIR` override media, and
`--save-dir DIRECTORY` / `VIRTUA_FIGHTER_3_SAVE_DIR` override saves. No other
port's saves or preferences are accessed.

New interactive launches clear unused coin/credit state from existing NVRAM
before native context creation, with an exact backup under `Backups` before any
atomic update. Scores, cabinet settings and lifetime accounting are preserved.
In-session Reset and headless/replay sessions bypass this launch-only policy.
See the startup analysis and save-handling acceptance reports for confirmed
fields, validation and preservation checks.

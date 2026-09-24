# Validation workflow

Acceptance reports record exact tested inputs and scope. Build products, instruction traces, audio/video captures and ROM bytes stay under ignored `build/`.

| Layer | Evidence |
| --- | --- |
| Media | `media-acceptance.json`: canonical Revision D sockets and shared billboard ROM |
| PowerPC | `ppc-acceptance.json`: specialized operation state/bus comparisons, guards and observed ROM/RAM mapping |
| Billboard | `z80-acceptance.json`: mapped starts, enabled interrupt modes, NMI and rejection checks |
| Sound | `sound-acceptance.json`: original/fixed 68000, all static SCSP instruction variants, mixed uploads, captured program images, mirror limits and negative guards |
| Integration | `integration-acceptance.json`: each frame's RGBA, PCM and stereo sample count for the listed original/native routes |
| Bridge | `bridge-acceptance.json`: real media/input boundaries and two cold sessions with the same save directory |
| Host routing | `input-acceptance.json`, `typecheck-acceptance.json`, `link-guard-acceptance.json`: actual input code, Swift compilation and refusal to link non-product engines |
| Host replay | `host-acceptance.json`: packaged Swift host/direct-engine agreement and repeated fresh sessions |
| Audio lifecycle | `audio-lifecycle-acceptance.json`: two same-process native sessions against the original reference |
| Package | `package-acceptance.json`: actual architecture, dependencies, signature, source/media identities and processor symbol boundaries |
| Visible app | `live-acceptance.json`: game/display pacing, audio device state, queue limits and zero underruns during the measured interval |
| Independent build | `reproduction-acceptance.json`: fresh source tree, original media/archive only, newly generated translations and replay agreement |
| Damage assist | `invincibility-acceptance.json`: authenticated damage operation, guarded behavior and ordinary-input gameplay with protection enabled |
| Packaged assist | `host-invincibility-acceptance.json`: exact Swift/C ABI picture, audio and assist-state agreement through OFF/ON/OFF, with two fresh sessions |
| Visible controls | `gui-controls-acceptance.json`: actual keyboard/menu toggles, indicator, paused-input behavior, Reset OFF and in-session credit retention |
| Startup credits | `startup-credit-analysis.json`, `startup-host-acceptance.json`, `startup-launch-acceptance.json`: original cabinet fields, narrow backed-up cleanup and actual bundled startup |

The replay set includes a long original attract sequence, paid arcade fighting with loss/continue behavior, local two-player fighting, late start during attract music, joining an active match and one bounded paid fighting route for each of the twelve selectable characters. The original cabinet input test is an observer-only route because service/test controls are deliberately absent from the shipping game-input ABI.

Every fighter route is ordinary input: coins, Start, a sequence of selection movements, then Punch/Kick/Guard/Evade and directional combinations. Selection screenshots were inspected to verify the actual character rather than treating filenames as evidence. The original grid places Wolf before Jeffry; corrected captures are used, and discovery runs with reversed labels are excluded.

Parallel processes are used for deterministic reference comparisons. Their throughput is not a live display benchmark. The visible app test runs separately after competing engine work has stopped. Input unit tests, original cabinet port checks, connected-controller detection and actual physical controller button actuation are different kinds of evidence; the reports do not substitute one for another.

Reference parity is bounded by these routes. It does not prove every possible input sequence, every ending or hidden mode, every controller model, or accuracy against physical Model 3 hardware. Unknown native processor instructions and DSP instructions outside the static slot catalogs remain fatal errors rather than activating an interpreter.

The invincibility update reruns the ordinary gameplay routes with the assist off.
Enabled-assist evidence is separate because preserving player-one health is an
intentional change from the original game. Controller event routing is tested
with the actual host code; this does not claim physical button actuation.
The independent clean reconstruction and unchanged sound-specific reports are
historical baseline evidence, bound to the artifact hashes recorded in them.

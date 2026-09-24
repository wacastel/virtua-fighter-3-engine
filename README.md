# Virtua Fighter 3 for Apple Silicon

A native arm64 macOS application for the locally supplied **Virtua Fighter 3, Japan Revision D** arcade game. The game program is translated offline from verified media, following the Daytona USA 2 port's fixed-execution workflow. An AppKit/SpriteKit host provides video, AVFoundation audio, keyboard controls and up to two GameController controllers.

The source repository contains no ROMs, generated game instructions, saves or bundled game media. Other revisions and Virtua Fighter 3 Team Battle are separate games and are not accepted by this target.

## Play

Open `build/Virtua Fighter 3.app`, or double-click `Play.command`. The original cabinet startup takes about twenty seconds. With factory settings, insert **two coins** for a new game, then press Start.

| Action | PS5 DualSense | Player 1 keyboard | Player 2 keyboard |
| --- | --- | --- | --- |
| Move / crouch / jump | D-pad or left stick | Arrow keys | W / A / S / D |
| Punch | Triangle | Z | F |
| Kick | Circle | X | G |
| Guard | Cross | C | H |
| Evade | Square | V | J |
| Insert coin | R1 | 5 | 6 |
| Start / resume | Options | 1 or Return | 2 |
| Pause / resume | Create | P or Escape | P or Escape |

Controller assignments stay stable for the first two connected controllers. Stick clicks are unassigned. Focus loss or controller disconnection pauses play and clears held controls. The menus provide restart, sound and fullscreen controls. Restart performs a complete cabinet restart while preserving local cabinet settings.

Saves and preferences use the independent `local.william.virtuafighter3` identity. Prior Daytona and Virtua Fighter applications are not changed.

## Build

Requires Apple Silicon, macOS 14 or later, Xcode Command Line Tools and Python 3.11 or later. There are no Homebrew or SDL runtime dependencies.

Place the supplied Revision D set in `Virtua Fighter 3 ROMs/vf3/`. The importer also searches sibling folders for the shared `epr-18022.ic2` billboard ROM, accepts only the expected identities and leaves supplied files unchanged. It creates normalized media under ignored `build/`.

```sh
python3 scripts/prepare_native.py
scripts/build.sh --skip-engine
python3 scripts/verify_package.py
python3 scripts/verify_host.py
python3 scripts/verify_live.py
```

Preparation downloads only the pinned Supermodel **source** archive, verifies every original source file, imports local media, records original-processor routes, generates fixed PowerPC/68000/SCSP DSP/Z80 code, checks instruction semantics, and compares complete native pictures and PCM against the separate reference engine. This is a substantial build and validation run. The first application build must complete before launching.

`Play.command` runs preparation if the app is absent. For a different local ROM directory, pass `--game /path/to/vf3` to `prepare_native.py`. Keep the shared billboard ROM in that directory or a sibling location. Publication scanning uses macOS archive tools to inspect supplied ZIP and 7z contents.

## Execution and validation

The native app contains fixed specialized game instructions and retained Model 3 hardware/graphics code. It does not link the original processor dispatchers, an interpreter fallback, SDL, or a Rosetta executable. Instructions outside the verified static catalogs stop the session with an error. Original processors exist only in separate validation builds.

The PowerPC target uses the game's 2 MiB fixed program window and its authenticated 640 KiB boot copy into RAM. Sound uses the single original 68000 board, its full 512 KiB program and fixed SCSP DSP instruction variants, including byte-wise upload combinations at their original slots. The shared billboard processor is also specialized offline. Upstream source remains unmodified; platform adaptations and generated game-dependent code live under `build/`.

Current-game reports in `Documentation/` describe the tested routes and bind evidence to source, media and executable hashes. Reference agreement establishes those bounded execution paths; it is not an exhaustive proof of every possible game state or a comparison with a physical arcade board. See `Sources/Mac/README.md` for the host threading and input contract and `Documentation/publication.md` for the source publication boundary.

The accepted gameplay set covers **99,058 frames across 17 routes**, with exact per-frame agreement on pictures, stereo audio and sample counts. It includes all twelve selectable fighters, attract mode, paid arcade play with continue behavior, two-player matches, late starts and joining an active match.

An independent clean build reproduced those results. The packaged app's isolated 80-second live check measured 60.025 game frames per second, with zero audio underruns and no engine faults. Controller routing and connected DualSense profile detection are verified; physical controller button actuation is not part of the recorded automated checks.

Supermodel and included components retain their original licenses and notices in `COPYING` and `Licenses/`. Original game content belongs to its respective rights holders.

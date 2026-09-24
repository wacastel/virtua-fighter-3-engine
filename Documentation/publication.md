# Source publication workflow

This port uses the private personal repository
[`wacastel/virtua-fighter-3`](https://github.com/wacastel/virtua-fighter-3)
and the reviewed public source companion
[`wacastel/virtua-fighter-3-engine`](https://github.com/wacastel/virtua-fighter-3-engine).
Both contain source and bounded validation reports. The locally built game and
its supplied media are excluded from both repositories.

The initial release passed all seventeen original/native gameplay comparisons
over 99,058 frames, an independent clean regeneration and rebuild, processor and
host checks, and the packaged app's live display/audio test. The live interval
measured 60.025 game frames per second and zero audio underruns. Exact inputs,
artifact identities and limitations are recorded in the acceptance reports;
publication does not expand those claims.

The subsequent invincibility and startup-credit update rebuilds the native engine
and host, reruns the seventeen ordinary routes, and adds guarded damage,
OFF/ON/OFF packaged replay and backed-up startup-save checks. The initial clean
reconstruction report remains historical evidence for its own artifact hashes.
Current package and live reports identify the updated executable.

The selected target is Virtua Fighter 3 Japan Revision D (`vf3`). Each gameplay,
processor, package, audio and UI claim must come from a current Virtua Fighter 3
report bound to its tested inputs. Prior ports provide implementation methods;
their acceptance reports are not Virtua Fighter 3 evidence.

## Reviewed boundary

`scripts/prepare_publication.py` holds the explicit `REVIEWED_FILES` source list.
It never runs Git, creates a repository or pushes. New files under the controlled
source trees cause an error until their paths are deliberately reviewed and
added. Only actual current-game acceptance reports are admitted. Add processor,
integration, host, package and other qualification reports only after they exist
and have been reviewed. Do not add stale documents merely to satisfy an inventory error.

Both repositories exclude supplied ROMs, ZIP/7z archives, generated program
arrays and instruction maps, local saves, captures and the `build/` tree. The
public companion also excludes local agent instructions. Publication consists
of the reviewed source, build/translation tools, ROM identity metadata, original
component license notices and relevant current-game reports. The app bundle
with locally supplied media remains a local artifact.

## Final preparation

After current-game validation and documentation are complete:

1. Run `python3 scripts/prepare_publication.py --inventory`. This cheap check
   verifies the explicit paths, text extensions and absence of unreviewed files.
   It does not scan media, stage files or make a validation claim.
2. Run `python3 scripts/prepare_publication.py`. It stages only the reviewed
   inventory under `build/publication-review/engine-source`, preserving file
   modes, and writes a manifest binding every source file and the pinned
   upstream source identity.
3. Run `python3 scripts/prepare_publication.py --verify` after staging. It repeats
   the content scan and requires exact agreement with both the working sources
   and staged files. Any source change requires new staging and verification.
4. Review the staged source and report, reproduce the build as required by the
   project's qualification, then create the repositories and commit/push the
   reviewed contents. Keep any publishing checkout separate from the staging
   tree; preparation refuses to delete a staging directory containing `.git`.
5. Verify the remote commit identities and document the tested application and
   source revision. A source scan is not a substitute for game validation.

The complete media scan reads all supplied Virtua Fighter 3 files, every decoded
ZIP and 7z member, nested archive download wrappers, the normalized local ZIP,
optional cabinet seed and generated `.bin` / `.rom` images. It compares complete
identities and searches staged source for complete raw, contiguous hexadecimal
and Base64 media encodings where the media could fit in a source file. It also
requires UTF-8 text, parses Python sources, and checks for local user paths and
credential-shaped strings. It leaves the supplied media unchanged.

This is a bounded source/content check. It does not claim to detect every possible
fragment or encoding of program data, every secret, or every licensing issue.
The explicit source inventory, review and exclusion of all generated instruction
sources remain part of the publication boundary.

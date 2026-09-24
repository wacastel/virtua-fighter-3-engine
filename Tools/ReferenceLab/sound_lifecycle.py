#!/usr/bin/env python3
"""Compare two fresh native game sessions in one process and an earlier trace."""
from pathlib import Path
import argparse
import ctypes as C
import hashlib
import json
import os
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=ROOT / "build/native/libvf3.dylib")
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=2400)
    parser.add_argument("--output", type=Path, default=ROOT / "build/audio-lifecycle/verified")
    args = parser.parse_args()
    if args.frames <= 0:
        raise ValueError('A lifecycle replay must run at least one frame')
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["VF3_RTC_EPOCH"] = "946684800"
    baseline = [json.loads(line) for line in args.baseline.read_text().splitlines()][:args.frames]
    if len(baseline) != args.frames:
        raise RuntimeError("Baseline is shorter than the requested replay")
    library_sha = digest(args.library)
    lib = C.CDLL(str(args.library.resolve()))
    ptr = C.c_void_p
    signatures = {
        "create": ([C.c_char_p, C.c_char_p], ptr), "destroy": ([ptr], None),
        "step": ([ptr, C.c_uint32, C.c_uint32], C.c_int),
        "error": ([ptr], C.c_char_p), "audio": ([ptr], ptr),
        "audio_count": ([ptr], C.c_int), "pixels": ([ptr], ptr),
        "fault_code": ([ptr], C.c_uint32), "frame_number": ([ptr], C.c_uint64),
    }
    for name, (inputs, result) in signatures.items():
        function = getattr(lib, "vf3_" + name)
        function.argtypes, function.restype = inputs, result
    route = json.loads(args.route.read_text())
    runs, summaries = [], []
    started = time.monotonic()
    for run in range(2):
        with tempfile.TemporaryDirectory(prefix="vf3-sound-lifecycle-") as saves:
            context = lib.vf3_create(os.fsencode(ROOT / "build/assets"), os.fsencode(saves))
            if not context:
                raise RuntimeError(lib.vf3_error(None).decode())
            trace, audio, pictures = [], hashlib.sha256(), hashlib.sha256()
            try:
                for frame in range(args.frames):
                    state = dict(player1=0, player2=0)
                    for event in route["events"]:
                        if event["start"] <= frame < event["end"]:
                            state.update({key: value for key, value in event.items() if key in state})
                    if lib.vf3_step(context, state["player1"], state["player2"]) != 1:
                        raise RuntimeError(f"Session {run + 1} frame {frame + 1}: " + lib.vf3_error(context).decode())
                    if lib.vf3_fault_code(context) != 0 or lib.vf3_frame_number(context) != frame + 1:
                        raise RuntimeError(f"Unexpected session {run + 1} state at frame {frame + 1}")
                    count = lib.vf3_audio_count(context)
                    pcm = C.string_at(lib.vf3_audio(context), count * 4)
                    rgba = C.string_at(lib.vf3_pixels(context), 496 * 384 * 4)
                    audio.update(pcm)
                    pictures.update(rgba)
                    trace.append(dict(frame=frame + 1, audioFrames=count,
                                      pcm=hashlib.sha256(pcm).hexdigest(),
                                      rgba=hashlib.sha256(rgba).hexdigest()))
                    if (frame + 1) % 600 == 0:
                        print(f"Session {run + 1}: {frame + 1}/{args.frames} frames", flush=True)
            finally:
                lib.vf3_destroy(context)
            (args.output / f"session-{run + 1}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in trace))
            runs.append(trace)
            summaries.append(dict(pcmSHA256=audio.hexdigest(), rgbaSHA256=pictures.hexdigest()))
    fields = ("audioFrames", "pcm", "rgba")
    differences = {}
    for name, left, right in [("freshSessions", runs[0], runs[1]),
                              ("firstSessionVsBaseline", baseline, runs[0]),
                              ("secondSessionVsBaseline", baseline, runs[1])]:
        mismatches = [{"frame": a["frame"], "fields": [field for field in fields if a[field] != b[field]]}
                      for a, b in zip(left, right) if any(a[field] != b[field] for field in fields)]
        differences[name] = dict(differingFrames=len(mismatches), firstMismatch=mismatches[0] if mismatches else None)
    result = dict(game='vf3', revision='Japan Revision D',
                  passed=all(row["differingFrames"] == 0 for row in differences.values()),
                  framesPerSession=args.frames, sessions=2, processRestartBetweenSessions=False,
                  globalStatePatching=False, freshSavesEachSession=True, librarySHA256=library_sha,
                  verifierSHA256=digest(Path(__file__).resolve()),
                  baselineSHA256=digest(args.baseline), routeSHA256=digest(args.route),
                  clockEpoch=946684800, results=differences, sessionHashes=summaries,
                  elapsedSeconds=round(time.monotonic() - started, 3))
    (args.output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

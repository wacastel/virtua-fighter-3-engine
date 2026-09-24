#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=link
ENGINE='build/native/libvf3.a'
OUTPUT='build/host/VirtuaFighter3'
while [[ $# -gt 0 ]]; do
    case "$1" in
        --typecheck) MODE=typecheck; shift ;;
        --self-test) MODE=selftest; shift ;;
        --test-link-guard) MODE=guardtest; shift ;;
        --engine) [[ $# -ge 2 ]] || { echo '--engine requires a path' >&2; exit 2; }; ENGINE="$2"; shift 2 ;;
        --output) [[ $# -ge 2 ]] || { echo '--output requires a path' >&2; exit 2; }; OUTPUT="$2"; shift 2 ;;
        *) echo 'Usage: scripts/build_host.sh [--typecheck | --self-test | --test-link-guard] [--engine ARCHIVE] [--output EXECUTABLE]' >&2; exit 2 ;;
    esac
done
SDK="$(xcrun --sdk macosx --show-sdk-path)"
FLAGS=(-swift-version 5 -target arm64-apple-macosx14.0 -sdk "$SDK")
if [[ "$MODE" == typecheck ]]; then
    xcrun swiftc "${FLAGS[@]}" -typecheck Sources/Mac/*.swift
    mkdir -p build/host-tests
    python3 - <<'REPORT'
from pathlib import Path
import hashlib,json,subprocess
sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('Sources/Mac').glob('*.swift'))}
result={'passed':True,'mode':'typecheck','engineLinked':False,'appProduced':False,'sources':sources,
        'buildScriptSHA256':hashlib.sha256(Path('scripts/build_host.sh').read_bytes()).hexdigest(),
        'compiler':subprocess.check_output(['xcrun','swiftc','--version'],text=True).strip(),
        'target':'arm64-apple-macosx14.0'}
Path('build/host-tests/typecheck.json').write_text(json.dumps(result,indent=2)+'\n')
print('Virtua Fighter 3 host typecheck passed; no engine linked and no app produced.')
REPORT
elif [[ "$MODE" == selftest ]]; then
    mkdir -p build/host-tests
    xcrun swiftc "${FLAGS[@]}" -O -framework GameController \
        Sources/Mac/Input.swift Sources/Mac/Controls.swift Sources/Mac/Tests/main.swift \
        -o build/host-tests/input-tests
    build/host-tests/input-tests > build/host-tests/input-tests.json
    python3 - <<'REPORT'
from pathlib import Path
import hashlib,json,subprocess
p=Path('build/host-tests/input-tests.json');r=json.loads(p.read_text())
paths=['Sources/Mac/Input.swift','Sources/Mac/Controls.swift','Sources/Mac/Tests/main.swift','scripts/build_host.sh']
r['sources']={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in paths}
r['executableSHA256']=hashlib.sha256(Path('build/host-tests/input-tests').read_bytes()).hexdigest()
r['compiler']=subprocess.check_output(['xcrun','swiftc','--version'],text=True).strip()
r['target']='arm64-apple-macosx14.0'
p.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'passed':r['passed'],'checkCount':r['checkCount'],'report':str(p),'engineLinked':False,'engineStubUsed':False}))
REPORT
elif [[ "$MODE" == guardtest ]]; then
    python3 - <<'GUARD_TEST'
from pathlib import Path
import hashlib,json,os,subprocess,tempfile
root=Path.cwd();directory=root/'build/host-tests/link-guard';directory.mkdir(parents=True,exist_ok=True)
script=root/'scripts/build_host.sh';digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
cases=[]
with tempfile.TemporaryDirectory(prefix='fixtures-',dir=directory) as temporary:
    work=Path(temporary);scratch=work/'tmp';scratch.mkdir()
    for marker in ['vf3_reference_probe_marker','vf3_diagnostic_engine_marker','vf3_test_stub_marker',None]:
        name=marker or 'invalid-archive';archive=work/(name+'.a');output=work/(name+'-must-not-link')
        if marker:
            source=work/(name+'.c');obj=work/(name+'.o')
            source.write_text('void '+marker+'(void) {}\n')
            subprocess.run(['xcrun','clang','-arch','arm64','-mmacosx-version-min=14.0','-c',str(source),'-o',str(obj)],check=True)
            subprocess.run(['/usr/bin/ar','rcs',str(archive),str(obj)],check=True)
            expected='Refusing to link a test, reference or diagnostic engine'
        else:
            archive.write_text('Deliberately invalid archive for the nm failure check.\n')
            expected='Cannot inspect engine symbols'
        result=subprocess.run([str(script),'--engine',str(archive),'--output',str(output)],
                              env=dict(os.environ,TMPDIR=str(scratch)),capture_output=True,text=True,timeout=30)
        assert result.returncode!=0 and expected in result.stderr,(name,result.returncode,result.stderr)
        assert not output.exists(),name+' unexpectedly produced a host executable'
        assert not list(scratch.glob('vf3-host-symbols.*')),name+' leaked its temporary symbol file'
        cases.append({'case':name,'rejected':True,'exitCode':result.returncode,'hostProduced':False,
                      'symbolFileCleaned':True,'archiveSHA256':digest(archive)})
report={'passed':True,'cases':cases,'buildScriptSHA256':digest(script),
        'scope':'Actual build entry rejects marker-bearing arm64 archives and a real nm error before Swift linking; no app rebuilt.'}
(directory/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
GUARD_TEST
else
    test -f "$ENGINE" || { echo "A validated fixed-native engine archive is required: $ENGINE" >&2; exit 1; }
    # Test binaries have no engine at all; no dummy implementation is accepted.
    SYMBOLS="$(/usr/bin/mktemp "${TMPDIR:-/tmp}/vf3-host-symbols.XXXXXX")"
    trap 'rm -f "$SYMBOLS"' EXIT
    if ! /usr/bin/nm -gU "$ENGINE" > "$SYMBOLS"; then
        echo 'Cannot inspect engine symbols; refusing to link an unverified archive.' >&2; exit 1
    fi
    if /usr/bin/grep -E 'vf3_test_stub_marker|vf3_reference_probe_marker|vf3_diagnostic_engine_marker' "$SYMBOLS" >/dev/null; then
        echo 'Refusing to link a test, reference or diagnostic engine into the product host.' >&2; exit 1
    else
        MARKER_STATUS=$?
        if [[ "$MARKER_STATUS" != 1 ]]; then
            echo 'Engine marker inspection failed; refusing to link an unverified archive.' >&2; exit 1
        fi
    fi
    mkdir -p "$(dirname "$OUTPUT")"
    xcrun swiftc "${FLAGS[@]}" -O -framework AppKit -framework SpriteKit \
        -framework AVFoundation -framework GameController -framework CoreGraphics \
        -framework IOKit -framework CoreFoundation -framework OpenGL -framework CoreVideo \
        Sources/Mac/*.swift "$ENGINE" -lc++ -lz -Xlinker -dead_strip -o "$OUTPUT"
    printf 'Linked %s against %s. App packaging is handled by scripts/build.sh.\n' "$OUTPUT" "$ENGINE"
fi

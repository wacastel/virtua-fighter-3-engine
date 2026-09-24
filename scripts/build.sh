#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
SKIP_ENGINE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-engine) SKIP_ENGINE=1; shift ;;
        *) echo 'Usage: scripts/build.sh [--skip-engine]' >&2; exit 2 ;;
    esac
done
if [[ "$SKIP_ENGINE" == 0 ]]; then
    test -f scripts/prepare_native.py || { echo 'Prepare and validate the native engine before packaging with --skip-engine.' >&2; exit 1; }
    python3 scripts/prepare_native.py
fi
python3 - <<'PY'
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'scripts')
from verify_package import verify_engine_sources
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
path=Path('build/native/engine-build-manifest.json')
if not path.is_file():raise SystemExit('A verified fixed-native engine manifest is required.')
manifest=json.loads(path.read_text());archive=Path('build/native/libvf3.a')
if manifest.get('shippingNative') is not True or manifest.get('diagnostics') is not False or manifest.get('kind')!='native':
    raise SystemExit('Refusing a reference, diagnostic or incomplete engine.')
if not archive.is_file() or sha(archive)!=manifest['staticArchiveSHA256']:
    raise SystemExit('Native engine archive identity mismatch.')
verify_engine_sources(manifest)
media=json.loads(Path('build/assets/media-identity.json').read_text())
names={x['path'] for x in media['files']}
if len(names)!=len(media['files']) or names not in ({'vf3.zip','Games.xml'}, {'vf3.zip','Games.xml','default.nv'}):
    raise SystemExit('The verified media inventory is invalid.')
for row in media['files']:
    source=Path('build/assets')/row['path']
    if not source.is_file() or source.stat().st_size!=row['bytes'] or sha(source)!=row['sha256']:
        raise SystemExit('Media changed: '+row['path'])
if not Path('Licenses').is_dir() or not any(p.is_file() for p in Path('Licenses').rglob('*')):
    raise SystemExit('Complete source notices in Licenses are required before packaging.')
PY
mkdir -p build/staging
STAGE="$(mktemp -d "$PWD/build/staging/app.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
APP="$STAGE/Virtua Fighter 3.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/Media"
python3 - "$STAGE/host-sources.json" <<'HOST_SOURCES'
import hashlib,json,sys
from pathlib import Path
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
sources=sorted(Path('Sources/Mac').glob('*.swift'))
packaging=[Path(p) for p in ['scripts/build.sh','scripts/build_host.sh','scripts/build_icon.sh','scripts/build_icon.swift','scripts/verify_package.py','Resources/Info.plist']]
Path(sys.argv[1]).write_text(json.dumps({'hostSources':{str(p):sha(p) for p in sources},'packagingSources':{str(p):sha(p) for p in packaging}},sort_keys=True)+'\n')
HOST_SOURCES
scripts/build_icon.sh
scripts/build_host.sh --engine build/native/libvf3.a --output "$APP/Contents/MacOS/VirtuaFighter3"
cp Resources/Info.plist "$APP/Contents/Info.plist"
cp build/icon/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
cp -R Licenses "$APP/Contents/Resources/Licenses"
python3 - "$APP/Contents/Resources/Media" <<'COPY_MEDIA'
from pathlib import Path
import json,shutil,sys
destination=Path(sys.argv[1]); source=Path('build/assets')
manifest=json.loads((source/'media-identity.json').read_text())
for row in manifest['files']:
    if row['path'] not in {'vf3.zip','Games.xml','default.nv'}:
        raise SystemExit('Unexpected media path')
    shutil.copyfile(source/row['path'],destination/row['path'])
shutil.copyfile(source/'media-identity.json',destination/'media-identity.json')
COPY_MEDIA
codesign --force --sign - "$APP"
codesign --verify --strict "$APP"
python3 - "$APP" "$STAGE/host-sources.json" <<'PY'
import hashlib,json,plistlib,shutil,sys
from pathlib import Path
source=Path(sys.argv[1]);destination=Path('build/Virtua Fighter 3.app')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
inputs=json.loads(Path(sys.argv[2]).read_text())
if set(inputs['hostSources'])!={str(p) for p in Path('Sources/Mac').glob('*.swift')}:
    raise SystemExit('Host source inventory changed during packaging.')
for name,digest in {**inputs['hostSources'],**inputs['packagingSources']}.items():
    if sha(Path(name))!=digest:raise SystemExit('Source changed during packaging: '+name)
identity='local.william.virtuafighter3'
info=plistlib.loads((source/'Contents/Info.plist').read_bytes())
if info['CFBundleIdentifier']!=identity or info['CFBundleExecutable']!='VirtuaFighter3':
    raise SystemExit('Unexpected app identity.')
if destination.exists():
    old=destination/'Contents/Info.plist'
    if not old.is_file() or plistlib.loads(old.read_bytes()).get('CFBundleIdentifier')!=identity:
        raise SystemExit('Refusing to replace an unrecognized app directory.')
    shutil.rmtree(destination)
source.rename(destination)
report={'app':str(destination),'executableSHA256':sha(destination/'Contents/MacOS/VirtuaFighter3'),
        'engineManifestSHA256':sha(Path('build/native/engine-build-manifest.json')),
        'nativeArchiveSHA256':sha(Path('build/native/libvf3.a')),
        'mediaManifestSHA256':sha(Path('build/assets/media-identity.json')),
        'iconSHA256':sha(destination/'Contents/Resources/AppIcon.icns'),
        'buildScriptSHA256':sha(Path('scripts/build.sh')),'identity':identity,
        'architecture':'arm64','deploymentTarget':'14.0','adHocSignatureVerified':True,
        'qualification':'Packaged artifact identity and signature only; gameplay and host acceptance are separate.'}
report.update(inputs)
Path('build/package-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
print('Built '+str(destination.resolve()))
PY

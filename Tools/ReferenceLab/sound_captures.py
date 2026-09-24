#!/usr/bin/env python3
"""Merge current VF3 observer sound captures with per-run provenance."""
from pathlib import Path
import argparse, json, sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from compile_sound import captures, sha
from prepare_source import REVISION

def relative(path):
    return str(path.resolve().relative_to(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',nargs=2,action='append',required=True,metavar=('CAPTURE_JSONL','REPLAY_REPORT'))
    parser.add_argument('--output',type=Path,default=ROOT/'build/coverage/sound-observations.jsonl')
    parser.add_argument('--observer-manifest',type=Path,default=ROOT/'build/observer/engine-build-manifest.json')
    args=parser.parse_args();records=set();sources=[]
    observer=json.loads(args.observer_manifest.read_text())
    if observer['kind']!='observer' or observer['shippingNative'] is not False or observer['upstreamCommit']!=REVISION:
        raise ValueError('Expected the pinned original-processor observer build')
    for capture_name,report_name in args.run:
        capture,report_path=Path(capture_name).resolve(),Path(report_name).resolve()
        report=json.loads(report_path.read_text())
        if report.get('passed') is not True or not report.get('librarySHA256') or report.get('frames',0)<=0:
            raise ValueError('Incomplete replay provenance: '+str(report_path))
        if report['librarySHA256']!=observer['dynamicLibrarySHA256']:
            raise ValueError('Capture replay used a different observer library')
        data=captures(capture)
        if not data:raise ValueError('Empty sound capture: '+str(capture))
        if any(row['kind']=='m68k' and row.get('board')!=0 for row in data):
            raise ValueError('Unexpected sound board in VF3 capture: '+str(capture))
        records.update(json.dumps(row,sort_keys=True,separators=(',',':')) for row in data)
        sources.append({'capture':relative(capture),'captureSHA256':sha(capture),'report':relative(report_path),
            'reportSHA256':sha(report_path),'records':len(data),'frames':report['frames'],
            'observerLibrarySHA256':report['librarySHA256'],'clockEpoch':report['clockEpoch'],'route':report['route']})
    output=args.output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(''.join(row+'\n' for row in sorted(records)))
    inventory={'game':'vf3','revision':'Japan Revision D','upstreamCommit':REVISION,
        'mergeScriptSHA256':sha(Path(__file__).resolve()),'mergedCapture':relative(output),
        'mergedCaptureSHA256':sha(output),'uniqueRecords':len(records),'runs':sources,
        'observerBuildManifest':relative(args.observer_manifest),'observerBuildManifestSHA256':sha(args.observer_manifest),
        'observerSourceInputs':observer['sources'],
        'observerSoundSources':{name:digest for name,digest in observer['compiledSources'].items() if any(part in name for part in ('sound_observe','m68kcpu','SCSPDSP','SoundBoard','SCSP.cpp'))},
        'scope':'Union of supplied current-game original-processor observer outputs. Game ROM mapping and every observed 68K word are separately authenticated by compile_sound.py; generated programs and raw captures remain local.'}
    output.with_name('sound-capture-sources.json').write_text(json.dumps(inventory,indent=2)+'\n')
    print(json.dumps({'output':relative(output),'runs':len(sources),'records':len(records)}))
if __name__=='__main__':main()

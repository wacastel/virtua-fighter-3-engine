#!/usr/bin/env python3
"""Validate supplied Revision D media and create a deterministic local bundle."""
from pathlib import Path
import argparse, hashlib, json, shutil, zipfile, zlib
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write_json(path, data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--game',type=Path,default=ROOT/'Virtua Fighter 3 ROMs/vf3')
    args=ap.parse_args()
    source=ROOT/'build/upstream/supermodel/Config/Games.xml'
    tree=ET.parse(source); game=next(g for g in tree.getroot() if g.get('name')=='vf3')
    output=ROOT/'build/assets'; output.mkdir(parents=True,exist_ok=True)
    manifest_path=ROOT/'Configuration/media.json'
    expected=json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    rows=[]
    normalized=ROOT/'build/media-source'; normalized.mkdir(parents=True,exist_ok=True)
    selected={}
    for region in game.find('roms'):
        for entry in region.findall('file'):
            name=entry.get('name')
            wanted=int(entry.get('crc32'),16)
            candidates=[args.game/name]
            candidates+=sorted(p for p in args.game.parent.rglob(name) if p.is_file())
            path=next((p for p in candidates if p.is_file() and zlib.crc32(p.read_bytes())==wanted),None)
            if path is None: raise ValueError('Missing verified media: '+name)
            data=path.read_bytes(); selected[name]=data
            (normalized/name).write_bytes(data)
            crc=f'{zlib.crc32(data):08x}'
            if crc!=f'{int(entry.get("crc32"),16):08x}': raise ValueError(f'Wrong CRC32: {name}')
            rows.append(dict(path=name,region=region.get('name'),bytes=len(data),crc32=crc,sha1=hashlib.sha1(data).hexdigest(),sha256=hashlib.sha256(data).hexdigest()))
    rows.sort(key=lambda r:r['path'])
    manifest={'game':'vf3','title':'Virtua Fighter 3','revision':'Japan Revision D, original country settings available','files':rows}
    if expected is not None and manifest != expected: raise ValueError('Media differs from canonical identities')
    if expected is None: write_json(manifest_path,manifest)
    dest=output/'vf3.zip'
    with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_STORED) as z:
        for row in rows:
            info=zipfile.ZipInfo(row['path'],(1996,12,24,0,0,0));info.external_attr=0o100644<<16
            z.writestr(info,selected[row['path']])
    root=ET.Element(tree.getroot().tag,tree.getroot().attrib);root.append(game)
    ET.indent(root)
    xml=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    (ROOT/'Configuration/Games.xml').write_bytes(xml)
    (output/'Games.xml').write_bytes(xml)
    identity={'files':[{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in [dest,output/'Games.xml']]}
    write_json(output/'media-identity.json',identity)
    generated=ROOT/'build/generated';generated.mkdir(parents=True,exist_ok=True)
    (generated/'media_identity.h').write_text('#pragma once\n'+''.join(f'constexpr const char *{name} = "{row["sha256"]}";\n' for name,row in zip(['vf3_zip_sha256','vf3_xml_sha256'],identity['files'])))
    write_json(ROOT/'Documentation/media-acceptance.json',{'passed':True,'fileCount':len(rows),'bytes':sum(r['bytes'] for r in rows),'identity':identity,'scope':'Exact supplied media lengths, CRC32, SHA1 and SHA256. Other sets remain untouched.'})
    print(json.dumps({'verifiedFiles':len(rows),'output':str(output.relative_to(ROOT))}))
if __name__=='__main__': main()

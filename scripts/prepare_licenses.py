#!/usr/bin/env python3
"""Preserve pinned upstream licenses and embedded component notices verbatim."""
from pathlib import Path
import json
import re
import shutil
from prepare_source import ROOT, SOURCE, REVISION, ARCHIVE_SHA256, sha, verify_source, write_json

LICENSES = ROOT / 'Licenses'
NOTICE_WORDS = re.compile(rb'copyright|licen[cs]e|permission|redistribut|public domain|no warranty|dedicat.{0,30}rights', re.I)
COMMENT = re.compile(rb'/\*.*?\*/', re.S)
LINE_COMMENT = re.compile(rb'^[\t ]*//[^\r\n]*(?:\r?\n[\t ]*//[^\r\n]*)*', re.M)
SOURCE_SUFFIXES = {'.c', '.cc', '.cpp', '.h', '.hpp', '.inl', '.m', '.mm'}


def prepare():
    original = verify_source()
    LICENSES.mkdir(parents=True, exist_ok=True)
    copies = [('Docs/LICENSE.txt', 'Supermodel-LICENSE.txt'),
              ('Docs/README.txt', 'Supermodel-README.txt')]
    copied = []
    for source, target in copies:
        shutil.copyfile(SOURCE / source, LICENSES / target)
        copied.append({'source': source, 'path': target, 'sha256': sha(LICENSES / target)})
    shutil.copyfile(SOURCE / 'Docs/LICENSE.txt', ROOT / 'COPYING')
    output = bytearray(b'Verbatim source notices from the pinned Supermodel source archive.\n'
                       b'Each fragment below is copied byte-for-byte; source filenames are attribution.\n\n')
    records = []
    for name in sorted(original['files']):
        source = SOURCE / name
        if source.suffix not in SOURCE_SUFFIXES:
            continue
        data = source.read_bytes()
        spans = [(m.start(), m.end()) for m in COMMENT.finditer(data) if NOTICE_WORDS.search(m[0])]
        spans += [(m.start(), m.end()) for m in LINE_COMMENT.finditer(data) if NOTICE_WORDS.search(m[0])]
        # Preserve Musashi's original binary copyright string and its separate GPL permission.
        spans += [(m.start(), m.end()) for m in re.finditer(
            rb'static const char\s*\*\s*copyright_notice\s*=.*?;', data, re.S)]
        spans += [(m.start(), m.end()) for m in re.finditer(
            rb'const char unz_copyright\[\]\s*=.*?;', data, re.S)]
        if not spans:
            continue
        output.extend(('\n===== ' + name + ' =====\n').encode())
        fragments = []
        for start, end in sorted(set(spans)):
            block = data[start:end]
            output_start = len(output)
            output.extend(block)
            output.extend(b'\n\n')
            fragments.append({'sourceByteStart': start, 'sourceByteEnd': end,
                              'noticeByteStart': output_start, 'bytes': len(block)})
        records.append({'source': name, 'sourceSHA256': sha(source), 'fragments': fragments})
    notice = LICENSES / 'SourceNotices.txt'
    notice.write_bytes(output)
    # Crypto.cpp/Crypto.h retain MAME's BSD identifier and exact holder lines.
    # Preserve those lines above and include the corresponding standard terms.
    bsd = LICENSES / 'Crypto-BSD-3-Clause.txt'
    bsd.write_text('''The source identifies the following copyright holders:
Crypto.cpp: Andreas Naive, Olivier Galibert, David Haywood
Crypto.h: David Haywood
License identifier in the pinned source: BSD-3-Clause

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS
IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
''')
    # Verify extraction boundaries against both files, including CRLF and legacy bytes.
    for row in records:
        data = (SOURCE / row['source']).read_bytes()
        for block in row['fragments']:
            a = data[block['sourceByteStart']:block['sourceByteEnd']]
            b = output[block['noticeByteStart']:block['noticeByteStart'] + block['bytes']]
            if a != b:
                raise RuntimeError('Notice extraction changed source bytes: ' + row['source'])
    manifest = {'upstream': 'https://github.com/trzy/Supermodel', 'revision': REVISION,
                'archiveSHA256': ARCHIVE_SHA256, 'scriptSHA256': sha(Path(__file__)),
                'copiedFiles': copied, 'rootCopyingSHA256': sha(ROOT / 'COPYING'),
                'noticeFile': 'SourceNotices.txt', 'noticeSHA256': sha(notice),
                'cryptoBSDTermsSHA256': sha(bsd),
                'sourceFilesWithNotices': len(records), 'sourceNotices': records,
                'scope': 'Exact pinned upstream license/manual and embedded source comment notices, plus Musashi binary copyright strings. Preserves attributions; does not change upstream component terms.'}
    write_json(LICENSES / 'manifest.json', manifest)
    (LICENSES / 'README.md').write_text('''# Source notices

Supermodel is distributed under GNU GPL version 3 or later. The original
license and manual are preserved verbatim in this directory; `COPYING` at the
project root also preserves the upstream license document.

`SourceNotices.txt` preserves copyright/license comment blocks from the pinned
original source, with original filenames. It includes the Supermodel team,
Musashi/Karl Stenerud and its recorded GPL permission, YAZE/Frank D. Cringle,
GLEW, Mesa, Khronos, minizip, tinyxml2, minimp3, and other included attributions.
Upstream components retain their respective terms. The notice file includes
notices from unused source components as well as components used by this target.

`manifest.json` records the upstream commit, archive identity, source hashes,
and exact byte ranges, so notice extraction can be checked without changing
the original text. `scripts/prepare_licenses.py` regenerates these files from
the verified source archive. System frameworks and system zlib are provided by
macOS and are not bundled here.

Original Virtua Fighter 3 game content belongs to its respective rights holders.
Game ROMs and generated program data are not part of this source distribution.
''')
    print(json.dumps({'prepared': True, 'sourceFilesWithNotices': len(records),
                      'noticeBytes': len(output), 'upstreamCommit': REVISION}))


if __name__ == '__main__':
    prepare()

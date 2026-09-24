#!/usr/bin/env python3
"""Exercise the real Swift launch-credit policy with synthetic, ROM-free saves."""
from pathlib import Path
import argparse
import json
import subprocess
import tempfile
from import_assets import ROOT, sha, write_json


HARNESS = r'''
import Foundation
import CryptoKit

struct TestFailure: Error, CustomStringConvertible { let description: String }
var checks = [String]()
func require(_ condition: @autoclosure () -> Bool, _ description: String) throws {
    guard condition() else { throw TestFailure(description: description) }
    checks.append(description)
}
func rejected(_ description: String, _ action: () throws -> Void) throws {
    do { try action() } catch { checks.append(description); return }
    throw TestFailure(description: description)
}
func uint32(_ value: UInt32) -> Data {
    var number = value.littleEndian
    return withUnsafeBytes(of: &number) { Data($0) }
}
func replaceWord(_ source: Data, _ offset: Int, _ value: UInt32) -> Data {
    var result = source; result.replaceSubrange(offset..<(offset + 4), with: uint32(value)); return result
}
func block(_ name: String, _ comment: String, _ payload: Data) -> Data {
    let n = Data(name.utf8) + Data([0]), c = Data(comment.utf8) + Data([0])
    return uint32(UInt32(12 + n.count + c.count + payload.count))
        + uint32(UInt32(n.count)) + uint32(UInt32(c.count)) + n + c + payload
}
struct Fixture {
    let data: Data, creditOffset: Int
    let header: Data, eeprom: Data, backup: Data
}
func fixture(_ credits: UInt8 = 13, longComments: Bool = false) -> Fixture {
    let header = block("VF3 NVRAM", "Synthetic fixture only", Data())
    var eepromPayload = Data((0..<166).map { UInt8(($0 * 19 + 7) & 255) })
    eepromPayload.replaceSubrange(0..<4, with: [0x45, 0x53, 0x41, 0x47])
    eepromPayload.replaceSubrange(64..<68, with: [0x45, 0x53, 0x41, 0x47])
    let eeprom = block("93C46", longComments ? String(repeating: "synthetic/", count: 31) : "EEPROM", eepromPayload)
    var ram = Data((0..<0x20000).map { UInt8(($0 * 37 + 11) & 255) })
    for offset in VF3CabinetSave.creditOffsets { ram[offset] = 0 }
    ram[0x1e046] = credits; ram[0x1e048] = 73
    ram.replaceSubrange(0x1e050..<0x1e058, with: [0x47, 0x41, 0x53, 0x45, 0x53, 0x45, 0x47, 0x41])
    let backup = block("Backup RAM", longComments ? "A different build-path length" : "RAM", ram)
    return Fixture(data: header + eeprom + backup,
                   creditOffset: header.count + eeprom.count + backup.count - ram.count + 0x1e046,
                   header: header, eeprom: eeprom, backup: backup)
}
func digest(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
func saved(_ root: URL, _ name: String, _ data: Data) throws -> URL {
    let directory = root.appendingPathComponent(name, isDirectory: true)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    try data.write(to: directory.appendingPathComponent("vf3.nv"))
    return directory
}
func contents(_ directory: URL) throws -> Data { try Data(contentsOf: directory.appendingPathComponent("vf3.nv")) }
func backupURL(_ directory: URL, _ data: Data) -> URL {
    directory.appendingPathComponent("Backups", isDirectory: true)
        .appendingPathComponent("vf3-before-startup-\(digest(data)).nv")
}
func run() throws {
    let fm = FileManager.default, root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    let domain = "local.william.virtuafighter3"
    for args in [[], ["--audio-report", "telemetry.json"], ["--save-dir", "disposable"], ["--capture", "frame.png"]] {
        try require(VF3CabinetSave.shouldClearCredits(bundleIdentifier: domain, arguments: args),
                    "Bundled interactive policy admits \(args)")
    }
    for flag in ["--headless", "--self-test", "--diagnostic-run", "--audio-replay"] {
        try require(!VF3CabinetSave.shouldClearCredits(bundleIdentifier: domain, arguments: [flag]),
                    "Replay policy preserves \(flag) save")
        try require(!VF3CabinetSave.shouldClearCredits(bundleIdentifier: domain, arguments: ["--audio-report", "out.json", flag]),
                    "Replay policy remains excluded with telemetry: \(flag)")
    }
    for identity: String? in [nil, "other.application"] {
        try require(!VF3CabinetSave.shouldClearCredits(bundleIdentifier: identity, arguments: []),
                    "Unbundled or different app preserves save: \(identity ?? "nil")")
    }
    for count: UInt8 in [1, 13, 24, 255] {
        for longer in [false, true] {
            let f = fixture(count, longComments: longer)
            let result = try VF3CabinetSave.clearingCredits(in: f.data)
            let differences = zip(f.data, result.data).enumerated().filter { $0.element.0 != $0.element.1 }.map { $0.offset }
            try require(result.credits == Int(count) && result.data.count == f.data.count && differences == [f.creditOffset],
                        "Counter \(count), variable comments \(longer): exactly the primary credit byte changes")
            try require(result.data[f.creditOffset] == 0 && result.data[f.creditOffset + 2] == 73,
                        "Counter \(count), variable comments \(longer): unrelated adjacent byte remains 73")
        }
    }
    for offset in VF3CabinetSave.creditOffsets {
        let f = fixture(0); var input = f.data
        let absolute = f.creditOffset + offset - 0x1e046; input[absolute] = 255
        let cleared = try VF3CabinetSave.clearingCredits(in: input)
        try require(cleared.credits == 255 && cleared.data == f.data,
                    "Each independent credit bank or coin remainder is cleared exactly: \(offset)")
    }
    let allFixture = fixture(0); var all = allFixture.data
    for offset in VF3CabinetSave.creditOffsets { all[allFixture.creditOffset + offset - 0x1e046] = 255 }
    let allResult = try VF3CabinetSave.clearingCredits(in: all)
    try require(allResult.credits == 1530 && allResult.data == allFixture.data,
                "Both credit banks and all four coin remainders clear without sum overflow")
    let f = fixture(), zero = fixture(0)
    let result = try VF3CabinetSave.clearingCredits(in: zero.data)
    try require(result.credits == 0 && result.data == zero.data, "Zero-credit data stays byte-identical")
    let absent = root.appendingPathComponent("absent", isDirectory: true)
    let absentCount = try VF3CabinetSave.prepareInteractiveLaunch(in: absent)
    try require(absentCount == 0 && !fm.fileExists(atPath: absent.path), "Missing save is a no-op without creating directories")
    let zeroDir = try saved(root, "zero", zero.data)
    let zeroSave = zeroDir.appendingPathComponent("vf3.nv"), stamp = Date(timeIntervalSince1970: 1_000_000)
    try fm.setAttributes([.modificationDate: stamp], ofItemAtPath: zeroSave.path)
    let zeroCount = try VF3CabinetSave.prepareInteractiveLaunch(in: zeroDir)
    let zeroData = try contents(zeroDir), zeroAttributes = try fm.attributesOfItem(atPath: zeroSave.path)
    try require(zeroCount == 0 && zeroData == zero.data && zeroAttributes[.modificationDate] as? Date == stamp
                && !fm.fileExists(atPath: zeroDir.appendingPathComponent("Backups").path),
                "Zero-credit file is not rewritten and no backup is created")

    let normal = try saved(root, "normal", f.data), normalSave = normal.appendingPathComponent("vf3.nv")
    try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: normalSave.path)
    let count = try VF3CabinetSave.prepareInteractiveLaunch(in: normal)
    let backup = backupURL(normal, f.data), originalBackup = try Data(contentsOf: backup)
    let changed = try contents(normal), expected = try VF3CabinetSave.clearingCredits(in: f.data).data
    try require(count == 13 && changed == expected && originalBackup == f.data,
                "File mutation preserves an exact original backup before clearing 13 credits")
    let changedPermissions = try fm.attributesOfItem(atPath: normalSave.path)[.posixPermissions] as? NSNumber
    let backupPermissions = try fm.attributesOfItem(atPath: backup.path)[.posixPermissions] as? NSNumber
    try require(changedPermissions?.intValue == 0o600 && backupPermissions?.intValue == 0o600,
                "Original POSIX permissions survive on changed save and backup")
    let second = try VF3CabinetSave.prepareInteractiveLaunch(in: normal)
    let backupFiles = try fm.contentsOfDirectory(atPath: normal.appendingPathComponent("Backups").path)
    let secondData = try contents(normal)
    try require(second == 0 && secondData == changed && backupFiles.count == 1,
                "Repeated startup is idempotent and does not duplicate backups")
    try f.data.write(to: normalSave, options: .atomic)
    try fm.setAttributes([.modificationDate: stamp], ofItemAtPath: backup.path)
    let reused = try VF3CabinetSave.prepareInteractiveLaunch(in: normal)
    let reusedAttributes = try fm.attributesOfItem(atPath: backup.path)
    try require(reused == 13 && reusedAttributes[.modificationDate] as? Date == stamp,
                "Existing exact SHA-named backup is reused without overwrite")
    let tampered = try saved(root, "tampered", f.data), tamperedBackup = backupURL(tampered, f.data)
    try fm.createDirectory(at: tamperedBackup.deletingLastPathComponent(), withIntermediateDirectories: true)
    let unrelated = Data("An existing backup must never be overwritten".utf8)
    try unrelated.write(to: tamperedBackup)
    try rejected("Tampered existing backup prevents the save write") { _ = try VF3CabinetSave.prepareInteractiveLaunch(in: tampered) }
    let preserved = try contents(tampered), preservedBackup = try Data(contentsOf: tamperedBackup)
    try require(preserved == f.data && preservedBackup == unrelated, "Backup mismatch preserves both original files")

    var cases: [(String, Data)] = [
        ("empty", Data()), ("truncated-header", Data(f.data.prefix(11))),
        ("zero-block-size", replaceWord(f.data, 0, 0)),
        ("oversized-block", replaceWord(f.data, 0, .max)),
        ("oversized-name", replaceWord(f.data, 4, .max)),
        ("oversized-comment", replaceWord(f.data, 8, .max)),
        ("zero-name", replaceWord(f.data, 4, 0)),
        ("zero-comment", replaceWord(f.data, 8, 0)),
        ("short-payload", Data(f.data.dropLast())),
        ("trailing-bytes", f.data + Data([0])),
        ("duplicate-block", f.data + f.backup),
        ("reordered-blocks", f.header + f.backup + f.eeprom),
        ("wrong-header", block("Different NVRAM", "Fixture", Data()) + f.eeprom + f.backup),
        ("header-payload", block("VF3 NVRAM", "Fixture", Data([1])) + f.eeprom + f.backup),
        ("short-eeprom", f.header + block("93C46", "Fixture", Data(repeating: 0, count: 165)) + f.backup),
        ("bad-eeprom-signature", f.header + block("93C46", "Fixture", Data(repeating: 0, count: 166)) + f.backup),
        ("short-backup-ram", f.header + f.eeprom + block("Backup RAM", "Fixture", Data(repeating: 0, count: 0x1ffff)))
    ]
    var nameEnd = f.data; nameEnd[12 + "VF3 NVRAM".utf8.count] = 65
    cases.append(("unterminated-name", nameEnd))
    var nameInterior = f.data; nameInterior[13] = 0
    cases.append(("interior-name-nul", nameInterior))
    var commentEnd = f.data; commentEnd[f.header.count - 1] = 65
    cases.append(("unterminated-comment", commentEnd))
    var commentInterior = f.data; commentInterior[12 + "VF3 NVRAM".utf8.count + 1] = 0
    cases.append(("interior-comment-nul", commentInterior))
    var badMirror = f.data; badMirror[f.header.count + f.eeprom.count - 166 + 64] = 0
    cases.append(("bad-eeprom-mirror-signature", badMirror))
    var badRAM = f.data; badRAM[f.creditOffset + 0x1e050 - 0x1e046] = 0
    cases.append(("bad-cabinet-ram-signature", badRAM))
    for (name, data) in cases {
        let directory = try saved(root, name, data)
        try rejected("Reject malformed container: \(name)") { _ = try VF3CabinetSave.prepareInteractiveLaunch(in: directory) }
        let after = try contents(directory)
        try require(after == data && !fm.fileExists(atPath: directory.appendingPathComponent("Backups").path),
                    "Malformed \(name) leaves bytes unchanged and creates no backup")
    }
    let target = root.appendingPathComponent("symlink-target.nv"); try f.data.write(to: target)
    let links = root.appendingPathComponent("symlink-save", isDirectory: true)
    try fm.createDirectory(at: links, withIntermediateDirectories: true)
    try fm.createSymbolicLink(at: links.appendingPathComponent("vf3.nv"), withDestinationURL: target)
    try rejected("Symbolic-link save is rejected") { _ = try VF3CabinetSave.prepareInteractiveLaunch(in: links) }
    let targetData = try Data(contentsOf: target)
    try require(targetData == f.data, "Symbolic-link target remains unchanged")
    let linkBackup = try saved(root, "symlink-backup", f.data)
    let external = root.appendingPathComponent("external-backups", isDirectory: true)
    try fm.createDirectory(at: external, withIntermediateDirectories: true)
    try fm.createSymbolicLink(at: linkBackup.appendingPathComponent("Backups"), withDestinationURL: external)
    try rejected("Symbolic-link backup directory is rejected") { _ = try VF3CabinetSave.prepareInteractiveLaunch(in: linkBackup) }
    let linkData = try contents(linkBackup), externalFiles = try fm.contentsOfDirectory(atPath: external.path)
    try require(linkData == f.data && externalFiles.isEmpty, "Rejected backup directory leaves save and target unchanged")

    let report: [String: Any] = ["passed": true, "checkCount": checks.count, "checks": checks,
                               "malformedContainerCases": cases.count, "usesSyntheticDataOnly": true]
    let encoded = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
    print(String(decoding: encoded, as: UTF8.self))
}
do { try run() } catch { fputs("Startup policy verification failed: \(error)\n", stderr); exit(1) }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/startup-investigation/host-tests')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = [ROOT/'Sources/Mac/CabinetSave.swift', ROOT/'Sources/Mac/NativeGame.swift', Path(__file__).resolve()]
    inputs = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    harness = output/'main.swift'
    harness.write_text(HARNESS)
    executable = output/'startup-tests'
    sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    command = ['xcrun', 'swiftc', '-swift-version', '5', '-target', 'arm64-apple-macosx14.0',
               '-sdk', sdk, '-O', str(sources[0]), str(harness), '-o', str(executable)]
    subprocess.run(command, cwd=ROOT, check=True)
    with tempfile.TemporaryDirectory(prefix='synthetic-saves-', dir=output) as fixtures:
        completed = subprocess.run([str(executable), fixtures], cwd=ROOT, capture_output=True, text=True, check=True)
    result = json.loads(completed.stdout)
    if any(sha(ROOT/name) != digest for name, digest in inputs.items()):
        raise RuntimeError('Startup policy sources changed while the tests ran')
    result.update(inputs=inputs, harnessSHA256=sha(harness), executableSHA256=sha(executable),
                  compiler=subprocess.check_output(['xcrun', 'swiftc', '--version'], text=True).strip(),
                  target='arm64-apple-macosx14.0', engineLinked=False, realUserSaveRead=False,
                  scope='VF3 Japan Revision D actual Swift credit-cleanup helper and launch-policy tests against disposable synthetic CBlockFile containers. Checks six-field preservation, exact backups, permissions, idempotence and rejection before writes. NativeGame source is bound for integration review; the engine and GUI are not executed by this fixture. Separate original-program and packaged-startup evidence establishes the game-specific credit meaning and attract behavior.')
    write_json(output/'acceptance.json', result)
    write_json(ROOT/'Documentation/startup-host-acceptance.json', result)
    print(json.dumps({'passed': result['passed'], 'checkCount': result['checkCount'],
                      'malformedContainerCases': result['malformedContainerCases'],
                      'report': str((output/'acceptance.json').relative_to(ROOT))}))


if __name__ == '__main__':
    main()

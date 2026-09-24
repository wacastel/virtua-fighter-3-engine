import Foundation
import CryptoKit

/// Credits belong to the current desktop session. Keep the original cabinet
/// settings, records and accounting intact when starting the next session.
enum VF3CabinetSave {
    enum Failure: LocalizedError {
        case invalid(String)
        var errorDescription: String? {
            switch self { case .invalid(let detail): return "Cabinet save was left unchanged: \(detail)" }
        }
    }

    static func shouldClearCredits(bundleIdentifier: String?, arguments: [String]) -> Bool {
        let replayOptions = ["--headless", "--self-test", "--diagnostic-run", "--audio-replay"]
        return bundleIdentifier == "local.william.virtuafighter3"
            && !replayOptions.contains(where: arguments.contains)
    }

    /// VF3 Japan Revision D stores two credit banks and four coin-conversion
    /// remainders as independently masked bytes in its CBlockFile Backup RAM.
    /// The original SRAM accessor doubles logical offsets and reverses words.
    static let creditOffsets = [0x1e046, 0x1e047, 0x1e04a, 0x1e04b, 0x1e04e, 0x1e04f]
    static func clearingCredits(in original: Data) throws -> (data: Data, credits: Int) {
        let bytes = [UInt8](original)
        let expected = [("VF3 NVRAM", 0), ("93C46", 166), ("Backup RAM", 0x20000)]
        var position = 0, payloads: [Int] = []
        func invalid() -> Failure { .invalid("unrecognized NVRAM structure") }
        func word(_ at: Int) -> Int {
            Int(bytes[at]) | Int(bytes[at + 1]) << 8 | Int(bytes[at + 2]) << 16 | Int(bytes[at + 3]) << 24
        }
        for (name, length) in expected {
            guard bytes.count - position >= 12 else { throw invalid() }
            let size = word(position), nameSize = word(position + 4), commentSize = word(position + 8)
            let header = 12 + nameSize + commentSize
            guard nameSize > 0, commentSize > 0, size >= header,
                  size <= bytes.count - position, size - header == length else { throw invalid() }
            let nameStart = position + 12, commentStart = nameStart + nameSize
            let storedName = bytes[nameStart..<(commentStart - 1)]
            let commentEnd = commentStart + commentSize - 1
            guard bytes[commentStart - 1] == 0, !storedName.contains(0),
                  String(bytes: storedName, encoding: .utf8) == name,
                  bytes[commentEnd] == 0, !bytes[commentStart..<commentEnd].contains(0) else { throw invalid() }
            payloads.append(position + header); position += size
        }
        guard position == bytes.count,
              Array(bytes[payloads[1]..<(payloads[1] + 4)]) == [0x45, 0x53, 0x41, 0x47],
              Array(bytes[(payloads[1] + 64)..<(payloads[1] + 68)]) == [0x45, 0x53, 0x41, 0x47],
              Array(bytes[(payloads[2] + 0x1e050)..<(payloads[2] + 0x1e058)]) == [0x47, 0x41, 0x53, 0x45, 0x53, 0x45, 0x47, 0x41] else {
            throw invalid()
        }
        // Logical 0x22/0x25 are P1/common and P2 credits; 0x23/0x24 and
        // 0x26/0x27 are their coin-conversion remainders. Original coin, service,
        // and start paths modify these byte fields without a checksum. Cabinet
        // settings, score tables, EEPROM and lifetime accounting are elsewhere.
        let offsets = creditOffsets.map { payloads[2] + $0 }
        let credits = offsets.reduce(0) { $0 + Int(bytes[$1]) }
        guard credits != 0 else { return (original, 0) }
        var updated = original
        for offset in offsets { updated[offset] = 0 }
        return (updated, credits)
    }

    @discardableResult
    static func prepareInteractiveLaunch(in directory: URL) throws -> Int {
        let fm = FileManager.default, save = directory.appendingPathComponent("vf3.nv")
        guard fm.fileExists(atPath: save.path) else { return 0 }
        let attributes = try fm.attributesOfItem(atPath: save.path)
        guard attributes[.type] as? FileAttributeType == .typeRegular else {
            throw Failure.invalid("NVRAM is not a regular file")
        }
        let original = try Data(contentsOf: save)
        let result = try clearingCredits(in: original)
        guard result.credits != 0 else { return 0 }

        let backups = directory.appendingPathComponent("Backups", isDirectory: true)
        try fm.createDirectory(at: backups, withIntermediateDirectories: true)
        guard try fm.attributesOfItem(atPath: backups.path)[.type] as? FileAttributeType == .typeDirectory else {
            throw Failure.invalid("backup location is not a directory")
        }
        let digest = SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined()
        let backup = backups.appendingPathComponent("vf3-before-startup-\(digest).nv")
        if !fm.fileExists(atPath: backup.path) {
            try original.write(to: backup, options: .withoutOverwriting)
            if let permissions = attributes[.posixPermissions] {
                try fm.setAttributes([.posixPermissions: permissions], ofItemAtPath: backup.path)
            }
        }
        guard try fm.attributesOfItem(atPath: backup.path)[.type] as? FileAttributeType == .typeRegular,
              try Data(contentsOf: backup) == original,
              try Data(contentsOf: save) == original else {
            throw Failure.invalid("save or backup changed during startup")
        }
        try result.data.write(to: save, options: .atomic)
        if let permissions = attributes[.posixPermissions] {
            try fm.setAttributes([.posixPermissions: permissions], ofItemAtPath: save.path)
        }
        return result.credits
    }
}

import Foundation
import CryptoKit

/// Resolves app-owned assets and a separate writable data directory.
/// Exact file identities must be checked by vf3_create before the engine runs.
struct VF3Media {
    let assets: URL, saves: URL
    let temporary: Bool
    static func resolve() throws -> VF3Media {
        let fm = FileManager.default
        func option(_ name: String) -> String? {
            guard let index = CommandLine.arguments.firstIndex(of: name), index + 1 < CommandLine.arguments.count else { return nil }
            let value = CommandLine.arguments[index + 1]
            return value.hasPrefix("--") ? nil : value
        }
        let override = option("--assets") ?? ProcessInfo.processInfo.environment["VIRTUA_FIGHTER_3_ASSET_DIR"]
        let assets = override.map { URL(fileURLWithPath: $0, isDirectory: true).standardizedFileURL }
            ?? Bundle.main.resourceURL?.appendingPathComponent("Media", isDirectory: true)
        var directory: ObjCBool = false
        guard let assets, fm.fileExists(atPath: assets.path, isDirectory: &directory), directory.boolValue else {
            throw VirtuaFighter3Error.message("Virtua Fighter 3 media is missing. Build the app with its verified local media, or provide --assets DIRECTORY.")
        }
        try verify(assets)
        let explicit = option("--save-dir") ?? ProcessInfo.processInfo.environment["VIRTUA_FIGHTER_3_SAVE_DIR"]
        let diagnostic = ["--headless","--self-test","--diagnostic-run","--audio-report","--audio-replay"].contains(where: CommandLine.arguments.contains)
        let temporary = explicit == nil && (Bundle.main.bundleIdentifier != VF3Preferences.domain || diagnostic)
        let saves: URL
        if let explicit { saves = URL(fileURLWithPath: explicit, isDirectory: true).standardizedFileURL }
        else if temporary { saves = fm.temporaryDirectory.appendingPathComponent("virtua-fighter-3-test-" + UUID().uuidString, isDirectory: true) }
        else {
            saves = try fm.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
                .appendingPathComponent(VF3Preferences.domain, isDirectory: true)
        }
        try fm.createDirectory(at: saves, withIntermediateDirectories: true)
        return VF3Media(assets: assets, saves: saves, temporary: temporary)
    }
    private struct Manifest: Decodable {
        struct File: Decodable { let path: String; let bytes: Int; let sha256: String }
        let files: [File]
    }
    /// A packaging integrity check; the bridge independently verifies canonical media.
    private static func verify(_ directory: URL) throws {
        let manifest = try JSONDecoder().decode(Manifest.self,
            from: Data(contentsOf: directory.appendingPathComponent("media-identity.json")))
        let paths = Set(manifest.files.map(\.path))
        guard paths.isSuperset(of: ["vf3.zip", "Games.xml"]),
              paths.isSubset(of: ["vf3.zip", "Games.xml", "default.nv"]),
              paths.count == manifest.files.count else {
            throw VirtuaFighter3Error.message("The bundled media inventory is invalid.")
        }
        for row in manifest.files {
            let data = try Data(contentsOf: directory.appendingPathComponent(row.path), options: .mappedIfSafe)
            let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            guard data.count == row.bytes, digest == row.sha256 else {
                throw VirtuaFighter3Error.message("Bundled media failed verification: \(row.path).")
            }
        }
    }
    func removeTemporarySaves() { if temporary { try? FileManager.default.removeItem(at: saves) } }
}

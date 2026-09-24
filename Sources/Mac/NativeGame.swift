import Foundation
import CryptoKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

@_silgen_name("vf3_create") private func nativeCreate(_ assets: UnsafePointer<CChar>, _ saves: UnsafePointer<CChar>) -> UnsafeMutableRawPointer?
@_silgen_name("vf3_destroy") private func nativeDestroy(_ context: UnsafeMutableRawPointer)
@_silgen_name("vf3_error") private func nativeError(_ context: UnsafeMutableRawPointer?) -> UnsafePointer<CChar>?
@_silgen_name("vf3_fault_code") private func nativeFaultCode(_ context: UnsafeMutableRawPointer) -> UInt32
@_silgen_name("vf3_step") private func nativeStep(_ context: UnsafeMutableRawPointer, _ player1: UInt32, _ player2: UInt32) -> Int32
@_silgen_name("vf3_set_invincible") private func nativeSetInvincible(_ context: UnsafeMutableRawPointer, _ enabled: Int32) -> Int32
@_silgen_name("vf3_get_invincible") private func nativeGetInvincible(_ context: UnsafeMutableRawPointer) -> Int32
@_silgen_name("vf3_pixels") private func nativePixels(_ context: UnsafeMutableRawPointer) -> UnsafePointer<UInt8>?
@_silgen_name("vf3_audio") private func nativeAudio(_ context: UnsafeMutableRawPointer) -> UnsafePointer<Int16>?
@_silgen_name("vf3_audio_count") private func nativeAudioCount(_ context: UnsafeMutableRawPointer) -> Int32
@_silgen_name("vf3_width") private func nativeWidth(_ context: UnsafeMutableRawPointer) -> Int32
@_silgen_name("vf3_height") private func nativeHeight(_ context: UnsafeMutableRawPointer) -> Int32
@_silgen_name("vf3_frame_rate") private func nativeFrameRate(_ context: UnsafeMutableRawPointer) -> Double
@_silgen_name("vf3_audio_sample_rate") private func nativeSampleRate(_ context: UnsafeMutableRawPointer) -> Int32
@_silgen_name("vf3_frame_number") private func nativeFrameNumber(_ context: UnsafeMutableRawPointer) -> UInt64

enum VF3Preferences {
    static let domain = "local.william.virtuafighter3"
    static let defaults: UserDefaults = Bundle.main.bundleIdentifier == domain ? .standard : UserDefaults(suiteName: domain)!
    static let mutedKey = "muted"
}

final class VF3Game {
    struct Frame {
        let rgba: Data
        let width: Int, height: Int
        var image: CGImage? {
            guard rgba.count == width * height * 4, let provider = CGDataProvider(data: rgba as CFData) else { return nil }
            return CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                           bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                           bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.last.rawValue), provider: provider,
                           decode: nil, shouldInterpolate: false, intent: .defaultIntent)
        }
        func writePNG(to url: URL) throws {
            guard let image, let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else {
                throw VirtuaFighter3Error.message("Cannot create capture at \(url.path).")
            }
            CGImageDestinationAddImage(destination, image, nil)
            guard CGImageDestinationFinalize(destination) else { throw VirtuaFighter3Error.message("Could not save the frame capture.") }
        }
    }
    private var context: UnsafeMutableRawPointer
    private let media: VF3Media
    private var closed = false
    let width: Int, height: Int, sampleRate: Int
    let framesPerSecond: Double
    private(set) var frameCount = 0
    private(set) var sampleFrames = 0
    private(set) var latestFrame: Frame?

    init() throws {
        let media = try VF3Media.resolve()
        do {
            if VF3CabinetSave.shouldClearCredits(bundleIdentifier: Bundle.main.bundleIdentifier,
                                                arguments: CommandLine.arguments) {
                try VF3CabinetSave.prepareInteractiveLaunch(in: media.saves)
            }
        } catch { media.removeTemporarySaves(); throw error }
        let pointer = media.assets.path.withCString { assets in media.saves.path.withCString { nativeCreate(assets, $0) } }
        guard let pointer else {
            media.removeTemporarySaves()
            throw VirtuaFighter3Error.message(nativeError(nil).map { String(cString: $0) } ?? "The Virtua Fighter 3 native engine could not initialize.")
        }
        let width = Int(nativeWidth(pointer)), height = Int(nativeHeight(pointer))
        let fps = nativeFrameRate(pointer), rate = Int(nativeSampleRate(pointer))
        guard width == 496, height == 384, fps.isFinite, (1...240).contains(fps), (8_000...192_000).contains(rate) else {
            nativeDestroy(pointer); media.removeTemporarySaves()
            throw VirtuaFighter3Error.message("The native engine returned an unsupported Model 3 video or audio format.")
        }
        self.context = pointer; self.media = media; self.width = width; self.height = height
        self.framesPerSecond = fps; self.sampleRate = rate
    }
    deinit { close() }
    func close() {
        guard !closed else { return }
        closed = true; nativeDestroy(context); media.removeTemporarySaves()
    }
    private func requireOpen() throws {
        guard !closed else { throw VirtuaFighter3Error.message("The game session has closed.") }
    }
    private var failure: VirtuaFighter3Error {
        let text = nativeError(context).map { String(cString: $0) } ?? "The native engine stopped."
        return .message("\(text) (fault \(nativeFaultCode(context)))")
    }
    var invincible: Bool { !closed && nativeGetInvincible(context) != 0 }
    func setInvincible(_ enabled: Bool) throws {
        try requireOpen()
        guard nativeSetInvincible(context, enabled ? 1 : 0) == 1 else { throw failure }
        guard nativeFaultCode(context) == 0, invincible == enabled else {
            throw VirtuaFighter3Error.message("The native engine did not apply player-one invincibility.")
        }
    }
    func reset() throws {
        try requireOpen()
        guard nativeFaultCode(context) == 0 else { throw failure }
        // A cabinet restart needs fresh sound/DSP state as well as a CPU reset.
        // Destroy saves NVRAM; recreate reloads it from this same directory.
        // Both calls remain on the owning engine thread, including CGL teardown.
        closed = true
        nativeDestroy(context)
        let pointer = media.assets.path.withCString { assets in media.saves.path.withCString { nativeCreate(assets, $0) } }
        guard let pointer else {
            media.removeTemporarySaves()
            throw VirtuaFighter3Error.message(nativeError(nil).map { String(cString: $0) } ?? "The Virtua Fighter 3 native engine could not restart.")
        }
        guard Int(nativeWidth(pointer)) == width, Int(nativeHeight(pointer)) == height,
              nativeFrameRate(pointer) == framesPerSecond, Int(nativeSampleRate(pointer)) == sampleRate else {
            nativeDestroy(pointer); media.removeTemporarySaves()
            throw VirtuaFighter3Error.message("The restarted engine returned a different video or audio format.")
        }
        context = pointer; closed = false
        frameCount = 0; sampleFrames = 0; latestFrame = nil
    }
    func advance(_ input: VF3Input) throws -> [Int16] {
        try requireOpen(); try input.validate()
        if let enabled = input.invincible { try setInvincible(enabled) }
        guard nativeStep(context, input.normalized.player1, input.normalized.player2) == 1 else { throw failure }
        guard nativeFaultCode(context) == 0 else { throw failure }
        guard nativeFrameNumber(context) == UInt64(frameCount + 1), let pixels = nativePixels(context) else {
            throw VirtuaFighter3Error.message("The engine did not return the expected completed video frame.")
        }
        latestFrame = Frame(rgba: Data(bytes: pixels, count: width * height * 4), width: width, height: height)
        let count = Int(nativeAudioCount(context))
        guard (0...8192).contains(count) else { throw VirtuaFighter3Error.message("Invalid native stereo-frame count.") }
        var samples = [Int16]()
        if count > 0 {
            guard let pointer = nativeAudio(context) else { throw VirtuaFighter3Error.message("The engine returned no PCM buffer.") }
            samples = Array(UnsafeBufferPointer(start: pointer, count: count * 2))
        }
        frameCount += 1; sampleFrames += count
        return samples
    }
    func diagnostics() -> [String: Any] {
        ["frame": frameCount, "closed": closed, "invincible": invincible, "faultCode": closed ? 0 : nativeFaultCode(context),
         "framesPerSecond": framesPerSecond,
         "sampleRate": sampleRate, "width": width, "height": height]
    }
}

func runVF3Replay(frames: Int, replay: VF3Replay?, capture: URL?, trace: URL? = nil) throws -> [String: Any] {
    let game = try VF3Game(); defer { game.close() }
    var pictures = SHA256(), audio = SHA256(), framedAudio = SHA256(), nonzeroSamples = 0
    let records: FileHandle?
    if let trace {
        try Data().write(to: trace, options: .atomic)
        records = try FileHandle(forWritingTo: trace)
    } else { records = nil }
    defer { try? records?.close() }
    func digest(_ value: SHA256.Digest) -> String { value.map { String(format: "%02x", $0) }.joined() }
    let started = Date()
    for frame in 0..<frames {
        let samples = try game.advance(replay?.input(frame: frame) ?? VF3Input())
        if let picture = game.latestFrame { pictures.update(data: picture.rgba) }
        let pcm = samples.withUnsafeBytes { Data($0) }
        audio.update(data: pcm)
        var sampleCount = UInt32(samples.count / 2).littleEndian
        withUnsafeBytes(of: &sampleCount) { framedAudio.update(data: Data($0)) }
        framedAudio.update(data: pcm)
        if let records, let picture = game.latestFrame {
            let row: [String: Any] = ["frame": frame + 1, "audioFrames": samples.count / 2,
                "rgba": digest(SHA256.hash(data: picture.rgba)), "pcm": digest(SHA256.hash(data: pcm)),
                "invincible": game.invincible]
            var data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
            data.append(10); try records.write(contentsOf: data)
        }
        nonzeroSamples += samples.reduce(0) { $0 + ($1 == 0 ? 0 : 1) }
    }
    guard let picture = game.latestFrame else { throw VirtuaFighter3Error.message("No frame was produced.") }
    if let capture { try picture.writePNG(to: capture) }
    return ["game": "Virtua Fighter 3", "frames": frames, "framesPerSecond": game.framesPerSecond,
            "width": game.width, "height": game.height, "pixelFormat": "RGBA8888", "audioSampleRate": game.sampleRate,
            "sampleFrames": game.sampleFrames, "nonzeroSamples": nonzeroSamples,
            "pictureSHA256": digest(pictures.finalize()), "audioSHA256": digest(audio.finalize()),
            "audioFrameSequenceSHA256": digest(framedAudio.finalize()),
            "finalPictureSHA256": digest(SHA256.hash(data: picture.rgba)), "finalState": game.diagnostics(),
            "elapsedSeconds": Date().timeIntervalSince(started)]
}

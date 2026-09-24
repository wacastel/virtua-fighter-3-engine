import Foundation

/// The native CGL context and every engine call live on one persistent thread.
/// SpriteKit receives immutable pictures; its main-thread render loop never waits
/// for a game frame or controls the audio producer's clock.
final class VF3EngineWorker {
    struct Presentation {
        let frame: VF3Game.Frame?
        let serial: UInt64
        let failure: String?
        let invincible: Bool
    }
    private let condition = NSCondition()
    private let inputForFrame: (Int, VF3Input?) -> VF3Input
    private var thread: Thread?
    private var ready = false, finished = false, stopping = false, paused = true
    private var resetRequested = false
    private var resetError: String?
    private var failure: String?
    private var epoch: UInt64 = 0
    private var serial: UInt64 = 0
    private var latestFrame: VF3Game.Frame?
    private var gameState: [String: Any] = [:]
    private var frameNumber = 0
    private var lastInput = VF3Input()
    private var replay: VF3Replay?
    private var audio: VF3AudioOutput?
    private(set) var sampleRate = 44100
    private(set) var framesPerSecond = 60.0
    private var engineSeconds = 0.0, audioSeconds = 0.0
    private var engineDurations: [Double] = []
    private var discardedClockGaps = 0
    private var callsOnDedicatedThread = true

    init(inputForFrame: @escaping (Int, VF3Input?) -> VF3Input) throws {
        self.inputForFrame = inputForFrame
        let thread = Thread { [weak self] in self?.run() }
        self.thread = thread
        thread.name = "Virtua Fighter 3 engine"
        thread.qualityOfService = .userInteractive
        thread.start()
        condition.lock()
        while !ready { condition.wait() }
        let error = failure
        condition.unlock()
        if let error { throw VirtuaFighter3Error.message(error) }
    }

    func attachAudio(_ value: VF3AudioOutput) {
        condition.lock(); audio = value; condition.broadcast(); condition.unlock()
    }
    func setReplay(_ value: VF3Replay?) {
        condition.lock(); replay = value; condition.unlock()
    }
    func setPaused(_ value: Bool) {
        condition.lock(); defer { condition.unlock() }
        if !value && (failure != nil || stopping || finished) { return }
        guard paused != value else { return }
        paused = value; epoch &+= 1
        audio?.flush(); condition.broadcast()
    }
    func reset() throws {
        condition.lock()
        guard !finished else {
            let error = failure ?? "The game session has closed."
            condition.unlock(); throw VirtuaFighter3Error.message(error)
        }
        paused = true; epoch &+= 1; audio?.flush()
        resetRequested = true; resetError = nil; condition.broadcast()
        while resetRequested && !finished { condition.wait() }
        let error = resetError
        condition.unlock()
        if let error { throw VirtuaFighter3Error.message(error) }
    }
    func stop() {
        condition.lock()
        stopping = true; condition.broadcast()
        while !finished { condition.wait() }
        condition.unlock()
    }
    var frameCount: Int {
        condition.lock(); defer { condition.unlock() }; return frameNumber
    }
    func presentation() -> Presentation {
        condition.lock(); defer { condition.unlock() }
        return Presentation(frame: latestFrame, serial: serial, failure: failure,
                            invincible: gameState["invincible"] as? Bool ?? false)
    }
    func diagnostics() -> [String: Any] {
        condition.lock(); defer { condition.unlock() }
        let sorted = engineDurations.sorted()
        let timings: [String: Double] = sorted.isEmpty ? [:] : [
            "p50": sorted[sorted.count / 2] * 1000,
            "p95": sorted[min(sorted.count - 1, sorted.count * 95 / 100)] * 1000,
            "maximum": sorted.last! * 1000]
        return ["gameState": gameState, "gameFrames": frameNumber,
                "invincible": gameState["invincible"] as? Bool ?? false,
                "lastInput": lastInput.diagnostic, "discardedClockGaps": discardedClockGaps,
                "engineCallsOnDedicatedThread": callsOnDedicatedThread,
                "engineTiming": ["engineSeconds": engineSeconds, "audioSeconds": audioSeconds,
                                 "engineMilliseconds": timings, "timingSamples": sorted.count]]
    }

    private func run() {
        do {
            let game = try autoreleasepool { try VF3Game() }
            condition.lock()
            sampleRate = game.sampleRate; framesPerSecond = game.framesPerSecond
            gameState = game.diagnostics(); ready = true
            callsOnDedicatedThread = !Thread.isMainThread
            condition.broadcast(); condition.unlock()
            var deadline: Double?
            var clockEpoch: UInt64 = 0
            let interval = 1 / game.framesPerSecond
            while autoreleasepool(invoking: { () -> Bool in
                condition.lock()
                while !stopping && !resetRequested && (paused || audio == nil) {
                    deadline = nil; condition.wait()
                }
                if stopping { condition.unlock(); return false }
                if resetRequested {
                    condition.unlock()
                    var error: String?
                    do { try game.reset() } catch let caught { error = caught.localizedDescription }
                    condition.lock()
                    resetError = error; failure = error; resetRequested = false
                    gameState = game.diagnostics(); frameNumber = game.frameCount
                    latestFrame = nil; serial &+= 1; deadline = nil
                    condition.broadcast(); condition.unlock(); return true
                }
                let now = ProcessInfo.processInfo.systemUptime
                if deadline == nil || clockEpoch != epoch {
                    deadline = now + interval; clockEpoch = epoch
                }
                if now < deadline! {
                    _ = condition.wait(until: Date(timeIntervalSinceNow: deadline! - now))
                    condition.unlock(); return true
                }
                if now - deadline! >= 0.25 {
                    deadline = now; discardedClockGaps += 1; audio?.flush()
                }
                let stepEpoch = epoch
                let override = replay?.input(frame: game.frameCount)
                condition.unlock()

                // Reserve pending one-shot controls atomically for this frame.
                // Input arriving during native execution remains for the next one.
                let input = inputForFrame(game.frameCount, override)
                let started = ProcessInfo.processInfo.systemUptime
                do {
                    let samples = try game.advance(input)
                    let duration = ProcessInfo.processInfo.systemUptime - started
                    condition.lock()
                    engineSeconds += duration
                    if engineDurations.count < 12000 { engineDurations.append(duration) }
                    callsOnDedicatedThread = callsOnDedicatedThread && !Thread.isMainThread
                    latestFrame = game.latestFrame; frameNumber = game.frameCount
                    gameState = game.diagnostics(); lastInput = input; serial &+= 1
                    // Pause/stop may arrive during the one in-flight engine frame.
                    // Complete that frame, but never queue its audio after a flush.
                    if !paused && !stopping && epoch == stepEpoch {
                        let audioStarted = ProcessInfo.processInfo.systemUptime
                        audio?.present(samples)
                        audioSeconds += ProcessInfo.processInfo.systemUptime - audioStarted
                    }
                    condition.unlock()
                } catch {
                    condition.lock(); failure = error.localizedDescription; paused = true
                    gameState = game.diagnostics(); audio?.flush(); condition.unlock()
                }
                deadline! += interval
                return true
            }) {}
            autoreleasepool { game.close() }
            condition.lock(); gameState = game.diagnostics(); finished = true
            condition.broadcast(); condition.unlock()
        } catch {
            condition.lock(); failure = error.localizedDescription; ready = true; finished = true
            condition.broadcast(); condition.unlock()
        }
    }
}

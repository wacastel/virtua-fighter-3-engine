import AppKit
import SpriteKit
import GameController

final class VF3Scene: SKScene {
    private let worker: VF3EngineWorker
    private let audio: VF3AudioOutput
    let controls: VF3Controls
    private let controlLock: NSRecursiveLock
    private let picture = SKSpriteNode(color: .black, size: CGSize(width: 512, height: 384))
    private let shade = SKShapeNode(rectOf: CGSize(width: 512, height: 384))
    private let title = SKLabelNode(fontNamed: "AvenirNext-DemiBold")
    private let hint = SKLabelNode(fontNamed: "AvenirNext-Regular")
    private let assistStatus = SKLabelNode(fontNamed: "AvenirNext-DemiBold")
    private var failed = false
    private var updateCount = 0, presentedFrames = 0
    private var lastPresentedSerial: UInt64?
    private var textureSeconds = 0.0, updateSeconds = 0.0
    private var updateDurations: [Double] = []
    private var updatesOnMainThread = true
    private var observers: [(NotificationCenter, NSObjectProtocol)] = []
    private(set) var pausedByHost = false
    var onStatus: ((String) -> Void)?
    var diagnosticReplay: VF3Replay? { didSet { worker.setReplay(diagnosticReplay) } }
    var savesPreferences = true
    var frameCount: Int { worker.frameCount }
    var invincible: Bool { worker.presentation().invincible }
    var canToggleInvincibility: Bool { !failed && !pausedByHost && routed { controls.isActive } }
    var muted: Bool {
        get { audio.muted }
        set { audio.muted = newValue; if savesPreferences { VF3Preferences.defaults.set(newValue, forKey: VF3Preferences.mutedKey) } }
    }
    init(muted: Bool) throws {
        let input = VF3Controls(), lock = NSRecursiveLock()
        controls = input; controlLock = lock
        worker = try VF3EngineWorker { _, replayInput in
            lock.lock(); defer { lock.unlock() }
            // The dedicated thread is about to execute exactly this frame.
            // New events arriving while it runs remain pending for the next frame.
            return input.reserveFrame(replayInput)
        }
        audio = VF3AudioOutput(muted: muted, sampleRate: Double(worker.sampleRate))
        worker.attachAudio(audio)
        super.init(size: CGSize(width: 512, height: 384))
        scaleMode = .aspectFit; backgroundColor = .black
        picture.position = CGPoint(x: 256, y: 192); addChild(picture)
        shade.position = picture.position; shade.fillColor = NSColor.black.withAlphaComponent(0.78)
        shade.strokeColor = .clear; shade.zPosition = 10; shade.isHidden = true; addChild(shade)
        title.fontSize = 24; title.position = CGPoint(x: 0, y: 9); shade.addChild(title)
        hint.fontSize = 12; hint.position = CGPoint(x: 0, y: -20); shade.addChild(hint)
        assistStatus.name = "invincibilityStatus"; assistStatus.text = "P1 INVINCIBLE"
        assistStatus.fontSize = 13; assistStatus.fontColor = .systemGreen
        assistStatus.position = CGPoint(x: 256, y: 10); assistStatus.zPosition = 20
        assistStatus.isHidden = true; addChild(assistStatus)
        controls.onTogglePause = { [weak self] in self?.togglePause() }
        controls.onResume = { [weak self] in self?.setPaused(false) }
        _ = routed { controls.refreshControllers(GCController.controllers()) }
        observe(.GCControllerDidConnect) { [weak self] _ in self?.refreshControllers() }
        observe(.GCControllerDidDisconnect) { [weak self] _ in self?.refreshControllers() }
        for name in [NSWorkspace.willSleepNotification, NSWorkspace.didWakeNotification] {
            observe(name, center: NSWorkspace.shared.notificationCenter) { [weak self] _ in self?.setPaused(true) }
        }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }
    deinit {
        for (center, observer) in observers { center.removeObserver(observer) }
        worker.stop()
    }
    private func routed<T>(_ body: () -> T) -> T {
        controlLock.lock(); defer { controlLock.unlock() }; return body()
    }
    private func observe(_ name: Notification.Name, center: NotificationCenter = .default, callback: @escaping (Notification) -> Void) {
        observers.append((center, center.addObserver(forName: name, object: nil, queue: .main, using: callback)))
    }
    private func refreshControllers() {
        if routed({ controls.refreshControllers(GCController.controllers()) }) { setPaused(true) }
    }
    func key(_ key: UInt16, down: Bool, repeated: Bool = false) { routed { controls.key(key, down: down, repeated: repeated) } }
    func clearKeyboard() { routed { controls.clearKeyboard() } }
    func setInputActive(_ active: Bool) { routed { controls.setActive(active) }; if !active { setPaused(true) } }
    func setPaused(_ paused: Bool) {
        pausedByHost = paused; routed { controls.setPaused(paused) }; worker.setPaused(paused)
        shade.isHidden = !paused; title.text = "Paused"; hint.text = "Release controls, then press Return / Create / Options"
    }
    func togglePause() { setPaused(!pausedByHost) }
    func toggleInvincibility() {
        guard canToggleInvincibility else { return }
        routed { controls.toggleInvincibility() }
    }
    func resetGame() {
        do {
            try worker.reset(); routed { controls.resetInvincibility() }; failed = false
            assistStatus.isHidden = true
            picture.texture = nil; lastPresentedSerial = nil; setPaused(false)
        } catch { showFailure(error) }
    }
    override func update(_ time: TimeInterval) {
        let started = ProcessInfo.processInfo.systemUptime
        defer {
            let duration = ProcessInfo.processInfo.systemUptime - started
            updateSeconds += duration
            if updateDurations.count < 12000 { updateDurations.append(duration) }
        }
        updateCount += 1; updatesOnMainThread = updatesOnMainThread && Thread.isMainThread
        routed { controls.pollController() }
        let snapshot = worker.presentation()
        assistStatus.isHidden = !snapshot.invincible
        if let failure = snapshot.failure, !failed { showFailure(VirtuaFighter3Error.message(failure)) }
        guard routed({ controls.isActive }), !pausedByHost, !failed else { return }
        worker.setPaused(false)
        if snapshot.serial != lastPresentedSerial, let frame = snapshot.frame {
            let textureStarted = ProcessInfo.processInfo.systemUptime
            if let image = frame.image {
                let texture = SKTexture(cgImage: image); texture.filteringMode = .nearest; picture.texture = texture
                textureSeconds += ProcessInfo.processInfo.systemUptime - textureStarted
                lastPresentedSerial = snapshot.serial; presentedFrames += 1
            }
        }
    }
    private func showFailure(_ error: Error) {
        failed = true; worker.setPaused(true); routed { controls.clear() }
        shade.isHidden = false; title.text = "Game stopped"; hint.text = "Quit and reopen the app to start a new session"
        onStatus?(error.localizedDescription); fputs("Virtua Fighter 3: \(error.localizedDescription)\n", stderr)
    }
    func shutdown() { setPaused(true); failed = true; worker.stop() }
    func capture(to url: URL) throws {
        guard let frame = worker.presentation().frame else { throw VirtuaFighter3Error.message("No engine frame is available.") }
        try frame.writePNG(to: url)
    }
    func diagnostics() -> [String: Any] {
        var value = audio.diagnostics()
        value.merge(worker.diagnostics()) { _, new in new }
        value["displayUpdates"] = updateCount; value["updatesOnMainThread"] = updatesOnMainThread
        value["presentedFrames"] = presentedFrames; value["pausedByHost"] = pausedByHost
        value["assignedControllers"] = routed { controls.controllers.map { $0?.vendorName ?? "Unassigned" } }
        let sorted = updateDurations.sorted()
        let times: [String: Double] = sorted.isEmpty ? [:] : [
            "p50": sorted[sorted.count / 2] * 1000,
            "p95": sorted[min(sorted.count - 1, sorted.count * 95 / 100)] * 1000,
            "maximum": sorted.last! * 1000]
        value["presentationTiming"] = ["textureSeconds": textureSeconds, "updateSeconds": updateSeconds,
                                       "updateMilliseconds": times, "timingSamples": sorted.count]
        return value
    }
}

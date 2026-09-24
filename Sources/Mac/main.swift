import AppKit
import SpriteKit
import GameController

private let arguments = CommandLine.arguments
setbuf(stdout, nil)
private func argument(_ name: String) -> String? {
    guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else { return nil }
    let result = arguments[index + 1]
    return result.hasPrefix("--") ? nil : result
}
private func replay(_ path: String) throws -> VF3Replay {
    let value = try JSONDecoder().decode(VF3Replay.self, from: Data(contentsOf: URL(fileURLWithPath: path)))
    try value.validate(); return value
}
private func report(_ value: [String: Any], path: String? = nil) throws {
    let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys])
    if let path { try data.write(to: URL(fileURLWithPath: path), options: .atomic) }
    print(String(decoding: data, as: UTF8.self))
}
if arguments.contains("--help") {
    print("""
    Virtua Fighter 3 — macOS host for the native Model 3 engine
    Launch without arguments to play using verified bundled media.
    --assets DIRECTORY / --save-dir DIRECTORY   Override media or isolated game-data path
    --fullscreen / --mute / --sound             Presentation and audio options
    --controllers                              List connected controllers
    --headless --frames N                       Execute real engine frames without a window
    --diagnostic-run FILE.json                  Frame-indexed normalized two-player fighting inputs
    --self-test --frames N                      Compare graphics/PCM from two fresh real-engine sessions
    --diagnostic-capture FILE.png               Capture final headless engine frame
    --diagnostic-report FILE.json               Write headless JSON report
    --diagnostic-frames FILE.jsonl              Write per-frame RGBA/PCM/count evidence
    --audio-replay FILE.json                    Replay fighting inputs in the visible app
    --audio-report FILE.json                    Save playback telemetry when the app closes
    --capture FILE.png --capture-after SECONDS  Capture the engine picture during a GUI run
    --quit-after SECONDS                        Close after a bounded GUI interval
    Inputs: player1 and player2 each contain a separate button mask.
    Flags per player: Up1 Down2 Left4 Right8 Punch16 Kick32 Guard64 Evade128 Start256 Coin512.
    DualSense: left stick / D-pad moves; Triangle punches, Circle kicks, Cross guards, Square evades.
    R1 inserts a coin; Options starts/resumes; Create pauses/resumes. Stick clicks are unassigned.
    Player 1 keyboard: arrows, Z Punch, X Kick, C Guard, V Evade, 1/Return Start, 5 Coin.
    Player 2 keyboard: WASD, F Punch, G Kick, H Guard, J Evade, 2 Start, 6 Coin.
    P/Escape pauses/resumes. Two connected controllers retain their player assignments.
    Insert two coins, press Start and follow the original character selection screen.
    """)
    exit(0)
}
if arguments.contains("--controllers") {
    _ = NSApplication.shared
    GCController.shouldMonitorBackgroundEvents = true
    GCController.startWirelessControllerDiscovery(completionHandler: nil)
    RunLoop.current.run(until: Date().addingTimeInterval(2)); GCController.stopWirelessControllerDiscovery()
    let list = GCController.controllers().map { ["name": $0.vendorName ?? $0.productCategory,
        "category": $0.productCategory, "extendedGamepad": $0.extendedGamepad != nil,
        "dualSense": $0.extendedGamepad is GCDualSenseGamepad] as [String: Any] }
    try report(["game": "Virtua Fighter 3", "connectedCount": list.count, "controllers": list,
                "physicalActuationTested": false])
    exit(0)
}
if arguments.contains("--headless") || arguments.contains("--self-test") || arguments.contains("--diagnostic-run") {
    do {
        let route = try argument("--diagnostic-run").map(replay)
        let frames = argument("--frames").flatMap(Int.init) ?? route?.frames ?? 3600
        guard (1...1_000_000).contains(frames) else { throw VirtuaFighter3Error.message("Frames must be between 1 and 1,000,000.") }
        var first = try runVF3Replay(frames: frames, replay: route,
                    capture: argument("--diagnostic-capture").map { URL(fileURLWithPath: $0) },
                    trace: argument("--diagnostic-frames").map { URL(fileURLWithPath: $0) })
        if arguments.contains("--self-test") {
            let second = try runVF3Replay(frames: frames, replay: route, capture: nil)
            for key in ["pictureSHA256","audioSHA256","audioFrameSequenceSHA256","finalPictureSHA256"] {
                guard first[key] as? String == second[key] as? String else {
                    throw VirtuaFighter3Error.message("Fresh native sessions disagree on \(key).")
                }
            }
            guard first["sampleFrames"] as? Int == second["sampleFrames"] as? Int else {
                throw VirtuaFighter3Error.message("Fresh native sessions disagree on PCM length.")
            }
            first["deterministic"] = true; first["comparedRuns"] = 2
            first["scope"] = "Graphics and PCM determinism only; separate core validation is required for CPU and game semantics."
        }
        try report(first, path: argument("--diagnostic-report")); exit(0)
    } catch { fputs("Virtua Fighter 3: \(error.localizedDescription)\n", stderr); exit(1) }
}

final class VF3View: SKView {
    override var acceptsFirstResponder: Bool { true }
    override func keyDown(with event: NSEvent) {
        if event.modifierFlags.contains(.command) { (scene as? VF3Scene)?.clearKeyboard(); super.keyDown(with: event); return }
        (scene as? VF3Scene)?.key(event.keyCode, down: true, repeated: event.isARepeat)
    }
    override func keyUp(with event: NSEvent) { (scene as? VF3Scene)?.key(event.keyCode, down: false) }
    override func flagsChanged(with event: NSEvent) { if event.modifierFlags.contains(.command) { (scene as? VF3Scene)?.clearKeyboard() } }
    override func resignFirstResponder() -> Bool { (scene as? VF3Scene)?.clearKeyboard(); return super.resignFirstResponder() }
}
final class VF3App: NSObject, NSApplicationDelegate, NSWindowDelegate, NSMenuItemValidation {
    private var window: NSWindow!
    private var view: VF3View!
    private var scene: VF3Scene!
    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            scene = try VF3Scene(muted: !arguments.contains("--sound") && (arguments.contains("--mute") || VF3Preferences.defaults.bool(forKey: VF3Preferences.mutedKey)))
            scene.savesPreferences = argument("--audio-report") == nil && argument("--audio-replay") == nil
            if let path = argument("--audio-replay") { scene.diagnosticReplay = try replay(path) }
        } catch { NSAlert(error: error).runModal(); NSApp.terminate(nil); return }
        let available = NSScreen.main?.visibleFrame.size ?? CGSize(width: 1280, height: 900)
        let width = max(496, min(992, available.width - 60, (available.height - 90) * 4 / 3))
        let size = NSSize(width: width, height: width * 3 / 4)
        window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                          styleMask: [.titled,.closable,.miniaturizable,.resizable], backing: .buffered, defer: false)
        window.title = "Virtua Fighter 3"; window.contentAspectRatio = NSSize(width: 4, height: 3)
        window.contentMinSize = NSSize(width: 512, height: 384); window.backgroundColor = .black
        window.isReleasedWhenClosed = false; window.delegate = self; window.collectionBehavior = [.fullScreenPrimary]
        view = VF3View(frame: NSRect(origin: .zero, size: size)); view.autoresizingMask = [.width,.height]
        view.preferredFramesPerSecond = max(60, NSScreen.main?.maximumFramesPerSecond ?? 60)
        window.contentView = view
        scene.onStatus = { [weak self] in self?.window.subtitle = $0 }
        installMenus(); window.center(); window.makeKeyAndOrderFront(nil)
        view.presentScene(scene); window.makeFirstResponder(view); NSApp.activate(ignoringOtherApps: true)
        GCController.startWirelessControllerDiscovery(completionHandler: nil)
        if arguments.contains("--fullscreen") { window.toggleFullScreen(nil) }
        if let path = argument("--capture") {
            let delay = max(0, argument("--capture-after").flatMap(Double.init) ?? 10)
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                do { try self?.scene.capture(to: URL(fileURLWithPath: path)) }
                catch { fputs("Capture failed: \(error.localizedDescription)\n", stderr) }
            }
        }
        if let delay = argument("--quit-after").flatMap(Double.init), delay.isFinite, delay >= 0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { NSApp.terminate(nil) }
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        GCController.stopWirelessControllerDiscovery()
        if let path = argument("--audio-report"), let scene {
            var value = scene.diagnostics()
            value["preferredDisplayFramesPerSecond"] = view.preferredFramesPerSecond
            value["windowVisible"] = window.isVisible; value["windowOccluded"] = !window.occlusionState.contains(.visible)
            do { try report(value, path: path) } catch { fputs("Playback report failed: \(error.localizedDescription)\n", stderr) }
        }
        scene?.shutdown()
    }
    func applicationDidResignActive(_ notification: Notification) { scene?.setInputActive(false) }
    func applicationDidBecomeActive(_ notification: Notification) { if window?.isKeyWindow == true { scene?.setInputActive(true) } }
    func windowDidBecomeKey(_ notification: Notification) { scene?.setInputActive(true) }
    func windowDidResignKey(_ notification: Notification) { scene?.setInputActive(false) }
    private func menuItem(_ title: String, _ action: Selector, _ key: String = "") -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self; item.keyEquivalentModifierMask = [.command]; return item
    }
    private func installMenus() {
        let menu = NSMenu(), app = NSMenu(title: "Virtua Fighter 3"), game = NSMenu(title: "Game")
        let window = NSMenu(title: "Window"), help = NSMenu(title: "Help")
        app.addItem(menuItem("About Virtua Fighter 3", #selector(about))); app.addItem(.separator())
        app.addItem(menuItem("Quit Virtua Fighter 3", #selector(quit), "q"))
        game.addItem(menuItem("Pause", #selector(pause))); game.addItem(menuItem("Reset Game", #selector(reset), "r"))
        game.addItem(menuItem("Mute", #selector(mute), "m"))
        window.addItem(menuItem("Enter Full Screen", #selector(fullscreen), "f"))
        help.addItem(menuItem("Controls", #selector(controls), "/"))
        for submenu in [app,game,window,help] { let item = NSMenuItem(); item.submenu = submenu; menu.addItem(item) }
        NSApp.mainMenu = menu; NSApp.windowsMenu = window; NSApp.helpMenu = help
    }
    func validateMenuItem(_ item: NSMenuItem) -> Bool {
        if item.action == #selector(pause) { item.title = scene?.pausedByHost == true ? "Resume" : "Pause" }
        if item.action == #selector(mute) { item.state = scene?.muted == true ? .on : .off }
        return true
    }
    @objc private func quit() { NSApp.terminate(nil) }
    @objc private func pause() { scene.togglePause() }
    @objc private func reset() { scene.resetGame(); window.makeFirstResponder(view) }
    @objc private func mute() { scene.muted.toggle() }
    @objc private func fullscreen() { window.toggleFullScreen(nil) }
    @objc private func controls() {
        scene.setPaused(true)
        let alert = NSAlert(); alert.messageText = "Virtua Fighter 3 Controls"
        alert.informativeText = "Move: left stick / D-pad\nPunch: Triangle\nKick: Circle\nGuard: Cross\nEvade: Square\nInsert coin: R1\nStart / resume: Options\nPause / resume: Create (stick clicks are unassigned)\n\nPlayer 1 keyboard: arrows; Z/X/C/V = Punch/Kick/Guard/Evade; 1 or Return = Start; 5 = Coin\nPlayer 2 keyboard: WASD; F/G/H/J = Punch/Kick/Guard/Evade; 2 = Start; 6 = Coin\nP / Escape pauses or resumes.\n\nFactory settings: insert two coins, then press Start.\n\nTwo controllers retain their player assignments. Focus loss, sleep or an assigned-controller disconnection pauses the app. Release held controls before resuming."
        alert.runModal(); window.makeFirstResponder(view)
    }
    @objc private func about() {
        scene.setPaused(true)
        let alert = NSAlert(); alert.messageText = "Virtua Fighter 3"
        alert.informativeText = "Apple Silicon edition\nOriginal Virtua Fighter 3 game © SEGA, 1996\n\nOpen Help → Controls for keyboard and DualSense mappings."
        alert.runModal(); window.makeFirstResponder(view)
    }
}
let app = NSApplication.shared
let delegate = VF3App()
app.setActivationPolicy(.regular); app.delegate = delegate; app.run()

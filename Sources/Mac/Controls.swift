import Foundation
import GameController

// Each player has an independent original cabinet button mask. Host pause never
// enters that mask. Assist requests are reserved separately for the engine thread.
// Stable assignments prevent another pad taking over a fighter.
final class VF3Controls {
    var onTogglePause: (() -> Void)?
    var onResume: (() -> Void)?
    private final class Slot {
        var controller: GCController?
        var needsNeutral = true, pause = false, triangle = false
        var current: UInt32 = 0, pending: UInt32 = 0
        func clear() { needsNeutral = true; pause = false; triangle = false; current = 0; pending = 0 }
    }
    private let slots = [Slot(), Slot()]
    var controllers: [GCController?] { slots.map { $0.controller } }
    private(set) var isActive = true
    private(set) var paused = false
    private var pressed = Set<UInt16>(), pendingKeys = Set<UInt16>()
    private var reservedInvincibility = false, pendingInvincibilityToggle = false
    // Hardware key codes: P1 arrows/ZXCV/1/Return/5; P2 WASD/FGHJ/2/6.
    private let keyMap: [(UInt16, Int, UInt32)] = [
        (126,0,VF3Button.up),(125,0,VF3Button.down),(123,0,VF3Button.left),(124,0,VF3Button.right),
        (6,0,VF3Button.punch),(7,0,VF3Button.kick),(8,0,VF3Button.guardButton),(9,0,VF3Button.evade),
        (18,0,VF3Button.start),(36,0,VF3Button.start),(76,0,VF3Button.start),(23,0,VF3Button.coin),
        (13,1,VF3Button.up),(1,1,VF3Button.down),(0,1,VF3Button.left),(2,1,VF3Button.right),
        (3,1,VF3Button.punch),(5,1,VF3Button.kick),(4,1,VF3Button.guardButton),(38,1,VF3Button.evade),
        (19,1,VF3Button.start),(22,1,VF3Button.coin)
    ]
    /// Keep surviving slots, then fill vacancies. An ignored third pad cannot
    /// clear live input or bypass the neutral guard on an assigned controller.
    func refreshControllers(_ available: [GCController]) -> Bool {
        let usable = available.filter { $0.extendedGamepad != nil }
        var lostAssigned = false
        for slot in slots {
            if let current = slot.controller, !usable.contains(where: { $0 === current }) {
                current.playerIndex = .indexUnset; slot.controller = nil; slot.clear(); lostAssigned = true
            }
        }
        for controller in usable where !slots.contains(where: { $0.controller === controller }) {
            guard let index = slots.firstIndex(where: { $0.controller == nil }) else { break }
            let slot = slots[index]; slot.controller = controller; slot.clear()
            controller.playerIndex = index == 0 ? .index1 : .index2
            controller.extendedGamepad?.buttonMenu.preferredSystemGestureState = .disabled
            controller.extendedGamepad?.buttonOptions?.preferredSystemGestureState = .disabled
        }
        return lostAssigned
    }
    func clear() { clearKeyboard(); pendingInvincibilityToggle = false; for slot in slots { slot.clear() } }
    func clearKeyboard() { pressed.removeAll(); pendingKeys.removeAll() }
    func setActive(_ value: Bool) { isActive = value; clear() }
    func setPaused(_ value: Bool) { paused = value; clear() }
    /// Called under the scene's routing lock; native state changes only when the
    /// dedicated engine thread reserves and executes the next frame.
    func toggleInvincibility() {
        guard isActive, !paused else { return }
        pendingInvincibilityToggle.toggle()
    }
    func resetInvincibility() { clear(); reservedInvincibility = false }
    func key(_ code: UInt16, down: Bool, repeated: Bool = false) {
        guard isActive, !repeated else { return }
        if !down { pressed.remove(code); return }
        let fresh = pressed.insert(code).inserted
        if code == 35 || code == 53 { if fresh { onTogglePause?() }; return }
        if paused {
            if fresh && [18,19,36,76].contains(code) { onResume?() }
            return
        }
        if code == 34 { if fresh { toggleInvincibility() }; return }
        if keyMap.contains(where: { $0.0 == code }) { pendingKeys.insert(code) }
    }
    func pollController() {
        guard isActive else { return }
        for slot in slots {
            guard let pad = slot.controller?.extendedGamepad else { continue }
            var x = pad.leftThumbstick.xAxis.value, y = pad.leftThumbstick.yAxis.value
            if max(abs(pad.dpad.xAxis.value),abs(pad.dpad.yAxis.value)) > 0.3 {
                x = pad.dpad.xAxis.value; y = pad.dpad.yAxis.value
            }
            var buttons: UInt32 = 0
            if x < -0.3 { buttons |= VF3Button.left }; if x > 0.3 { buttons |= VF3Button.right }
            if y < -0.3 { buttons |= VF3Button.down }; if y > 0.3 { buttons |= VF3Button.up }
            if pad.buttonX.isPressed { buttons |= VF3Button.punch }
            if pad.buttonB.isPressed { buttons |= VF3Button.kick }
            if pad.buttonA.isPressed { buttons |= VF3Button.guardButton }
            if pad.leftShoulder.isPressed { buttons |= VF3Button.evade }
            if pad.buttonMenu.isPressed { buttons |= VF3Button.start }
            if pad.rightShoulder.isPressed { buttons |= VF3Button.coin }
            let pause = pad.buttonOptions?.isPressed == true
            let triangle = pad.buttonY.isPressed
            if slot.needsNeutral {
                if buttons == 0 && !pause && !triangle { slot.needsNeutral = false }
                slot.pause = pause; slot.triangle = triangle; slot.current = 0; continue
            }
            if pause && !slot.pause {
                onTogglePause?(); slot.pause = pause; return
            }
            slot.pause = pause
            if triangle && !slot.triangle { toggleInvincibility() }
            slot.triangle = triangle
            if paused && buttons & VF3Button.start != 0 { onResume?(); return }
            slot.current = paused ? 0 : buttons
            if !paused { slot.pending |= buttons }
        }
    }
    func input() -> VF3Input {
        guard isActive, !paused else { return VF3Input() }
        let keys = pressed.union(pendingKeys)
        var values = slots.map { $0.current | $0.pending }
        for (code, index, bit) in keyMap where keys.contains(code) { values[index] |= bit }
        return VF3Input(player1: values[0], player2: values[1],
                        invincible: pendingInvincibilityToggle ? !reservedInvincibility : nil).normalized
    }
    /// Reserve an imminent engine frame under the shared routing lock. Events
    /// arriving while the engine runs remain pending for the next reservation.
    func reserveFrame(_ replayInput: VF3Input? = nil) -> VF3Input {
        let value = (replayInput ?? input()).normalized
        if let enabled = value.invincible { reservedInvincibility = enabled }
        pendingInvincibilityToggle = false
        pendingKeys.removeAll(); for slot in slots { slot.pending = 0 }
        return value
    }
}

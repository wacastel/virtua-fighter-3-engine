import Foundation
import GameController

struct CheckError: Error, CustomStringConvertible { let description: String }
var checks = [String]()
func check(_ value: @autoclosure () -> Bool, _ description: String) throws {
    guard value() else { throw CheckError(description: description) }; checks.append(description)
}
func rejected(_ input: VF3Input, _ description: String) throws {
    do { try input.validate() } catch { checks.append(description); return }
    throw CheckError(description: description)
}
func rejectedReplay(_ json: String, _ description: String) throws {
    do { let r = try JSONDecoder().decode(VF3Replay.self, from: Data(json.utf8)); try r.validate() }
    catch { checks.append(description); return }
    throw CheckError(description: description)
}
func tap(_ c: VF3Controls, _ key: UInt16) { c.key(key, down: true); c.key(key, down: false) }
func press(_ c: VF3Controls, _ button: GCControllerButtonInput) {
    button.setValue(1); c.pollController(); button.setValue(0); c.pollController()
}

do {
    try VF3Input(player1: VF3Button.all, player2: VF3Button.all).validate()
    try check(VF3Input(player1: VF3Button.all, player2: VF3Button.all).normalized == VF3Input(player1: 1008, player2: 1008),
              "Both players accept ten defined flags and normalize opposed directions")
    try rejected(VF3Input(player1: 1024), "Reject unknown player1 bit")
    try rejected(VF3Input(player2: 1024), "Reject unknown player2 bit")
    try rejected(VF3Input(player1: 1 << 16), "Reject reference service flag in shipping input")
    for input: UInt32 in [1,2,4,8,5,6,9,10] {
        try check(VF3Button.normalize(input) == input, "Preserve direction or diagonal mask \(input)")
    }
    let neutral = try JSONDecoder().decode(VF3Input.self, from: Data("{}".utf8))
    try check(neutral == VF3Input(), "Missing player fields are neutral")
    let source = VF3Input(player1: VF3Button.punch | VF3Button.guardButton, player2: VF3Button.kick | VF3Button.evade, invincible: true)
    let roundTrip = try JSONDecoder().decode(VF3Input.self, from: JSONEncoder().encode(source))
    try check(roundTrip == source, "Input JSON round trip retains both players and explicit invincibility independently")
    try check(source.normalized.invincible == true && source.diagnostic["invincible"] as? Bool == true && VF3Input().diagnostic["invincible"] == nil,
              "Normalization and diagnostics retain explicit assist values and omit unspecified changes")
    let assistSteps = try JSONDecoder().decode(VF3Replay.self, from: Data(#"{"steps":[{"frames":2,"invincible":true},{"frames":1},{"frames":1,"invincible":false}]}"#.utf8))
    try assistSteps.validate()
    try check(assistSteps.input(frame:0).invincible == true && assistSteps.input(frame:1).invincible == true && assistSteps.input(frame:2).invincible == nil && assistSteps.input(frame:3).invincible == false,
              "Step replay distinguishes assist ON, omitted and OFF at exact boundaries")
    let assistEvents = try JSONDecoder().decode(VF3Replay.self, from: Data(#"{"frames":5,"events":[{"start":1,"end":4,"invincible":true},{"start":2,"end":3,"player2":16},{"start":3,"end":4,"invincible":false}]}"#.utf8))
    try assistEvents.validate()
    try check(assistEvents.input(frame:0).invincible == nil && assistEvents.input(frame:2) == VF3Input(player2:16,invincible:true) && assistEvents.input(frame:3).invincible == false && assistEvents.input(frame:4).invincible == nil,
              "Event replay merges assist independently in file order with half-open ranges")
    let route = try JSONDecoder().decode(VF3Replay.self, from: Data(#"{"steps":[{"frames":2,"player1":16},{"frames":1,"player2":128}]}"#.utf8))
    try route.validate()
    try check(route.frames == 3 && route.input(frame: 0).player1 == 16 && route.input(frame: 2).player2 == 128 && route.input(frame: 3) == VF3Input() && route.input(frame: -1) == VF3Input(), "Step replay has exact frame boundaries and neutral outside range")
    let events = try JSONDecoder().decode(VF3Replay.self, from: Data(#"{"frames":8,"events":[{"start":2,"end":6,"player1":16},{"start":3,"end":4,"player2":256},{"start":4,"end":5,"player1":32}]}"#.utf8))
    try events.validate()
    try check(events.frames == 8 && events.input(frame: 1) == VF3Input() && events.input(frame: 3) == VF3Input(player1:16,player2:256) && events.input(frame: 4).player1 == 32 && events.input(frame: 7) == VF3Input(), "Event replay merges players in file order with half-open ranges and neutral tail")
    let normalized = try JSONDecoder().decode(VF3Replay.self, from: Data(#"{"steps":[{"frames":1,"player1":19,"player2":140}]}"#.utf8))
    try normalized.validate()
    try check(normalized.input(frame: 0) == VF3Input(player1:16,player2:128), "Replay normalizes opposing directions before engine routing")
    let empty = try JSONDecoder().decode(VF3Replay.self, from: Data(#"{"frames":8,"events":[]}"#.utf8)); try empty.validate()
    try check(empty.frames == 8 && empty.input(frame: 7) == VF3Input(), "Explicitly bounded empty event replay is neutral")
    for (json, reason) in [
        (#"{"steps":[]}"#, "Reject empty steps"),
        (#"{"steps":[],"events":[]}"#, "Reject both replay formats"),
        (#"{"events":[{"start":2,"end":2}]}"#, "Reject empty event range"),
        (#"{"events":[{"start":-1,"end":2}]}"#, "Reject negative event start"),
        (#"{"events":[]}"#, "Reject empty events without frame count"),
        (#"{"frames":1,"events":[{"start":0,"end":2}]}"#, "Reject events past declared frame count"),
        (#"{"frames":0,"events":[]}"#, "Reject zero total frames"),
        (#"{"frames":2,"steps":[{"frames":1}]}"#, "Reject mismatched step duration"),
        (#"{"steps":[{"frames":0}]}"#, "Reject zero step duration"),
        (#"{"steps":[{"frames":-1}]}"#, "Reject negative step duration"),
        (#"{"steps":[{"frames":1000000},{"frames":1}]}"#, "Reject frame limit overflow"),
        (#"{"steps":[{"frames":1,"player1":1024}]}"#, "Reject unknown player1 bit in steps"),
        (#"{"events":[{"start":0,"end":1,"player2":1024}]}"#, "Reject unknown player2 bit in events"),
        (#"{"steps":[{"frames":1,"player1":-1}]}"#, "Reject negative player mask"),
        (#"{"steps":[{"frames":1,"buttons":16}]}"#, "Reject incompatible single-mask replay"),
        (#"{"events":[{"start":0,"end":1,"steering":1}]}"#, "Reject unrelated analog replay fields"),
        (#"{"frames":1,"events":[],"unknown":true}"#, "Reject unrecognized replay metadata")
    ] { try rejectedReplay(json, reason) }
    for value in ["1", "\"true\"", "[]", "{}"] {
        try rejectedReplay("{\"steps\":[{\"frames\":1,\"invincible\":\(value)}]}", "Reject non-boolean assist in steps: \(value)")
        try rejectedReplay("{\"events\":[{\"start\":0,\"end\":1,\"invincible\":\(value)}]}", "Reject non-boolean assist in events: \(value)")
    }

    let c = VF3Controls()
    var pauses = 0, resumes = 0
    c.onTogglePause = { pauses += 1; c.setPaused(!c.paused) }
    c.onResume = { resumes += 1; c.setPaused(false) }
    let keys: [(UInt16,Int,UInt32)] = [
        (126,0,1),(125,0,2),(123,0,4),(124,0,8),(6,0,16),(7,0,32),(8,0,64),(9,0,128),
        (18,0,256),(36,0,256),(76,0,256),(23,0,512),
        (13,1,1),(1,1,2),(0,1,4),(2,1,8),(3,1,16),(5,1,32),(4,1,64),(38,1,128),
        (19,1,256),(22,1,512)
    ]
    for (key,player,mask) in keys {
        tap(c,key)
        let expected = player == 0 ? VF3Input(player1:mask) : VF3Input(player2:mask)
        try check(c.input() == expected, "Keyboard key \(key) retains a tap for player\(player+1), mask\(mask)")
        try check(c.reserveFrame() == expected && c.reserveFrame() == VF3Input(), "Keyboard key \(key) is consumed by exactly one reservation")
    }
    c.key(123,down:true); c.key(124,down:true); c.key(13,down:true); c.key(3,down:true)
    try check(c.reserveFrame() == VF3Input(player2:17), "Opposed P1 movement cancels without changing P2 up+punch")
    try check(c.reserveFrame() == VF3Input(player2:17), "Held fighting input continues across worker frames")
    c.clearKeyboard(); try check(c.reserveFrame() == VF3Input(), "Keyboard clear removes held and pending inputs")
    tap(c,6); let inFlight = c.reserveFrame(); tap(c,6); tap(c,38)
    try check(inFlight == VF3Input(player1:16) && c.reserveFrame() == VF3Input(player1:16,player2:128), "Later player taps survive an in-flight frame reservation")
    tap(c,23); try check(c.reserveFrame(VF3Input(player2:32)) == VF3Input(player2:32) && c.reserveFrame() == VF3Input(), "Replay reservation replaces and consumes pending live input")
    tap(c,35); try check(c.paused && pauses == 1 && c.input() == VF3Input(), "P pauses both players")
    tap(c,6); tap(c,38); tap(c,23); tap(c,22)
    try check(c.input() == VF3Input(), "Paused attacks and coins cannot queue for either player")
    tap(c,19); try check(!c.paused && resumes == 1 && c.reserveFrame() == VF3Input(), "Player2 Start resumes without entering a game Start")
    c.setActive(false); tap(c,6); tap(c,3); tap(c,35)
    try check(c.input() == VF3Input() && pauses == 1, "Inactive keyboard cannot fight or toggle pause")
    c.setActive(true)
    c.key(34,down:true); c.key(34,down:true); c.key(34,down:true,repeated:true)
    try check(c.input() == VF3Input(invincible:true), "I rising edge queues one assist change outside both fighting masks")
    try check(c.reserveFrame() == VF3Input(invincible:true) && c.reserveFrame() == VF3Input(), "One assist request is consumed by exactly one worker reservation")
    c.key(34,down:false); tap(c,34)
    try check(c.reserveFrame() == VF3Input(invincible:false), "I release rearms the shared assist toggle")
    tap(c,34); tap(c,34)
    try check(c.reserveFrame() == VF3Input(), "Two toggles before a reservation preserve the original assist state")
    tap(c,34); tap(c,6); tap(c,38)
    try check(c.reserveFrame() == VF3Input(player1:16,player2:128,invincible:true), "Assist changes and both players' fighting input share one atomic reservation")
    c.setPaused(true); tap(c,34); c.toggleInvincibility()
    try check(c.reserveFrame() == VF3Input(), "Paused keyboard and menu assist requests are ignored")
    c.setPaused(false); tap(c,34)
    try check(c.reserveFrame().invincible == false, "Pause preserves previously applied assist state")
    tap(c,34); c.setActive(false); tap(c,34); c.toggleInvincibility(); c.setActive(true)
    try check(c.reserveFrame() == VF3Input(), "Focus loss drops pending assist requests and inactive toggles are ignored")
    tap(c,34); _ = c.reserveFrame(VF3Input(player2:32))
    tap(c,34)
    try check(c.reserveFrame() == VF3Input(invincible:true), "Replay reservation discards pending live toggles without changing the applied assist baseline")
    try check(c.reserveFrame(VF3Input(invincible:false)).invincible == false, "Replay applies explicit assist OFF")
    _ = c.reserveFrame(VF3Input(invincible:true)); tap(c,34)
    try check(c.reserveFrame().invincible == false, "Live toggle follows the last explicitly reserved replay assist state")
    _ = c.reserveFrame(VF3Input(invincible:true)); c.resetInvincibility(); tap(c,34)
    try check(c.reserveFrame().invincible == true, "Reset clears the router's assist baseline to OFF")
    c.resetInvincibility()

    let first = GCController.withExtendedGamepad(), second = GCController.withExtendedGamepad(), third = GCController.withExtendedGamepad()
    let p1 = first.extendedGamepad!, p2 = second.extendedGamepad!, p3 = third.extendedGamepad!
    p1.buttonY.setValue(1)
    try check(!c.refreshControllers([first,second]), "Initial two controller assignments are not a disconnect")
    c.pollController(); try check(c.input() == VF3Input(), "Held Triangle on connect requires neutral and cannot enable protection")
    p1.buttonY.setValue(0); c.pollController()
    try check(first.playerIndex == .index1 && second.playerIndex == .index2, "Controllers receive matching player indicators")
    for (pad,player) in [(p1,0),(p2,1)] {
        for (button,mask) in [(pad.buttonX,UInt32(16)),(pad.buttonB,32),(pad.buttonA,64),(pad.leftShoulder,128),(pad.buttonMenu,256),(pad.rightShoulder,512)] {
            press(c,button)
            let expected = player == 0 ? VF3Input(player1:mask) : VF3Input(player2:mask)
            try check(c.reserveFrame() == expected && c.reserveFrame() == VF3Input(), "Player\(player+1) controller mask\(mask) preserves a released tap exactly once")
        }
        pad.buttonY.setValue(1); c.pollController(); c.pollController()
        try check(c.reserveFrame() == VF3Input(invincible:true) && c.reserveFrame() == VF3Input(), "Player\(player+1) Triangle toggles shared P1 protection once while held")
        pad.buttonY.setValue(0); c.pollController(); press(c,pad.buttonY)
        try check(c.reserveFrame() == VF3Input(invincible:false), "Player\(player+1) Triangle rearms after release without Punch or Evade")
    }
    p1.leftThumbstick.xAxis.setValue(0.3); p1.leftThumbstick.yAxis.setValue(-0.3); c.pollController()
    try check(c.reserveFrame() == VF3Input(), "Analog axes within the threshold are neutral")
    p1.leftThumbstick.xAxis.setValue(-0.31); p1.leftThumbstick.yAxis.setValue(0.31); c.pollController()
    try check(c.reserveFrame().player1 == 5 && c.reserveFrame().player1 == 5, "Analog diagonal is held consistently across worker reservations")
    p1.dpad.xAxis.setValue(1); c.pollController()
    try check(c.reserveFrame().player1 == 8, "D-pad overrides both left-stick axes")
    p1.leftThumbstick.xAxis.setValue(0); p1.leftThumbstick.yAxis.setValue(0); p1.dpad.xAxis.setValue(0); c.pollController()
    p1.buttonX.setValue(1); p2.leftShoulder.setValue(1); c.pollController()
    try check(c.reserveFrame() == VF3Input(player1:16,player2:128), "Two controllers fight independently in the same frame")
    try check(!c.refreshControllers([third,second,first]) && c.controllers[0] === first && c.controllers[1] === second, "Extra controller and discovery reordering preserve both assignments")
    c.pollController(); try check(c.reserveFrame() == VF3Input(player1:16,player2:128), "Ignored third controller cannot disturb held attacks")
    p1.buttonX.setValue(0); p2.leftShoulder.setValue(0); c.pollController()
    if let leftClick = p1.leftThumbstickButton, let rightClick = p1.rightThumbstickButton {
        leftClick.setValue(1); rightClick.setValue(1); p1.leftThumbstick.xAxis.setValue(1); c.pollController()
        try check(!c.paused && c.reserveFrame().player1 == 8, "Stick clicks are inert while moving")
        leftClick.setValue(0); rightClick.setValue(0); p1.leftThumbstick.xAxis.setValue(0); c.pollController()
    }
    if let pause = p2.buttonOptions {
        pause.setValue(1); c.pollController(); c.pollController()
        try check(c.paused && pauses == 2, "Player2 Create pauses once while held")
        pause.setValue(0); c.pollController(); p1.buttonMenu.setValue(1); c.pollController()
        try check(!c.paused && resumes == 2 && c.reserveFrame() == VF3Input(), "Player1 Options resumes both players without arcade Start")
        p1.buttonMenu.setValue(0); c.pollController()
        pause.setValue(1); c.pollController(); pause.setValue(0); c.pollController()
        pause.setValue(1); c.pollController(); pause.setValue(0); c.pollController()
        try check(!c.paused && pauses == 4 && c.reserveFrame() == VF3Input(), "Create itself can pause and resume without game input")
    }
    p2.buttonA.setValue(1); c.pollController(); p3.leftShoulder.setValue(1)
    try check(c.refreshControllers([second,third]) && c.controllers[0] === third && c.controllers[1] === second,
              "Assigned disconnect replaces only the vacant player1 slot")
    c.pollController(); try check(c.reserveFrame() == VF3Input(player2:64), "Replacement held Evade is gated while surviving player2 stays assigned")
    p3.leftShoulder.setValue(0); p2.buttonA.setValue(0); c.pollController(); press(c,p3.leftShoulder)
    try check(c.reserveFrame() == VF3Input(player1:128), "Replacement pad becomes usable after neutral and a fresh press")
    press(c,p2.buttonX); c.setActive(false); c.setActive(true); c.pollController()
    try check(c.reserveFrame() == VF3Input(), "Focus transition drops unreserved controller taps")
    p3.buttonA.setValue(1); c.pollController(); c.setPaused(true); c.setPaused(false); c.pollController()
    try check(c.reserveFrame() == VF3Input(), "Held attack cannot leak through pause and resume")
    p3.buttonA.setValue(0); c.pollController(); press(c,p3.buttonA)
    try check(c.reserveFrame() == VF3Input(player1:64), "Release and fresh attack rearm after pause")
    c.clear(); try check(c.reserveFrame() == VF3Input(), "Reset clearing leaves both players neutral")

    c.pollController(); p3.buttonY.setValue(1); c.pollController(); c.setActive(false); c.setActive(true); c.pollController()
    try check(c.reserveFrame() == VF3Input(), "Triangle held across focus return cannot queue protection")
    p3.buttonY.setValue(0); c.pollController(); press(c,p3.buttonY)
    try check(c.reserveFrame() == VF3Input(invincible:true), "Release and fresh Triangle press rearm after focus return")
    c.setPaused(true); c.pollController(); press(c,p2.buttonY); c.setPaused(false); c.pollController()
    try check(c.reserveFrame() == VF3Input(), "Triangle pressed while paused cannot leak through resume")
    press(c,p2.buttonY)
    try check(c.reserveFrame().invincible == false, "A fresh post-resume Triangle press toggles the preserved state")

    // Exercise the same reservation boundary from two real threads. Inputs
    // arriving after reservation must survive while the engine frame is in flight.
    let threaded = VF3Controls(), routingLock = NSRecursiveLock()
    let reserved = DispatchSemaphore(value:0), resume = DispatchSemaphore(value:0)
    let finished = DispatchSemaphore(value:0)
    var reservations = [VF3Input]()
    tap(threaded,34); tap(threaded,6)
    DispatchQueue.global().async {
        routingLock.lock(); reservations.append(threaded.reserveFrame()); routingLock.unlock()
        reserved.signal(); resume.wait()
        routingLock.lock(); reservations.append(threaded.reserveFrame()); reservations.append(threaded.reserveFrame()); routingLock.unlock()
        finished.signal()
    }
    try check(reserved.wait(timeout:.now()+5) == .success, "Dedicated-thread reservation completed without holding the routing lock during execution")
    routingLock.lock(); tap(threaded,34); tap(threaded,38); routingLock.unlock(); resume.signal()
    try check(finished.wait(timeout:.now()+5) == .success, "Dedicated-thread follow-up reservations completed")
    try check(reservations == [VF3Input(player1:16,invincible:true), VF3Input(player2:128,invincible:false), VF3Input()],
              "Assist and fighting events arriving during an in-flight frame survive for exactly the next reservation")

    let result: [String:Any] = ["game":"Virtua Fighter 3","passed":true,"checks":checks,"checkCount":checks.count,
        "engineLinked":false,"engineStubUsed":false,"physicalControllerActuationTested":false,
        "scope":"Actual two-player fighting input router and Apple synthetic GameController values. No game, ROM, engine stub, GUI presentation or audio device is executed."]
    print(String(decoding:try JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys]),as:UTF8.self))
} catch { fputs("Host input test failed: \(error)\n", stderr); exit(1) }

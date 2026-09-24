import Foundation

enum VirtuaFighter3Error: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let value) = self { return value }; return nil }
}
enum VF3Button {
    static let up: UInt32 = 1, down: UInt32 = 2, left: UInt32 = 4, right: UInt32 = 8
    static let punch: UInt32 = 16, kick: UInt32 = 32, guardButton: UInt32 = 64, evade: UInt32 = 128
    static let start: UInt32 = 256, coin: UInt32 = 512, all: UInt32 = 1023
    static func normalize(_ buttons: UInt32) -> UInt32 {
        var value = buttons
        for pair in [up | down, left | right] where value & pair == pair { value &= ~pair }
        return value
    }
}
private struct VF3JSONKey: CodingKey {
    var stringValue: String
    var intValue: Int? { nil }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}
private func rejectUnknownFields(_ decoder: Decoder, allowed: Set<String>) throws {
    let fields = try decoder.container(keyedBy: VF3JSONKey.self).allKeys.map(\.stringValue)
    guard Set(fields).isSubset(of: allowed) else {
        throw VirtuaFighter3Error.message("Unrecognized fighting input or replay fields: \(Set(fields).subtracting(allowed).sorted().joined(separator: ", ")).")
    }
}
struct VF3Input: Codable, Equatable {
    var player1: UInt32 = 0, player2: UInt32 = 0
    init(player1: UInt32 = 0, player2: UInt32 = 0) { self.player1 = player1; self.player2 = player2 }
    private enum CodingKeys: String, CodingKey { case player1, player2 }
    init(from decoder: Decoder) throws {
        try rejectUnknownFields(decoder, allowed: ["player1", "player2", "frames"])
        let values = try decoder.container(keyedBy: CodingKeys.self)
        player1 = try values.decodeIfPresent(UInt32.self, forKey: .player1) ?? 0
        player2 = try values.decodeIfPresent(UInt32.self, forKey: .player2) ?? 0
    }
    func validate() throws {
        guard (player1 | player2) & ~VF3Button.all == 0 else {
            throw VirtuaFighter3Error.message("Invalid fighting input: each player accepts only direction, Punch, Kick, Guard, Evade, Start and Coin flags (bits 0–9).")
        }
    }
    var normalized: VF3Input { VF3Input(player1: VF3Button.normalize(player1), player2: VF3Button.normalize(player2)) }
    var diagnostic: [String: Any] { ["player1": player1, "player2": player2] }
}
struct VF3Replay: Decodable {
    struct Step: Decodable {
        let frames: Int
        let input: VF3Input
        private enum CodingKeys: String, CodingKey { case frames }
        init(from decoder: Decoder) throws {
            frames = try decoder.container(keyedBy: CodingKeys.self).decode(Int.self, forKey: .frames)
            input = try VF3Input(from: decoder)
        }
    }
    struct Event: Decodable {
        let start: Int, end: Int
        let player1: UInt32?, player2: UInt32?
        private enum CodingKeys: String, CodingKey { case start, end, player1, player2 }
        init(from decoder: Decoder) throws {
            try rejectUnknownFields(decoder, allowed: ["start", "end", "player1", "player2"])
            let values = try decoder.container(keyedBy: CodingKeys.self)
            start = try values.decode(Int.self, forKey: .start); end = try values.decode(Int.self, forKey: .end)
            player1 = try values.decodeIfPresent(UInt32.self, forKey: .player1)
            player2 = try values.decodeIfPresent(UInt32.self, forKey: .player2)
        }
        func applying(to input: VF3Input) -> VF3Input {
            VF3Input(player1: player1 ?? input.player1, player2: player2 ?? input.player2)
        }
    }
    let steps: [Step]
    let events: [Event]?
    let declaredFrames: Int?
    private enum CodingKeys: String, CodingKey { case steps, events, frames }
    init(from decoder: Decoder) throws {
        try rejectUnknownFields(decoder, allowed: ["steps", "events", "frames"])
        let values = try decoder.container(keyedBy: CodingKeys.self)
        guard values.contains(.steps) != values.contains(.events) else {
            throw VirtuaFighter3Error.message("A replay must contain either steps or events.")
        }
        steps = try values.decodeIfPresent([Step].self, forKey: .steps) ?? []
        events = try values.decodeIfPresent([Event].self, forKey: .events)
        declaredFrames = try values.decodeIfPresent(Int.self, forKey: .frames)
    }
    var frames: Int { declaredFrames ?? events?.map(\.end).max() ?? steps.reduce(0) { $0 + $1.frames } }
    func validate() throws {
        if let declaredFrames, !(1...1_000_000).contains(declaredFrames) {
            throw VirtuaFighter3Error.message("A replay is limited to one million frames and must contain at least one frame.")
        }
        if let events {
            guard frames > 0 else { throw VirtuaFighter3Error.message("An empty event replay must declare its frame count.") }
            for event in events {
                guard event.start >= 0, event.end > event.start, event.end <= min(frames, 1_000_000) else {
                    throw VirtuaFighter3Error.message("Replay events require 0 ≤ start < end within the replay frame count.")
                }
                try event.applying(to: VF3Input()).validate()
            }
            return
        }
        guard !steps.isEmpty else { throw VirtuaFighter3Error.message("A replay must contain at least one step.") }
        var total = 0
        for step in steps {
            try step.input.validate()
            guard (1...1_000_000).contains(step.frames), total <= 1_000_000 - step.frames else {
                throw VirtuaFighter3Error.message("A replay is limited to one million frames.")
            }
            total += step.frames
        }
        if let declaredFrames, declaredFrames != total {
            throw VirtuaFighter3Error.message("A step replay's declared frame count must equal the sum of its steps.")
        }
    }
    func input(frame: Int) -> VF3Input {
        guard frame >= 0 else { return VF3Input() }
        if let events {
            return events.filter { $0.start <= frame && frame < $0.end }
                .reduce(VF3Input()) { $1.applying(to: $0) }.normalized
        }
        var end = 0
        for step in steps { end += step.frames; if frame < end { return step.input.normalized } }
        return VF3Input()
    }
}

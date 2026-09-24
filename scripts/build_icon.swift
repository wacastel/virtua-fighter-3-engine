import AppKit
let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
func draw(_ size: Int, _ name: String) throws {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let scale = CGFloat(size) / 1024
    let transform = NSAffineTransform(); transform.scale(by: scale); transform.concat()
    let rect = NSRect(x: 42, y: 42, width: 940, height: 940)
    let shape = NSBezierPath(roundedRect: rect, xRadius: 210, yRadius: 210)
    NSGradient(colors: [NSColor(red: 0.08, green: 0.14, blue: 0.27, alpha: 1), NSColor(red: 0.01, green: 0.03, blue: 0.08, alpha: 1)])!.draw(in: shape, angle: -65)
    NSColor(red: 0.17, green: 0.67, blue: 0.94, alpha: 1).setStroke(); shape.lineWidth = 8; shape.stroke()
    let slash = NSBezierPath(); slash.move(to: NSPoint(x: 230, y: 200)); slash.line(to: NSPoint(x: 780, y: 840)); slash.lineWidth = 30
    NSColor(red: 0.9, green: 0.16, blue: 0.14, alpha: 0.8).setStroke(); slash.stroke()
    func centered(_ text: String, _ y: CGFloat, _ size: CGFloat, _ color: NSColor, _ weight: NSFont.Weight) {
        let a: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: size, weight: weight), .foregroundColor: color]
        let s = (text as NSString).size(withAttributes: a)
        (text as NSString).draw(at: NSPoint(x: (1024 - s.width) / 2, y: y), withAttributes: a)
    }
    centered("VIRTUA", 716, 98, .white, .heavy)
    centered("FIGHTER", 595, 110, .white, .heavy)
    centered("3", 168, 410, .white, .black)
    centered("APPLE SILICON", 112, 37, NSColor(white: 0.74, alpha: 1), .semibold)
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent(name))
}
for logical in [16, 32, 128, 256, 512] {
    try draw(logical, "icon_\(logical)x\(logical).png")
    try draw(logical*2, "icon_\(logical)x\(logical)@2x.png")
}

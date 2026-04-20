// get_cg_wid — Print LINE's on-screen window info in a single line.
//
// Usage:   get_cg_wid <app-name>
// Stdout:  "<wid> <x> <y> <w> <h>"
//          wid = kCGWindowNumber (integer)
//          x,y,w,h = kCGWindowBounds, global logical points (Doubles)
// Exit 0:  success
// Exit 1:  no matching window found
// Exit 2:  argument error
//
// Why return bounds too?
//   AppleScript `position of front window` / `size of front window` is
//   unreliable after cross-screen drags, Space switches, or window resize
//   (stale cache, local-coord leaks on external displays). CGWindowBounds
//   is the authoritative source — always global logical points, snapshot-
//   atomic, and correct across multi-monitor setups.
//
// When multiple matching windows exist (e.g. preferences popup + main chat),
// pick the one with the largest area. This is almost always the main chat
// window, matching what "the LINE window" means to the user.

import Foundation
import CoreGraphics

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: get_cg_wid <app-name>\n".data(using: .utf8)!)
    exit(2)
}
let targetOwner = args[1]

let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
guard let infoList = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
        as? [[String: AnyObject]] else {
    FileHandle.standardError.write("CGWindowListCopyWindowInfo returned nil\n".data(using: .utf8)!)
    exit(1)
}

struct Candidate {
    let wid: Int
    let x: Double
    let y: Double
    let w: Double
    let h: Double
    var area: Double { w * h }
}

var candidates: [Candidate] = []

for info in infoList {
    guard let ownerName = info[kCGWindowOwnerName as String] as? String else { continue }
    guard ownerName == targetOwner else { continue }
    guard let windowName = info[kCGWindowName as String] as? String,
          !windowName.isEmpty else { continue }
    guard let windowNumber = info[kCGWindowNumber as String] as? Int else { continue }
    guard let boundsDict = info[kCGWindowBounds as String] as? [String: Any] else { continue }
    let x = (boundsDict["X"] as? NSNumber)?.doubleValue ?? 0
    let y = (boundsDict["Y"] as? NSNumber)?.doubleValue ?? 0
    let w = (boundsDict["Width"] as? NSNumber)?.doubleValue ?? 0
    let h = (boundsDict["Height"] as? NSNumber)?.doubleValue ?? 0
    if w <= 0 || h <= 0 { continue }
    candidates.append(Candidate(wid: windowNumber, x: x, y: y, w: w, h: h))
}

guard let best = candidates.max(by: { $0.area < $1.area }) else {
    FileHandle.standardError.write(
        "no on-screen \(targetOwner) window with non-empty name\n".data(using: .utf8)!
    )
    exit(1)
}

print("\(best.wid) \(best.x) \(best.y) \(best.w) \(best.h)")
exit(0)

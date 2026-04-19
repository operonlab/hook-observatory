// get_cg_wid — Print the kCGWindowNumber of a given app's front window.
//
// Usage:   get_cg_wid <app-name>
// Exit 0:  print <CGWindowNumber> to stdout
// Exit 1:  no matching window found
// Exit 2:  argument error
//
// Uses CGWindowListCopyWindowInfo with the same semantics as Python pyobjc:
//   Quartz.CGWindowListCopyWindowInfo(
//     kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
//     kCGNullWindowID)
// Filters by kCGWindowOwnerName == <app-name> AND kCGWindowName is non-empty.

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

for info in infoList {
    guard let ownerName = info[kCGWindowOwnerName as String] as? String else { continue }
    guard ownerName == targetOwner else { continue }
    guard let windowName = info[kCGWindowName as String] as? String,
          !windowName.isEmpty else { continue }
    guard let windowNumber = info[kCGWindowNumber as String] as? Int else { continue }
    print(windowNumber)
    exit(0)
}

FileHandle.standardError.write(
    "no on-screen \(targetOwner) window with non-empty name\n".data(using: .utf8)!
)
exit(1)

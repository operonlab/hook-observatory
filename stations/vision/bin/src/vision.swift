import Foundation
import Vision
import AppKit

// MARK: - Helpers

func printJSON(_ dict: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys]),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    }
}

func exitWithError(_ message: String, task: String = "unknown") -> Never {
    printJSON(["error": message, "engine": "apple-vision", "task": task])
    exit(1)
}

// MARK: - CLI Entry

let args = CommandLine.arguments
guard args.count >= 2 else {
    exitWithError("Usage: apple-vision <image-file> [--task face|barcode|classify|detect]")
}

let filePath = args[1]
var task = "classify"

if let taskIdx = args.firstIndex(of: "--task"), taskIdx + 1 < args.count {
    task = args[taskIdx + 1]
}

guard FileManager.default.fileExists(atPath: filePath) else {
    exitWithError("File not found: \(filePath)", task: task)
}

guard let nsImage = NSImage(contentsOfFile: filePath),
      let tiff = nsImage.tiffRepresentation,
      let cgImage = NSBitmapImageRep(data: tiff)?.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    exitWithError("Cannot load image: \(filePath)", task: task)
}

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])

// MARK: - Task Dispatch

switch task {
case "face":
    let request = VNDetectFaceRectanglesRequest()
    try! handler.perform([request])
    let results: [[String: Any]] = (request.results ?? []).map { face in
        let box = face.boundingBox
        return [
            "x": box.origin.x,
            "y": box.origin.y,
            "width": box.width,
            "height": box.height,
            "confidence": face.confidence,
        ]
    }
    printJSON(["result": results, "count": results.count, "engine": "apple-vision", "task": "face"])

case "barcode":
    let request = VNDetectBarcodesRequest()
    try! handler.perform([request])
    let results: [[String: Any]] = (request.results ?? []).map { barcode in
        let box = barcode.boundingBox
        return [
            "payload": barcode.payloadStringValue ?? "",
            "symbology": barcode.symbology.rawValue,
            "x": box.origin.x,
            "y": box.origin.y,
            "width": box.width,
            "height": box.height,
        ]
    }
    printJSON(["result": results, "count": results.count, "engine": "apple-vision", "task": "barcode"])

case "classify":
    let request = VNClassifyImageRequest()
    try! handler.perform([request])
    let results: [[String: Any]] = (request.results ?? [])
        .filter { $0.confidence > 0.1 }
        .prefix(10)
        .map { classification in
            return [
                "label": classification.identifier,
                "confidence": classification.confidence,
            ]
        }
    printJSON(["result": results, "count": results.count, "engine": "apple-vision", "task": "classify"])

case "detect":
    let request = VNDetectRectanglesRequest()
    request.maximumObservations = 20
    try! handler.perform([request])
    let results: [[String: Any]] = (request.results ?? []).map { rect in
        let box = rect.boundingBox
        return [
            "x": box.origin.x,
            "y": box.origin.y,
            "width": box.width,
            "height": box.height,
            "confidence": rect.confidence,
        ]
    }
    printJSON(["result": results, "count": results.count, "engine": "apple-vision", "task": "detect"])

default:
    exitWithError("Unknown task: \(task). Supported: face, barcode, classify, detect", task: task)
}

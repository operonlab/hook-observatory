import Foundation
import Vision
import AppKit
import PDFKit

// MARK: - CLI Entry

let args = CommandLine.arguments
guard args.count >= 2 else {
    printJSON(["error": "Usage: apple-ocr <file> [--languages <lang1,lang2>]"])
    exit(1)
}

let filePath = args[1]
var languages = ["zh-Hant", "en"]

if let langIdx = args.firstIndex(of: "--languages"), langIdx + 1 < args.count {
    languages = args[langIdx + 1].split(separator: ",").map(String.init)
}

guard FileManager.default.fileExists(atPath: filePath) else {
    printJSON(["error": "File not found: \(filePath)"])
    exit(1)
}

// MARK: - OCR Processing

let fileURL = URL(fileURLWithPath: filePath)
let ext = fileURL.pathExtension.lowercased()

var allResults: [[String: Any]] = []

if ext == "pdf" {
    guard let pdfDoc = PDFDocument(url: fileURL) else {
        printJSON(["error": "Cannot open PDF: \(filePath)"])
        exit(1)
    }
    for i in 0..<pdfDoc.pageCount {
        guard let page = pdfDoc.page(at: i) else { continue }
        let bounds = page.bounds(for: .mediaBox)
        let size = CGSize(width: bounds.width * 2, height: bounds.height * 2)
        let image = NSImage(size: size)
        image.lockFocus()
        if let ctx = NSGraphicsContext.current?.cgContext {
            ctx.setFillColor(NSColor.white.cgColor)
            ctx.fill(CGRect(origin: .zero, size: size))
            ctx.scaleBy(x: 2.0, y: 2.0)
            page.draw(with: .mediaBox, to: ctx)
        }
        image.unlockFocus()
        guard let tiff = image.tiffRepresentation,
              let cgImage = NSBitmapImageRep(data: tiff)?.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            continue
        }
        let pageResults = recognizeText(cgImage: cgImage, languages: languages)
        for var r in pageResults {
            r["page"] = i + 1
            allResults.append(r)
        }
    }
} else {
    guard let nsImage = NSImage(contentsOfFile: filePath),
          let tiff = nsImage.tiffRepresentation,
          let cgImage = NSBitmapImageRep(data: tiff)?.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        printJSON(["error": "Cannot load image: \(filePath)"])
        exit(1)
    }
    allResults = recognizeText(cgImage: cgImage, languages: languages)
}

let fullText = allResults.map { $0["text"] as? String ?? "" }.joined(separator: "\n")
let output: [String: Any] = [
    "text": fullText,
    "blocks": allResults,
    "languages": languages,
    "engine": "apple-ocr",
    "file": filePath,
]
printJSON(output)

// MARK: - Helpers

func recognizeText(cgImage: CGImage, languages: [String]) -> [[String: Any]] {
    var results: [[String: Any]] = []
    let semaphore = DispatchSemaphore(value: 0)

    let request = VNRecognizeTextRequest { request, error in
        defer { semaphore.signal() }
        if let error = error {
            results.append(["error": error.localizedDescription])
            return
        }
        guard let observations = request.results as? [VNRecognizedTextObservation] else { return }
        for obs in observations {
            guard let candidate = obs.topCandidates(1).first else { continue }
            let box = obs.boundingBox
            results.append([
                "text": candidate.string,
                "confidence": candidate.confidence,
                "x": box.origin.x,
                "y": box.origin.y,
                "width": box.width,
                "height": box.height,
            ])
        }
    }

    request.recognitionLevel = .accurate
    request.recognitionLanguages = languages
    request.usesLanguageCorrection = true

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
    } catch {
        results.append(["error": error.localizedDescription])
        semaphore.signal()
    }

    semaphore.wait()
    return results
}

func printJSON(_ dict: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys]),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    }
}

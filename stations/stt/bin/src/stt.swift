import Foundation
import Speech

// MARK: - Helpers

func printJSON(_ dict: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys]),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    }
}

func exitWithError(_ message: String) -> Never {
    printJSON(["error": message])
    exit(1)
}

// MARK: - CLI Entry

let args = CommandLine.arguments
guard args.count >= 2 else {
    exitWithError("Usage: apple-stt <audio-file> [--language <code>]")
}

let audioPath = args[1]
var language = "zh-TW"

if let langIdx = args.firstIndex(of: "--language"), langIdx + 1 < args.count {
    language = args[langIdx + 1]
}

let fileURL = URL(fileURLWithPath: audioPath)
guard FileManager.default.fileExists(atPath: audioPath) else {
    exitWithError("File not found: \(audioPath)")
}

// MARK: - Speech Recognition (async on global queue, then exit)

DispatchQueue.global(qos: .userInitiated).async {
    let authSemaphore = DispatchSemaphore(value: 0)
    var authStatus: SFSpeechRecognizerAuthorizationStatus = .notDetermined

    SFSpeechRecognizer.requestAuthorization { status in
        authStatus = status
        authSemaphore.signal()
    }

    authSemaphore.wait()

    guard authStatus == .authorized else {
        printJSON(["error": "Speech recognition not authorized. Status: \(authStatus.rawValue)"])
        exit(1)
    }

    let locale = Locale(identifier: language)
    guard let recognizer = SFSpeechRecognizer(locale: locale) else {
        printJSON(["error": "Speech recognizer not available for locale: \(language)"])
        exit(1)
    }

    guard recognizer.isAvailable else {
        printJSON(["error": "Speech recognizer not available (offline or restricted)"])
        exit(1)
    }

    let request = SFSpeechURLRecognitionRequest(url: fileURL)
    request.shouldReportPartialResults = false

    let taskSemaphore = DispatchSemaphore(value: 0)
    var resultJSON: [String: Any] = [:]

    recognizer.recognitionTask(with: request) { result, error in
        if let error = error {
            resultJSON = ["error": error.localizedDescription]
            taskSemaphore.signal()
            return
        }
        guard let result = result else { return }
        if result.isFinal {
            var segments: [[String: Any]] = []
            for segment in result.bestTranscription.segments {
                segments.append([
                    "text": segment.substring,
                    "start": segment.timestamp,
                    "duration": segment.duration,
                    "confidence": segment.confidence,
                ])
            }
            resultJSON = [
                "text": result.bestTranscription.formattedString,
                "language": language,
                "segments": segments,
                "engine": "apple-stt",
            ]
            taskSemaphore.signal()
        }
    }

    taskSemaphore.wait()
    printJSON(resultJSON)
    exit(0)
}

// Keep main thread alive with RunLoop so callbacks can fire
dispatchMain()

import Foundation
import AVFoundation

// MARK: - Helpers

func printJSON(_ dict: [String: Any]) {
    if let data = try? JSONSerialization.data(withJSONObject: dict, options: [.prettyPrinted, .sortedKeys]),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    }
}

func printJSONArray(_ arr: [[String: Any]]) {
    if let data = try? JSONSerialization.data(withJSONObject: arr, options: [.prettyPrinted, .sortedKeys]),
       let str = String(data: data, encoding: .utf8) {
        print(str)
    }
}

func exitWithError(_ message: String) -> Never {
    printJSON(["error": message, "engine": "apple-tts"])
    exit(1)
}

// MARK: - CLI Entry

let args = CommandLine.arguments

if args.contains("--list-voices") {
    let voices = AVSpeechSynthesisVoice.speechVoices()
    let result: [[String: Any]] = voices.map { voice in
        return [
            "id": voice.identifier,
            "name": voice.name,
            "language": voice.language,
        ]
    }
    printJSONArray(result)
    exit(0)
}

guard args.count >= 2 else {
    exitWithError("Usage: apple-tts <text> [--voice <id>] [--speed <float>] [--output <path>]")
}

let text = args[1]
var voiceId: String? = nil
var speed: Float = 1.0
var outputPath: String? = nil

var i = 2
while i < args.count {
    switch args[i] {
    case "--voice":
        i += 1; if i < args.count { voiceId = args[i] }
    case "--speed":
        i += 1; if i < args.count { speed = Float(args[i]) ?? 1.0 }
    case "--output":
        i += 1; if i < args.count { outputPath = args[i] }
    default: break
    }
    i += 1
}

let outFile = outputPath ?? NSTemporaryDirectory() + "tts_apple_\(ProcessInfo.processInfo.globallyUniqueString).wav"

// MARK: - Synthesize (on background queue, RunLoop required for callbacks)

DispatchQueue.global(qos: .userInitiated).async {
    let synthesizer = AVSpeechSynthesizer()
    let utterance = AVSpeechUtterance(string: text)
    utterance.rate = AVSpeechUtteranceDefaultSpeechRate * speed

    if let vid = voiceId, let voice = AVSpeechSynthesisVoice(identifier: vid) {
        utterance.voice = voice
    } else {
        utterance.voice = AVSpeechSynthesisVoice(language: "zh-TW") ?? AVSpeechSynthesisVoice(language: "en-US")
    }

    let semaphore = DispatchSemaphore(value: 0)
    var totalFrames: AVAudioFrameCount = 0
    var audioFile: AVAudioFile? = nil

    synthesizer.write(utterance) { buffer in
        guard let pcmBuffer = buffer as? AVAudioPCMBuffer, pcmBuffer.frameLength > 0 else {
            semaphore.signal()
            return
        }

        if audioFile == nil {
            let url = URL(fileURLWithPath: outFile)
            do {
                audioFile = try AVAudioFile(
                    forWriting: url,
                    settings: pcmBuffer.format.settings,
                    commonFormat: .pcmFormatFloat32,
                    interleaved: false
                )
            } catch {
                printJSON(["error": "Failed to create audio file: \(error.localizedDescription)", "engine": "apple-tts"])
                exit(1)
            }
        }

        do {
            try audioFile?.write(from: pcmBuffer)
            totalFrames += pcmBuffer.frameLength
        } catch {
            printJSON(["error": "Failed to write audio: \(error.localizedDescription)", "engine": "apple-tts"])
            exit(1)
        }
    }

    semaphore.wait()

    let sampleRate = audioFile?.processingFormat.sampleRate ?? 22050
    let duration = Double(totalFrames) / sampleRate

    printJSON([
        "audio_path": outFile,
        "duration": duration,
        "sample_rate": Int(sampleRate),
        "engine": "apple-tts",
    ])
    exit(0)
}

// Keep main thread alive for callbacks
dispatchMain()

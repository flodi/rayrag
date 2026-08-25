import Foundation
import Vision
import AppKit

// OCR con il framework Vision di macOS: un percorso immagine per argomento,
// il testo riconosciuto su stdout.
for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("immagine illeggibile: \(path)\n".data(using: .utf8)!)
        continue
    }
    let richiesta = VNRecognizeTextRequest()
    richiesta.recognitionLevel = .accurate
    richiesta.recognitionLanguages = ["it-IT", "en-US"]
    richiesta.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    do { try handler.perform([richiesta]) } catch {
        FileHandle.standardError.write("errore Vision: \(error)\n".data(using: .utf8)!)
        continue
    }
    let righe = (richiesta.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    print(righe.joined(separator: "\n"))
}

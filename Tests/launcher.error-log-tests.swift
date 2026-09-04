import Foundation

@main struct LauncherErrorLogTests {
    static func main() throws {
        var parser = LauncherErrorLog()
        precondition(parser.consume("INFO: ready\nWARNING: retry\n") == "")
        precondition(parser.consume("ERR") == "")
        precondition(parser.consume("OR: first\n") == "ERROR: first\n")
        let trace = "Traceback (most recent call last):\n  File test.py, line 1\nValueError: second\n"
        precondition(parser.consume(trace + "INFO: ready\n") == trace)
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try LauncherErrorLog.save("", root: root)
        let file = root.appendingPathComponent("launcher-errors.log")
        precondition(!FileManager.default.fileExists(atPath: file.path))
        try LauncherErrorLog.save("first\n", root: root)
        try LauncherErrorLog.save("second\n", root: root)
        let saved = try String(contentsOf: file, encoding: .utf8)
        precondition(saved == "first\nsecond\n")
        print("PASS: error filtering, traceback, chunking and append-only storage")
    }
}

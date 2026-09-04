import Foundation

// 从分块输出中提取错误及异常堆栈。
struct LauncherErrorLog {
    private var pending = ""
    private var traceback = false

    mutating func consume(_ text: String) -> String {
        pending += text
        var output = ""
        while let newline = pending.firstIndex(of: "\n") {
            let line = String(pending[..<newline])
            pending.removeSubrange(...newline)
            if line.hasPrefix("Traceback (most recent call last):") {
                traceback = true
                output += line + "\n"
            } else if traceback {
                output += line + "\n"
                if !line.isEmpty && !line.hasPrefix(" ") && !line.hasPrefix("\t") {
                    traceback = false
                }
            } else if line.range(of: #"\b(ERROR|CRITICAL|FATAL)\b"#, options: .regularExpression) != nil {
                output += line + "\n"
            }
        }
        return output
    }

    // 追加错误日志，保留历史内容。
    static func save(_ text: String, root: URL) throws {
        guard !text.isEmpty else { return }
        let file = root.appendingPathComponent("launcher-errors.log")
        if !FileManager.default.fileExists(atPath: file.path) {
            guard FileManager.default.createFile(atPath: file.path, contents: nil,
                attributes: [.posixPermissions: 0o600]) else {
                throw CocoaError(.fileWriteUnknown)
            }
        }
        let handle = try FileHandle(forWritingTo: file)
        defer { try? handle.close() }
        try handle.seekToEnd()
        try handle.write(contentsOf: Data(text.utf8))
    }
}

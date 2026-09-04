import Foundation

// 解析部署标记，将步骤和下载进度转换为界面状态。
struct DeploymentProgress {
    static let totalSteps = 9
    private(set) var step = 1
    private(set) var title = "准备环境管理器"
    private(set) var detail = "正在准备应用专属目录…"
    private(set) var completed = false
    private var buffer = Data()

    var fraction: Double { Double(completed ? Self.totalSteps : step - 1) / Double(Self.totalSteps) }
    var label: String { completed ? "部署完成" : "步骤 \(step) / \(Self.totalSteps)" }

    // 推进部署步骤
    mutating func advance(_ step: Int, title: String) {
        guard (1...Self.totalSteps).contains(step), step >= self.step, !completed else { return }
        self.step = step
        self.title = title
        detail = "正在执行，请稍候…"
    }

    // 标记部署完成
    mutating func finish() {
        step = Self.totalSteps
        completed = true
        title = "部署完成"
        detail = "本地 Web App 已就绪"
    }

    // 解析分块日志与进度标记
    @discardableResult
    mutating func consume(_ data: Data) -> String {
        buffer.append(data)
        var messages = ""
        while let end = buffer.firstIndex(where: { $0 == 10 || $0 == 13 }) {
            let line = String(decoding: buffer[..<end], as: UTF8.self).trimmingCharacters(in: .whitespaces)
            buffer.removeSubrange(...end)
            if line.hasPrefix("@@ALAS_STAGE:") {
                let parts = line.split(separator: ":", maxSplits: 2)
                if parts.count == 3, let stage = Int(parts[1]) {
                    advance(stage, title: String(parts[2]))
                }
            } else if !completed, !line.isEmpty,
                      ["Receiving objects:", "Resolving deltas:", "Enumerating objects:",
                       "Counting objects:", "Compressing objects:", "Updating files:",
                       "继续下载核心", "核心对象已下载", "Collecting ", "Downloading ",
                       "Linking ", "当前镜像安装失败", "OCR ", "已是上游最新版本"].contains(where: line.contains) {
                detail = String(line.prefix(180))
            } else if !line.isEmpty {
                messages += line + "\n"
            }
        }
        if buffer.count > 65_536 { buffer.removeAll(keepingCapacity: true) }
        return messages
    }

    // 清空未完成日志片段
    mutating func resetStream() { buffer.removeAll(keepingCapacity: true) }
}

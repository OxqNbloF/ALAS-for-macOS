import Foundation

// 保存失败阶段、原因和最近输出，供用户导出。
enum DeploymentFailureReport {
    static func save(error: String, stage: String, logs: String, directory: URL) throws -> URL {
        let documents = directory
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let filename = "ALAS-部署失败-\(formatter.string(from: Date()))-\(UUID().uuidString.prefix(8)).log"
        let file = documents.appendingPathComponent(filename)
        let report = "时间：\(Date())\n阶段：\(stage)\n错误：\(error)\n\n本次部署最近日志：\n\(logs)\n"
        try Data(report.utf8).write(to: file, options: .withoutOverwriting)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        return file
    }
}

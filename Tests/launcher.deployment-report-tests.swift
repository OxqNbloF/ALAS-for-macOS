import Foundation

@main struct DeploymentFailureReportTests {
    static func main() throws {
        let files = FileManager.default
        let directory = files.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try files.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? files.removeItem(at: directory) }
        let first = try DeploymentFailureReport.save(error: "下载超时", stage: "下载核心",
            logs: "ERROR: timeout", directory: directory)
        let second = try DeploymentFailureReport.save(error: "安装失败", stage: "配置环境",
            logs: "ERROR: install", directory: directory)
        precondition(first != second)
        let contents = try String(contentsOf: first, encoding: .utf8)
        precondition(contents.contains("下载超时") && contents.contains("下载核心"))
        precondition(contents.contains("ERROR: timeout"))
        let permissions = try files.attributesOfItem(atPath: first.path)[.posixPermissions] as! NSNumber
        precondition(permissions.intValue == 0o600)
        let count = try files.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil).count
        precondition(count == 2)
        print("PASS: failure report content, unique names and private permissions")
    }
}

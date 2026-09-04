import Foundation

// 创建和检查固定数据目录，拒绝包内路径及符号链接。
enum LauncherStorage {
    // 数据统一放在用户的 Application Support 下。
    static var dataRoot: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("AzurLaneAutoScript", isDirectory: true)
    }

    // 创建运行目录，保留已有数据。
    static func prepare(root: URL) throws {
        let files = FileManager.default
        var ancestor = root.standardizedFileURL
        while !files.fileExists(atPath: ancestor.path), ancestor.path != "/" {
            ancestor.deleteLastPathComponent()
        }
        let resolved = ancestor.resolvingSymlinksInPath().standardizedFileURL
        guard root.standardizedFileURL.path != "/",
              !(root.pathComponents + resolved.pathComponents).contains(where: { $0.lowercased().hasSuffix(".app") }) else {
            throw CocoaError(.fileWriteNoPermission)
        }
        try files.createDirectory(at: root, withIntermediateDirectories: true,
                                  attributes: [.posixPermissions: 0o700])
    }

}

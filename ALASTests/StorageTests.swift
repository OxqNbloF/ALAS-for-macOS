import Foundation
import Testing
@testable import ALAS_for_macOS

// 固定数据目录、路径保护与重复准备保留原数据。
struct LauncherStorageTests {
    @Test func externalRootPathProtectionAndPreservation() throws {
        let files = FileManager.default
        let parent = files.temporaryDirectory.appendingPathComponent("alas-storage-\(UUID().uuidString)")
        let root = parent.appendingPathComponent("Library/Application Support/AzurLaneAutoScript")
        defer { try? files.removeItem(at: parent) }

        try LauncherStorage.prepare(root: root)

        try files.createDirectory(at: root.appendingPathComponent("data/config"), withIntermediateDirectories: true)
        try Data("new-setting".utf8).write(to: root.appendingPathComponent("data/config/alas.json"))
        try LauncherStorage.prepare(root: root)
        let value = try String(contentsOf: root.appendingPathComponent("data/config/alas.json"), encoding: .utf8)
        precondition(value == "new-setting")
        precondition(!files.fileExists(atPath: root.appendingPathComponent("active.json").path))
        precondition(!LauncherStorage.dataRoot.path.contains(".app/"))
        let bundle = parent.appendingPathComponent("Test.APP/Contents/Resources")
        try files.createDirectory(at: bundle, withIntermediateDirectories: true)
        let alias = parent.appendingPathComponent("alias")
        try files.createSymbolicLink(at: alias, withDestinationURL: bundle)
        for invalid in [bundle.appendingPathComponent("ALAS"), alias.appendingPathComponent("ALAS")] {
            do {
                try LauncherStorage.prepare(root: invalid)
                preconditionFailure("Bundle storage must be rejected")
            } catch { }
        }
        precondition(!files.fileExists(atPath: bundle.appendingPathComponent("ALAS").path))
        precondition(LauncherStorage.dataRoot.lastPathComponent == "AzurLaneAutoScript")
        precondition(LauncherStorage.dataRoot.deletingLastPathComponent() ==
               files.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0])
        try LauncherStorage.prepare(root: root)
        let preserved = try String(contentsOf: root.appendingPathComponent("data/config/alas.json"), encoding: .utf8)
        precondition(preserved == "new-setting", "Repeated preparation must preserve existing data")
    }
}

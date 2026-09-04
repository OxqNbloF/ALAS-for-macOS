import Foundation

@main
struct LauncherStorageTests {
    static func main() throws {
        let files = FileManager.default
        let parent = files.temporaryDirectory.appendingPathComponent("alas-storage-\(UUID().uuidString)")
        let root = parent.appendingPathComponent("Library/Application Support/AzurLaneAutoScript")
        defer { try? files.removeItem(at: parent) }

        try LauncherStorage.prepare(root: root)

        try files.createDirectory(at: root.appendingPathComponent("data/config"), withIntermediateDirectories: true)
        try Data("new-setting".utf8).write(to: root.appendingPathComponent("data/config/alas.json"))
        try LauncherStorage.prepare(root: root)
        let value = try String(contentsOf: root.appendingPathComponent("data/config/alas.json"), encoding: .utf8)
        assert(value == "new-setting")
        assert(!files.fileExists(atPath: root.appendingPathComponent("active.json").path))
        assert(!LauncherStorage.dataRoot.path.contains(".app/"))
        let bundle = parent.appendingPathComponent("Test.APP/Contents/Resources")
        try files.createDirectory(at: bundle, withIntermediateDirectories: true)
        let alias = parent.appendingPathComponent("alias")
        try files.createSymbolicLink(at: alias, withDestinationURL: bundle)
        for invalid in [bundle.appendingPathComponent("ALAS"), alias.appendingPathComponent("ALAS")] {
            do {
                try LauncherStorage.prepare(root: invalid)
                fatalError("Bundle storage must be rejected")
            } catch { }
        }
        assert(!files.fileExists(atPath: bundle.appendingPathComponent("ALAS").path))
        assert(LauncherStorage.dataRoot.lastPathComponent == "AzurLaneAutoScript")
        assert(LauncherStorage.dataRoot.deletingLastPathComponent() ==
               files.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0])
        try LauncherStorage.prepare(root: root)
        let preserved = try String(contentsOf: root.appendingPathComponent("data/config/alas.json"), encoding: .utf8)
        assert(preserved == "new-setting", "Repeated preparation must preserve existing data")
        print("LauncherStorage: external root, path protection and existing data preservation passed")
    }
}

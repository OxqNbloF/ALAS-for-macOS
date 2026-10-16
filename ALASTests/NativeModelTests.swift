import Foundation
import Testing
@testable import ALAS_for_macOS

// 原生客户端模型：调度时间同步、手动编辑保留与消息计时。
struct NativeModelTests {
    @Test @MainActor func nextRunSyncEditPreservationAndMessageExpiry() async throws {
        let model = NativeModel()
        let field = NativeField(id: "Main.Scheduler.NextRun", title: "Next run", help: "", kind: "datetime",
                                value: .string("2026-09-04 10:00:00"), defaultValue: .string("2020-01-01 00:00:00"),
                                readOnly: false, options: [])
        model.profile = "test"
        model.catalog = NativeCatalog(name: "test", mod: "alas", sections: [
            NativeSection(id: "main", title: "", tasks: [NativeTask(id: "Main", title: "", help: "", tool: false,
                groups: [NativeGroup(id: "Scheduler", title: "", fields: [field])])])])
        func snapshot(_ time: String) -> NativeSnapshot {
            NativeSnapshot(profiles: [], templates: [], schedule: [NativeScheduledTask(id: "Main", title: "", nextRun: time, state: "waiting")],
                           logs: "", revision: "", remoteAddress: "", remoteState: 0, remoteEnabled: false)
        }
        model.applySnapshot(snapshot("2026-09-04 11:00:00"))
        precondition(model.fields[0].value == .string("2026-09-04 11:00:00"))
        precondition(!model.dirty)
        model.edit(model.fields[0], .string("2026-09-05 08:30:00"))
        model.applySnapshot(snapshot("2026-09-04 12:00:00"))
        precondition(model.value(model.fields[0]) == .string("2026-09-05 08:30:00"))
        precondition(model.fields[0].value == .string("2026-09-04 11:00:00"), "Keep original conflict-check value")
        model.edits = [:]
        model.applySnapshot(snapshot("2026-09-04 12:00:00"))
        precondition(model.fields[0].value == .string("2026-09-04 12:00:00"))
        precondition(!model.dirty)
        model.message = "核心已是最新版本"
        try await Task.sleep(for: .seconds(3))
        precondition(model.message != nil)
        // 同文提示也重新计时
        model.message = "核心已是最新版本"
        try await Task.sleep(for: .seconds(3))
        precondition(model.message != nil)
        try await Task.sleep(for: .milliseconds(2300))
        precondition(model.message == nil)
        model.message = "配置已保存"
        model.message = nil
        precondition(model.message == nil)
        let values: [ConfigValue] = [.null, .bool(false), .bool(true), .number(1), .number(1.25),
            .string("001"), .array([.string("a"), .null]), .object(["count": .number(3)])]
        for value in values {
            let decoded = try JSONDecoder().decode(ConfigValue.self, from: JSONEncoder().encode(value))
            precondition(decoded == value)
        }
    }

    // 需要已部署环境的可选集成测试：ALAS_TEST_DATA=<运行数据目录>。
    @Test @MainActor func liveCatalogDecoding() async throws {
        guard let directory = ProcessInfo.processInfo.environment["ALAS_TEST_DATA"] else { return }
        struct Endpoint: Decodable { let url: URL; let token: String }
        let file = URL(fileURLWithPath: directory).appendingPathComponent("endpoint.json")
        let endpoint = try JSONDecoder().decode(Endpoint.self, from: Data(contentsOf: file))
        let config = URLSessionConfiguration.ephemeral; config.connectionProxyDictionary = [:]
        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel() }
        func fetch<T: Decodable>(_ path: String) async throws -> T {
            var request = URLRequest(url: URL(string: endpoint.url.absoluteString + path)!)
            request.setValue("Bearer " + endpoint.token, forHTTPHeaderField: "Authorization")
            let (data, response) = try await session.data(for: request)
            precondition((response as? HTTPURLResponse)?.statusCode == 200)
            return try JSONDecoder().decode(T.self, from: data)
        }
        let snapshot: NativeSnapshot = try await fetch("/native/snapshot")
        if let profile = snapshot.profiles.first {
            let escaped = profile.id.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed)!
            let catalog: NativeCatalog = try await fetch("/native/catalog?name=\(escaped)&language=zh-CN")
            let tasks = catalog.sections.flatMap(\.tasks)
            precondition(!tasks.isEmpty)
            for field in tasks.flatMap({ $0.groups.flatMap(\.fields) }) {
                _ = field.value.text; _ = field.value.any
            }
        }
    }
}

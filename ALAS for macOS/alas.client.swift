import AppKit
import Combine
import Foundation
import UniformTypeIdentifiers

// 连接本机核心接口，轮询状态并管理未保存的配置。
@MainActor
final class NativeModel: ObservableObject {
    @Published var snapshot: NativeSnapshot?
    @Published var catalog: NativeCatalog?
    @Published var profile = ""
    @Published var page = "home"
    @Published var search = ""
    @Published var logSearch = ""
    @Published var followLogs = true
    @Published var language = "zh-CN"
    @Published var appearance = "system"
    @Published var edits: [String: ConfigValue] = [:]
    @Published var busy = false
    @Published var error: String?
    @Published var connectionError: String?
    @Published var message: String? {
        didSet {
            messageDismissTask?.cancel()
            messageDismissTask = nil
            guard message != nil else { return }
            messageDismissTask = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(5)) }
                catch { return }
                guard !Task.isCancelled else { return }
                self?.message = nil
            }
        }
    }
    private var messageDismissTask: Task<Void, Never>?
    @Published var upstream = ""
    private var baseURL: URL?
    private var token = ""
    private var epoch = UUID()
    private let session: URLSession = {
        let c = URLSessionConfiguration.ephemeral
        c.connectionProxyDictionary = [:]
        c.timeoutIntervalForRequest = 40
        c.urlCache = nil
        return URLSession(configuration: c)
    }()
    var tasks: [NativeTask] { catalog?.sections.flatMap(\.tasks) ?? [] }
    var selectedTask: NativeTask? { tasks.first { page == "task:" + $0.id } }
    var currentProfile: NativeProfile? { snapshot?.profiles.first { $0.id == profile } }
    var running: Bool { currentProfile?.state == 1 }
    var dirty: Bool { !edits.isEmpty }
    var fields: [NativeField] { tasks.flatMap { $0.groups.flatMap(\.fields) } }

    // 发送带认证的本地请求
    func request<T: Decodable>(_ operation: String, query: [String: String] = [:], body: [String: Any]? = nil) async throws -> T {
        guard let baseURL else { throw failure("核心服务尚未连接") }
        var parts = URLComponents(url: baseURL.appendingPathComponent("native/" + operation), resolvingAgainstBaseURL: false)!
        parts.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        var request = URLRequest(url: parts.url!)
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            let value = try? JSONSerialization.jsonObject(with: data) as? [String: String]
            throw failure(value?["error"] ?? "核心接口请求失败")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    // 连接核心并定时刷新
    func connect(url: URL, token: String) async {
        let identifier = UUID(); epoch = identifier
        baseURL = url; self.token = token
        do {
            let preferences: [String: String] = try await request("ui-preferences")
            language = preferences["language"] ?? "zh-CN"
            appearance = preferences["appearance"] ?? "system"
            try await refresh()
            if profile.isEmpty || !(snapshot?.profiles.contains { $0.id == profile } ?? false) {
                profile = snapshot?.profiles.first?.id ?? ""
            }
            if !profile.isEmpty { try await loadCatalog() }
        } catch { connectionError = error.localizedDescription }
        while !Task.isCancelled && epoch == identifier {
            do {
                try await Task.sleep(for: .seconds(2))
                if !busy {
                    try await refresh()
                    if catalog == nil, let first = snapshot?.profiles.first {
                        if profile.isEmpty { profile = first.id }
                        try await loadCatalog()
                    }
                }
            } catch is CancellationError { return }
            catch { connectionError = error.localizedDescription }
        }
    }

    // 刷新当前配置运行状态
    func refresh() async throws {
        let selected = profile
        let result: NativeSnapshot = try await request("snapshot", query: ["name": selected, "language": language])
        guard selected == profile else { return }
        applySnapshot(result); connectionError = nil
    }
    // 同步未编辑的调度时间，不覆盖本地输入。
    func applySnapshot(_ result: NativeSnapshot) {
        snapshot = result
        synchronizeNextRuns()
    }

    private func synchronizeNextRuns() {
        guard var updated = catalog, updated.name == profile, let snapshot else { return }
        let times = Dictionary(snapshot.schedule.map { ($0.id, $0.nextRun) }, uniquingKeysWith: { first, _ in first })
        for section in updated.sections.indices {
            for task in updated.sections[section].tasks.indices {
                let taskID = updated.sections[section].tasks[task].id
                guard let time = times[taskID] else { continue }
                for group in updated.sections[section].tasks[task].groups.indices {
                    for field in updated.sections[section].tasks[task].groups[group].fields.indices {
                        let id = updated.sections[section].tasks[task].groups[group].fields[field].id
                        if id == "\(taskID).Scheduler.NextRun", edits[id] == nil {
                            updated.sections[section].tasks[task].groups[group].fields[field].value = .string(time)
                        }
                    }
                }
            }
        }
        catalog = updated
    }

    // 读取配置字段与任务目录
    func loadCatalog() async throws {
        let selected = profile
        let result: NativeCatalog = try await request("catalog", query: ["name": selected, "language": language])
        guard selected == profile else { return }
        catalog = result; edits = [:]
    }
    // 保护未保存编辑并切换配置
    func selectProfile(_ name: String) {
        guard name != profile else { return }
        guard !dirty else { error = "有未保存的修改，请先保存或放弃修改后再切换配置。"; return }
        perform {
            self.profile = name; self.catalog = nil; self.snapshot = nil; self.page = "overview"
            try await self.loadCatalog(); try await self.refresh()
        }
    }
    // 优先读取未保存字段值
    func value(_ field: NativeField) -> ConfigValue { edits[field.id] ?? field.value }
    // 暂存字段编辑
    func edit(_ field: NativeField, _ value: ConfigValue) {
        if value == field.value { edits.removeValue(forKey: field.id) } else { edits[field.id] = value }
        message = nil
    }
    // 提交修改并刷新配置
    func save() {
        guard dirty else { return }
        let changes = fields.compactMap { field -> [String: Any]? in
            guard let value = edits[field.id] else { return nil }
            return ["id": field.id, "original": field.value.any, "value": value.any]
        }
        perform {
            let _: [String: Bool] = try await self.request("save", body: ["name": self.profile, "changes": changes])
            try await self.loadCatalog(); self.message = "配置已保存"
            try await self.refresh()
        }
    }
    // 放弃编辑并重新载入
    func discard() { perform { try await self.loadCatalog() } }
    // 启动或停止核心任务
    func control(function: String? = nil, stop: Bool = false) {
        guard stop || !dirty else { error = "请先保存配置，再启动任务。"; return }
        perform {
            var body: [String: Any] = ["name": self.profile, "action": stop ? "stop" : "start"]
            if let function { body["function"] = function }
            let _: [String: Bool] = try await self.request("action", body: body)
            try await self.refresh()
        }
    }
    // 从来源创建配置
    func create(name: String, origin: String) {
        perform {
            let _: [String: Bool] = try await self.request("create", body: ["name": name, "origin": origin])
            self.profile = name; self.snapshot = nil; self.page = "overview"
            try await self.loadCatalog(); try await self.refresh()
        }
    }
    // 删除配置并重选当前项
    func deleteConfig(_ name: String) {
        guard !dirty else { error = "请先保存或放弃当前修改。"; return }
        perform {
            let _: [String: Bool] = try await self.request("delete", body: ["name": name, "confirm": true])
            if self.profile == name {
                self.profile = ""; self.catalog = nil; self.snapshot = nil
                try await self.refresh()
                self.profile = self.snapshot?.profiles.first?.id ?? ""
                if !self.profile.isEmpty { try await self.loadCatalog() }
                else { self.page = "home" }
            }
            try await self.refresh()
            self.message = "配置 \(name) 已删除"
        }
    }
    // 导出配置到所选文件
    func exportConfig(_ name: String) {
        perform {
            let data: [String: String] = try await self.request("transfer", body: ["name": name, "action": "export"])
            let panel = NSSavePanel(); panel.allowedContentTypes = [.json]
            panel.nameFieldStringValue = data["filename"] ?? "alas.json"
            guard panel.runModal() == .OK, let url = panel.url else { return }
            try (data["content"] ?? "").write(to: url, atomically: true, encoding: .utf8)
        }
    }
    // 校验并导入配置文件
    func importConfig() {
        guard !dirty else { error = "请先保存或放弃当前修改。"; return }
        let panel = NSOpenPanel(); panel.allowedContentTypes = [.json]; panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let url = panel.url else { return }
        perform {
            let fileSize = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
            guard fileSize <= 1024 * 1024 else { throw self.failure("配置文件不能超过 1 MB") }
            let parts = url.deletingPathExtension().lastPathComponent.split(separator: ".").map(String.init)
            let name = parts.first ?? ""
            let mod = parts.count == 2 ? parts[1] : "alas"
            var overwrite = false
            if self.snapshot?.profiles.contains(where: { $0.id == name }) == true {
                let alert = NSAlert(); alert.messageText = "覆盖配置 \(name)？"
                alert.informativeText = "此操作会替换该配置的全部设置，运行中的配置不能导入。"
                alert.addButton(withTitle: "取消"); alert.addButton(withTitle: "覆盖")
                guard alert.runModal() == .alertSecondButtonReturn else { return }
                overwrite = true
            }
            let content = try String(contentsOf: url, encoding: .utf8)
            let _: [String: Bool] = try await self.request("transfer", body: ["action": "import", "name": name,
                "mod": mod, "content": content, "overwrite": overwrite])
            self.profile = name; self.snapshot = nil; try await self.loadCatalog(); try await self.refresh()
            self.message = "配置已导入"
        }
    }
    // 比较上游与本地核心版本
    func checkUpdate() {
        perform {
            let result: [String: String] = try await self.request("check-update")
            self.upstream = result["revision"] ?? ""
            self.message = self.upstream == self.snapshot?.revision ? "核心已是最新版本" : "发现新核心版本"
        }
    }
    // 保存语言与外观偏好
    func preferences(language: String? = nil, appearance: String? = nil) {
        guard !dirty else { error = "请先保存或放弃修改，再切换界面设置。"; return }
        perform {
            let lang = language ?? self.language, theme = appearance ?? self.appearance
            let _: [String: Bool] = try await self.request("save-preferences", body: ["language": lang, "appearance": theme])
            self.language = lang; self.appearance = theme
            if !self.profile.isEmpty { try await self.loadCatalog() }
        }
    }
    // 测试错误信息传递
    func diagnostic() { perform { let _: [String: String] = try await self.request("diagnostic", body: [:]) } }
    // 统一更新请求状态和错误提示。
    func perform(_ operation: @escaping () async throws -> Void) {
        guard !busy else { return }
        busy = true; error = nil; message = nil
        Task {
            defer { busy = false }
            do { try await operation() }
            catch { self.error = error.localizedDescription }
        }
    }
    // 构造接口错误
    func failure(_ message: String) -> NSError { NSError(domain: "ALAS.Native", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
}

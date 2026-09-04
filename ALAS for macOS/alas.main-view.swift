import SwiftUI
import AppKit

// 原生主界面：任务导航、配置编辑、调度和核心管理。
struct NativeMainView: View {
    let url: URL
    let token: String
    @EnvironmentObject private var launcher: LauncherModel
    @StateObject private var model = NativeModel()
    @State private var expanded: Set<String> = ["Alas"]
    @State private var creating = false
    @State private var newName = ""
    @State private var origin = "template-alas"
    @State private var confirmStop = false
    @State private var confirmUpdate = false
    @State private var confirmDiscard = false
    @State private var showCoreLogs = false
    @State private var deletingProfile: String?

    var body: some View {
        NavigationSplitView(columnVisibility: .constant(.all)) {
            sidebar
                .navigationSplitViewColumnWidth(min: 210, ideal: 245, max: 340)
                .navigationTitle(model.profile.isEmpty ? "尚未选择配置" : model.profile)
                .modifier(PersistentSidebarAppearance())
        } detail: {
            VStack(spacing: 0) {
                if let connectionError = model.connectionError {
                    Label("连接中断：\(connectionError)", systemImage: "wifi.exclamationmark")
                        .font(.callout).foregroundStyle(.orange).padding(10)
                }
                if model.dirty {
                    HStack {
                        Label("\(model.edits.count) 项未保存修改", systemImage: "pencil.circle")
                        Spacer()
                        Button("放弃修改") { confirmDiscard = true }
                        Button("保存配置") { model.save() }.buttonStyle(.borderedProminent).keyboardShortcut("s")
                    }.padding(12).background(Color.accentColor.opacity(0.08))
                } else if let message = model.message {
                    HStack { Label(message, systemImage: "checkmark.circle"); Spacer() }
                        .foregroundStyle(.secondary).padding(10)
                }
                detail.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
            .frame(minWidth: 540)
        .navigationTitle(title)
        .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    if !model.profile.isEmpty {
                        Button {
                            if model.running { confirmStop = true }
                            else { model.control(function: model.selectedTask?.tool == true ? model.selectedTask?.id : nil) }
                        } label: {
                            Label(model.running ? "停止" : (model.selectedTask?.tool == true ? "运行工具" : "启动调度"),
                                  systemImage: model.running ? "stop.fill" : "play.fill")
                        }.disabled(model.busy || launcher.busy)
                    }
                }
        }
        .searchable(text: $model.search, placement: .toolbar, prompt: "搜索任务与配置项")
        }
        .navigationSplitViewStyle(.balanced)
        .onChange(of: model.search) { term in
            if !term.isEmpty {
                for section in model.catalog?.sections ?? [] where section.tasks.contains(where: matches) {
                    expanded.insert(section.id)
                }
            }
        }
        .task(id: token) { await model.connect(url: url, token: token) }
        .preferredColorScheme(model.appearance == "dark" ? .dark : (model.appearance == "light" ? .light : nil))
        .onChange(of: model.dirty) { launcher.hasUnsavedNativeChanges = $0 }
        .alert("操作未完成", isPresented: Binding(get: { model.error != nil }, set: { if !$0 { model.error = nil } })) {
            Button("好") { model.error = nil }
        } message: { Text(model.error ?? "") }
        .alert("停止当前任务？", isPresented: $confirmStop) {
            Button("取消", role: .cancel) {}
            Button("停止", role: .destructive) { model.control(stop: true) }
        } message: { Text("将停止配置 \(model.profile) 正在执行的自动化任务。") }
        .alert("同步核心更新？", isPresented: $confirmUpdate) {
            Button("取消", role: .cancel) {}
            Button("停止任务并更新") { launcher.start(mode: "update") }
        } message: { Text("所有运行中的任务会停止。仅通过 Git 更新核心，保留一个回退版本，不修改运行环境。") }
        .alert("放弃未保存修改？", isPresented: $confirmDiscard) {
            Button("取消", role: .cancel) {}
            Button("重新载入", role: .destructive) { model.discard() }
        }
        .sheet(isPresented: $creating) { createSheet }
        .alert("删除配置？", isPresented: Binding(get: { deletingProfile != nil }, set: { if !$0 { deletingProfile = nil } })) {
            Button("取消", role: .cancel) { deletingProfile = nil }
            Button("删除", role: .destructive) {
                if let name = deletingProfile { model.deleteConfig(name) }
                deletingProfile = nil
            }
        } message: {
            Text("将永久删除配置「\(deletingProfile ?? "")」的设置，无法撤销。日志和运行环境不受影响。需要备份时请先在配置管理中导出。")
        }
    }

    // 显示分组任务导航
    private var sidebar: some View {
        VStack(spacing: 0) {
            List(selection: $model.page) {
                Section("工作区") {
                    Label("首页", systemImage: "house").tag("home")
                    Label("调度总览", systemImage: "calendar.badge.clock").tag("overview")
                    Label("实时日志", systemImage: "text.alignleft").tag("logs")
                    Label("配置管理", systemImage: "square.stack").tag("manage")
                }
                ForEach(model.catalog?.sections ?? []) { section in
                    let tasks = section.tasks.filter { matches($0) }
                    if !tasks.isEmpty {
                        sidebarSection(section, tasks: tasks)
                    }
                }
                Section("应用") {
                    Label("核心更新", systemImage: "arrow.triangle.2.circlepath").tag("updates")
                    Label("远程访问", systemImage: "network").tag("remote")
                    Label("诊断工具", systemImage: "stethoscope").tag("diagnostics")
                }
            }.listStyle(.sidebar)
            HStack {
                Circle().fill(model.running ? Color.green : Color.secondary).frame(width: 7, height: 7)
                Text(model.currentProfile?.status ?? "等待配置").font(.caption)
                Spacer()
            }.padding(12)
        }
    }

    // 创建仅可折叠的任务分组
    @ViewBuilder private func sidebarSection(_ section: NativeSection, tasks: [NativeTask]) -> some View {
        let isExpanded = Binding(get: { expanded.contains(section.id) },
            set: { if $0 { expanded.insert(section.id) } else { expanded.remove(section.id) } })
        if #available(macOS 14.0, *) {
            Section(isExpanded: isExpanded) {
                sidebarTasks(tasks)
            } header: { Text(section.title) }
        } else {
            Section {
                if isExpanded.wrappedValue { sidebarTasks(tasks) }
            } header: {
                DisclosureGroup(isExpanded: isExpanded) {
                    EmptyView()
                } label: { Text(section.title) }
            }
        }
    }

    // 显示可选任务条目
    private func sidebarTasks(_ tasks: [NativeTask]) -> some View {
        ForEach(tasks) { task in
            Label(task.title, systemImage: task.tool ? "wrench.and.screwdriver" : "slider.horizontal.3")
                .tag("task:" + task.id)
        }
    }

    // 匹配任务与字段搜索词
    private func matches(_ task: NativeTask) -> Bool {
        let term = model.search.trimmingCharacters(in: .whitespaces)
        return term.isEmpty || task.title.localizedCaseInsensitiveContains(term) || task.id.localizedCaseInsensitiveContains(term)
            || task.groups.contains { $0.fields.contains { $0.title.localizedCaseInsensitiveContains(term) || $0.id.localizedCaseInsensitiveContains(term) } }
    }
    // 解析当前页面标题
    private var title: String {
        if let task = model.selectedTask { return task.title }
        return ["home": "指挥中心", "overview": "调度总览", "logs": "实时日志", "manage": "配置管理",
                "updates": "ALAS 核心更新", "remote": "远程访问", "diagnostics": "诊断工具"][model.page] ?? "ALAS"
    }
    // 切换当前功能页面
    @ViewBuilder private var detail: some View {
        if let task = model.selectedTask {
            configPage(task)
        } else {
            switch model.page {
            case "home": home
            case "overview": overview
            case "logs":
                VStack(spacing: 0) {
                    HStack {
                        Text(model.profile.isEmpty ? "尚未选择配置" : "当前配置：\(model.profile)").font(.headline)
                        Spacer()
                        Picker("日志来源", selection: $showCoreLogs) {
                            Text("任务日志").tag(false)
                            Text("核心日志").tag(true)
                        }.pickerStyle(.segmented).frame(width: 200)
                    }.padding(12)
                    NativeLogView(text: showCoreLogs ? launcher.logs : (model.snapshot?.logs ?? ""),
                                  filter: $model.logSearch, follow: $model.followLogs)
                }
            case "manage": management
            case "updates": updates
            case "remote": remote
            case "diagnostics": diagnostics
            default: ProgressView("正在读取核心配置…")
            }
        }
    }

    // 显示配置实例与运行概况
    private var home: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack(spacing: 16) {
                    metric("配置", value: "\(model.snapshot?.profiles.count ?? 0)", icon: "square.stack")
                    metric("运行中", value: "\(model.snapshot?.profiles.filter { $0.state == 1 }.count ?? 0)", icon: "play.circle")
                    metric("当前配置待执行", value: "\(model.snapshot?.schedule.count ?? 0)", icon: "calendar")
                }
                GroupBox("配置实例") {
                    VStack(spacing: 0) {
                        ForEach(model.snapshot?.profiles ?? []) { profile in
                            HStack(spacing: 12) {
                                Image(systemName: "shippingbox").font(.title2).foregroundStyle(.blue)
                                VStack(alignment: .leading) { Text(profile.id).font(.headline); Text(profile.mod.uppercased()).font(.caption).foregroundStyle(.secondary) }
                                Spacer()
                                Text(profile.status).foregroundStyle(profile.state == 1 ? .green : .secondary)
                                Button("打开") { model.selectProfile(profile.id); if !model.dirty { model.page = "overview" } }
                                Button("删除", role: .destructive) { deletingProfile = profile.id }
                                    .disabled(profile.state == 1 || model.busy || model.dirty)
                            }.padding(12)
                            if profile.id != model.snapshot?.profiles.last?.id { Divider() }
                        }
                        if model.snapshot?.profiles.isEmpty != false {
                            Text("尚无配置。新建一个配置，开始设置设备与任务。").foregroundStyle(.secondary).padding(24)
                        }
                    }
                }
                HStack {
                    Button("新建配置", systemImage: "plus") { creating = true }.disabled(model.dirty)
                    Button("导入配置", systemImage: "square.and.arrow.down") { model.importConfig() }
                    Spacer()
                    Link("ALAS 项目", destination: URL(string: "https://github.com/LmeSzinc/AzurLaneAutoScript")!)
                }
            }.padding(28).frame(maxWidth: 1000, alignment: .leading).frame(maxWidth: .infinity)
        }
    }
    // 显示运行统计指标
    private func metric(_ name: String, value: String, icon: String) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                Label(name, systemImage: icon).foregroundStyle(.secondary)
                Text(value).font(.system(size: 32, weight: .semibold, design: .rounded)).monospacedDigit()
            }.frame(maxWidth: .infinity, alignment: .leading).padding(14)
        }
    }
    // 显示运行与待执行任务
    private var overview: some View {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack { Spacer(); Text(model.profile.isEmpty ? "请先新建或选择配置" : (model.currentProfile?.status ?? "")).foregroundStyle(.secondary) }
                    ForEach(["running", "pending", "waiting"], id: \.self) { state in
                        GroupBox(["running": "正在执行", "pending": "等待执行", "waiting": "定时任务"][state]!) {
                            let tasks = model.snapshot?.schedule.filter { $0.state == state } ?? []
                            VStack(alignment: .leading, spacing: 10) {
                                if tasks.isEmpty { Text("暂无任务").foregroundStyle(.secondary).padding(8) }
                                ForEach(tasks) { task in
                                    HStack {
                                        Label(task.title, systemImage: state == "running" ? "play.circle.fill" : "clock")
                                        Spacer(); Text(task.nextRun).font(.callout.monospacedDigit()).foregroundStyle(.secondary)
                                        Button("设置") { model.page = "task:" + task.id }
                                    }.padding(6)
                                }
                            }.frame(maxWidth: .infinity, alignment: .leading).padding(8)
                        }
                    }
                }.padding(24)
            }
    }

    // 显示任务配置表单
    private func configPage(_ task: NativeTask) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                if meaningful(task.help) { Text(cleanHelp(task.help)).foregroundStyle(.secondary).textSelection(.enabled) }
                if task.tool {
                    Label("此工具使用当前配置的设备设置。运行前请保存修改，停止其他任务。", systemImage: "info.circle").foregroundStyle(.secondary)
                }
                ForEach(task.groups) { group in
                    GroupBox(group.title.hasSuffix("._info.name") ? group.id : group.title) {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(group.fields) { field in
                                NativeFieldView(field: field, value: Binding(get: { model.value(field) }, set: { model.edit(field, $0) }))
                                    .padding(.vertical, 13)
                                if field.id != group.fields.last?.id { Divider() }
                            }
                        }.padding(.horizontal, 12)
                    }
                }
            }.padding(26).frame(maxWidth: 1000).frame(maxWidth: .infinity)
        }.id(task.id).disabled(model.busy)
    }
    // 管理配置的增删与导入导出
    private var management: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Spacer()
                Button("导入…") { model.importConfig() }
                Button("新建…") { creating = true }.buttonStyle(.borderedProminent).disabled(model.dirty)
            }
            Text("每个配置独立保存设备、任务与调度设置；支持从模板或已有配置复制。") .foregroundStyle(.secondary)
            Table(model.snapshot?.profiles ?? []) {
                TableColumn("名称", value: \.id)
                TableColumn("核心类型", value: \.mod)
                TableColumn("状态") { Text($0.status) }
                TableColumn("操作") { profile in
                    HStack {
                        Button("编辑") { model.selectProfile(profile.id) }
                        Button("导出…") { model.exportConfig(profile.id) }
                        Button("删除", role: .destructive) { deletingProfile = profile.id }
                            .disabled(profile.state == 1 || model.dirty)
                    }
                }
            }
        }.padding(24).disabled(model.busy)
    }
    // 检查更新与回退核心
    private var updates: some View {
        Form {
            Section("启动器版本") {
                LabeledContent("当前版本", value: "\(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "") (\(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""))")
                Text("启动器通过完整签名 App 更新。退出后在 Finder 中替换旧 App，外部数据目录与环境保持不变；此处的 Git 更新仅针对 ALAS 核心。")
                    .foregroundStyle(.secondary)
            }
            Section("版本管理") {
                LabeledContent("当前提交", value: model.snapshot?.revision ?? "读取中").textSelection(.enabled)
                LabeledContent("上游提交", value: model.upstream.isEmpty ? "尚未检查" : model.upstream).textSelection(.enabled)
                Text("单 Git 工作树更新，仅保留一个回退版本。环境和用户配置不随核心回退。")
                    .foregroundStyle(.secondary)
                HStack {
                    Button("检查更新") { model.checkUpdate() }
                    Button("同步上游…") { confirmUpdate = true }.disabled(model.dirty)
                    Button("回退上一版本") { launcher.start(mode: "rollback") }.disabled(!launcher.canRollback || model.dirty)
                }
            }
        }.formStyle(.grouped).disabled(model.busy || launcher.busy)
    }
    // 展示远程访问状态
    private var remote: some View {
        Form {
            Section("远程访问状态") {
                LabeledContent("配置状态", value: model.snapshot?.remoteEnabled == true ? "已启用" : "未启用")
                LabeledContent("连接状态", value: [0: "未连接", 1: "连接中", 2: "运行中", 3: "SSH 不可用"][model.snapshot?.remoteState ?? 0] ?? "未知")
                if let address = model.snapshot?.remoteAddress, !address.isEmpty {
                    LabeledContent("访问地址", value: address).textSelection(.enabled)
                }
                Text("沿用核心的远程访问能力与 deploy.yaml 设置。原生控制接口仅接受本机认证连接，不对远程开放。")
                    .foregroundStyle(.secondary)
                Button("打开部署配置") { launcher.openDeployConfig() }
            }
        }.formStyle(.grouped)
    }
    // 展示诊断与界面设置
    private var diagnostics: some View {
        Form {
            Section("诊断与文件") {
                Button("测试错误反馈") { model.diagnostic() }
                Button("重新启动核心服务") { launcher.start() }.disabled(model.dirty)
                Button("打开配置、日志与截图目录") { launcher.openData() }
                Text("错误测试不会结束核心进程。重新启动将停止当前自动化任务。") .foregroundStyle(.secondary)
            }
            Section("配置字段语言") {
                Picker("语言", selection: Binding(get: { model.language }, set: { model.preferences(language: $0) })) {
                    Text("简体中文").tag("zh-CN"); Text("繁體中文").tag("zh-TW")
                    Text("English").tag("en-US"); Text("日本語").tag("ja-JP")
                }
                Picker("外观", selection: Binding(get: { model.appearance }, set: { model.preferences(appearance: $0) })) {
                    Text("跟随系统").tag("system"); Text("浅色").tag("light"); Text("深色").tag("dark")
                }
            }
        }.formStyle(.grouped).disabled(model.busy)
    }
    // 填写新配置名称与来源
    private var createSheet: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("新建配置").font(.title2.bold())
            TextField("配置名称", text: $newName).textFieldStyle(.roundedBorder)
            Picker("复制来源", selection: $origin) {
                ForEach((model.snapshot?.templates ?? ["template-alas"]) + (model.snapshot?.profiles.map(\.id) ?? []), id: \.self) { Text($0).tag($0) }
            }
            Text("不会启动自动化任务。创建后可先配置模拟器与游戏设置。") .font(.caption).foregroundStyle(.secondary)
            HStack { Spacer(); Button("取消") { creating = false }; Button("创建") {
                model.create(name: newName.trimmingCharacters(in: .whitespaces), origin: origin); creating = false
            }.buttonStyle(.borderedProminent).disabled(newName.trimmingCharacters(in: .whitespaces).isEmpty || model.busy) }
        }.padding(24).frame(width: 440)
    }
}

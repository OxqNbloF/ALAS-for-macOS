import AppKit
import Combine
import Darwin
import Foundation

// 管理部署、更新、回退和核心进程。
@MainActor
final class LauncherModel: ObservableObject {
    @Published var status = "尚未启动"
    @Published var logs = ""
    @Published var busy = false
    @Published var failure: String?
    @Published var notice: String?
    @Published var url: URL?
    @Published var apiToken = ""
    var hasUnsavedNativeChanges = false
    @Published var updateRequested = false
    @Published var canRollback = false
    @Published var isFirstDeployment = false
    @Published var deployment = DeploymentProgress()

    let root: URL = {
        #if DEBUG
        if let path = ProcessInfo.processInfo.environment["ALAS_RUNTIME_ROOT"], path.hasPrefix("/private/tmp/") {
            return URL(fileURLWithPath: path, isDirectory: true)
        }
        #endif
        return LauncherStorage.dataRoot
    }()
    private var process: Process?
    private var pipe: Pipe?
    private var operation: Task<Void, Never>?
    private var monitor: Task<Void, Never>?
    private var didStart = false
    private var closing = false
    private var lockFD: Int32 = -1
    @Published var failureReport: URL?
    private var errorLog = LauncherErrorLog()

    private struct Endpoint: Decodable { let url: URL; let pid: Int32; let token: String }

    // 防止重复启动
    func startIfNeeded() {
        guard !didStart else { return }
        didStart = true
        start()
    }

    // 部署环境并启动核心
    func start(mode: String = "prepare") {
        guard !busy, !closing else { return }
        guard !hasUnsavedNativeChanges else {
            notice = "有未保存的配置修改，请先保存或放弃修改后再更新、回退或重启。"
            return
        }
        isFirstDeployment = false
        deployment = DeploymentProgress()
        busy = true
        failure = nil
        failureReport = nil
        notice = nil
        operation = Task {
            do {
                isFirstDeployment = !FileManager.default.fileExists(atPath: root.appendingPathComponent("active.json").path)
                try acquireLock()
                await stopService()
                if isFirstDeployment { logs = "" }
                let previousActive = try? Data(contentsOf: root.appendingPathComponent("active.json"))
                status = previousActive != nil ? "检查核心更新 · 复用环境" : "首次安装独立环境"
                do {
                    try await runInstaller(mode)
                } catch {
                    if previousActive != nil {
                        notice = "操作未完成，继续使用原有版本。详情见运行日志。"
                        append("ERROR: 操作未完成，重新启动原有版本：\(error.localizedDescription)\n")
                    } else { throw error }
                }
                try Task.checkCancellation()
                canRollback = FileManager.default.fileExists(atPath: root.appendingPathComponent("previous.json").path)
                do {
                    try await launchService()
                } catch {
                    guard mode != "rollback", previousActive != nil, canRollback,
                          previousActive != (try? Data(contentsOf: root.appendingPathComponent("active.json"))) else { throw error }
                    append("ERROR: 新版本服务启动失败，自动回退：\(error.localizedDescription)\n")
                    await stopService()
                    try Task.checkCancellation()
                    try await runInstaller("rollback")
                    try await launchService()
                    status = "运行中 · 更新失败，已回退"
                    notice = "新版本未能正常启动，已自动回退到上一版本。"
                }
            } catch is CancellationError {
                status = "已停止"
            } catch {
                failure = error.localizedDescription
                status = "启动失败"
                append("ERROR: \(error.localizedDescription)\n")
                await stopService()
                if isFirstDeployment && !closing && !Task.isCancelled {
                    do {
                        let reports = root.appendingPathComponent("reports", isDirectory: true)
                        try FileManager.default.createDirectory(at: reports, withIntermediateDirectories: true)
                        let report = try DeploymentFailureReport.save(error: error.localizedDescription,
                            stage: deployment.title, logs: logs, directory: reports)
                        failureReport = report
                        notice = "部署失败日志已保存在应用数据目录，可导出到文稿。"
                    } catch {
                        notice = "无法保存失败日志：\(error.localizedDescription)"
                    }
                }
            }
            busy = false
        }
    }

    // 锁定环境防止多开
    private func acquireLock() throws {
        guard lockFD < 0 else { return }
        try LauncherStorage.prepare(root: root)
        let fd = Darwin.open(root.appendingPathComponent("launcher.lock").path, O_CREAT | O_RDWR, 0o600)
        guard fd >= 0 else { throw error("无法创建应用运行锁") }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            Darwin.close(fd)
            throw error("另一份 ALAS 启动器已在运行，请先关闭它。")
        }
        _ = fcntl(fd, F_SETFD, FD_CLOEXEC)
        lockFD = fd
    }

    // 用私有环境启动脚本，收集标准输出和错误。
    private func makeProcess(_ mode: String) throws -> Process {
        deployment.resetStream()
        guard let resources = Bundle.main.resourceURL else { throw error("找不到应用资源") }
        let runtime = resources.appendingPathComponent("Runtime")
        guard FileManager.default.fileExists(atPath: runtime.appendingPathComponent("bootstrap.sh").path),
              FileManager.default.fileExists(atPath: runtime.appendingPathComponent("deployment.py").path) else {
            throw error("应用资源不完整：缺少 Runtime，请重新构建。")
        }
        let child = Process()
        child.executableURL = URL(fileURLWithPath: "/bin/bash")
        child.arguments = [runtime.appendingPathComponent("bootstrap.sh").path, mode, root.path]
        child.currentDirectoryURL = root
        var env = ["PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
                   "HOME": root.appendingPathComponent("home").path,
                   "ALAS_LAUNCHER_PID": String(ProcessInfo.processInfo.processIdentifier)]
        for key in ["https_proxy", "http_proxy", "all_proxy", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"] {
            env[key] = ProcessInfo.processInfo.environment[key]
        }
        child.environment = env
        let output = Pipe()
        child.standardOutput = output
        child.standardError = output
        child.standardInput = FileHandle.nullDevice
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            guard let owner = self else { return }
            let data = handle.availableData
            guard !data.isEmpty else { return }
            Task { @MainActor in
                let display = owner.isFirstDeployment ? owner.deployment.consume(data) : nil
                owner.append(String(decoding: data, as: UTF8.self), display: display)
            }
        }
        pipe = output
        process = child
        try child.run()
        _ = setpgid(child.processIdentifier, child.processIdentifier)
        return child
    }

    // 执行部署与更新脚本
    private func runInstaller(_ mode: String) async throws {
        let child = try makeProcess(mode)
        while child.isRunning {
            try await Task.sleep(for: .milliseconds(200))
        }
        pipe?.fileHandleForReading.readabilityHandler = nil
        process = nil
        guard child.terminationStatus == 0 else {
            throw error("\(mode == "update" ? "更新" : "环境准备")失败（退出码 \(child.terminationStatus)）。请查看详细日志；可直接重试，原有版本不会被覆盖。")
        }
    }

    // 启动并连接核心服务
    private func launchService() async throws {
        status = "正在启动本地核心服务"
        if isFirstDeployment { deployment.advance(9, title: "启动本地核心服务") }
        let endpoint = root.appendingPathComponent("endpoint.json")
        try? FileManager.default.removeItem(at: endpoint)
        let child = try makeProcess("serve")
        let deadline = Date().addingTimeInterval(120)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 2
        configuration.connectionProxyDictionary = [:]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        while Date() < deadline {
            try Task.checkCancellation()
            guard child.isRunning else { throw error("核心服务提前退出，请查看运行日志。") }
            if let data = try? Data(contentsOf: endpoint),
               let ready = try? JSONDecoder().decode(Endpoint.self, from: data),
               ready.url.scheme == "http", ready.url.host == "127.0.0.1",
               let (_, response) = try? await session.data(from: ready.url),
               let response = response as? HTTPURLResponse, response.statusCode == 200 {
                url = ready.url
                apiToken = ready.token
                status = "运行中 · 本地隔离环境"
                if isFirstDeployment { deployment.finish() }
                beginMonitoring(child)
                return
            }
            try await Task.sleep(for: .milliseconds(300))
        }
        throw error("核心服务在 120 秒内未就绪，请检查日志后重试。")
    }

    // 监控服务退出与更新请求
    private func beginMonitoring(_ child: Process) {
        monitor = Task {
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(1)) } catch { return }
                if !child.isRunning {
                    url = nil
                    status = "服务已停止"
                    failure = "核心服务意外退出（\(child.terminationStatus)），请查看日志后重启。"
                    append("ERROR: \(failure ?? "")\n")
                    return
                }
                let request = root.appendingPathComponent("update-request")
                if FileManager.default.fileExists(atPath: request.path) {
                    try? FileManager.default.removeItem(at: request)
                    updateRequested = true
                }
            }
        }
    }

    // 停止服务及残留子进程
    private func stopService() async {
        monitor?.cancel()
        monitor = nil
        url = nil
        apiToken = ""
        guard let child = process else { return }
        let pid = child.processIdentifier
        if child.isRunning {
            if getpgid(pid) == pid { kill(-pid, SIGTERM) } else { child.terminate() }
            let deadline = Date().addingTimeInterval(8)
            while child.isRunning, Date() < deadline {
                await Task.detached { try? await Task.sleep(for: .milliseconds(100)) }.value
            }
            if child.isRunning { kill(pid, SIGKILL) }
        }
        kill(-pid, SIGKILL)
        pipe?.fileHandleForReading.readabilityHandler = nil
        pipe = nil
        process = nil
    }

    // 取消任务并释放运行锁
    func shutdown() async {
        closing = true
        operation?.cancel()
        await operation?.value
        await stopService()
        if lockFD >= 0 { flock(lockFD, LOCK_UN); Darwin.close(lockFD); lockFD = -1 }
    }

    // 打开独立数据目录
    func openData() { NSWorkspace.shared.open(root) }

    // 授权后导出失败报告
    func exportFailureReport() {
        guard let report = failureReport else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = report.lastPathComponent
        guard panel.runModal() == .OK, let destination = panel.url else { return }
        do { try Data(contentsOf: report).write(to: destination, options: .atomic) }
        catch { notice = "导出失败：\(error.localizedDescription)" }
    }

    // 打开外部核心部署配置
    func openDeployConfig() {
        NSWorkspace.shared.open(root.appendingPathComponent("core/config/deploy.yaml"))
    }

    // 实时显示并仅落盘错误
    private func append(_ text: String, display: String? = nil) {
        logs += display ?? text
        if logs.count > 100_000 { logs = String(logs.suffix(80_000)) }
        if lockFD >= 0 {
            let errors = errorLog.consume(text)
            do { try LauncherErrorLog.save(errors, root: root) }
            catch { notice = "错误日志保存失败：\(error.localizedDescription)" }
        }
    }

    // 构造启动错误
    private func error(_ message: String) -> NSError {
        NSError(domain: "ALASLauncher", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}

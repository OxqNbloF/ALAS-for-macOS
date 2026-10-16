import Combine
import Foundation
import IOKit.ps

// 依据电源状态决定是否保持唤醒；与 IO 解耦，便于单元测试。
struct AwakePolicy {
    var threshold = 20
    var hysteresis = 5
    private(set) var suspended = false

    // 返回 true 表示允许保持唤醒。电池跌到阈值即暂停，回升到「阈值 + 回差」后恢复。
    mutating func allowsAwake(batteryPercent: Int?, onBattery: Bool) -> Bool {
        guard onBattery, let level = batteryPercent else {
            if !onBattery { suspended = false }
            return true
        }
        if level <= threshold {
            suspended = true
        } else if suspended, level >= threshold + hysteresis {
            suspended = false
        }
        return !suspended
    }
}

// 任务运行期间保持 Mac 唤醒、按电量阈值停止；独立轮询任务状态，主界面关闭后仍然有效。
@MainActor
final class AwakeController: ObservableObject {
    static let shared = AwakeController()

    @Published private(set) var holding = false
    @Published private(set) var batteryPercent: Int?
    @Published private(set) var onBattery = false
    @Published private(set) var clamshellDisabled = false
    @Published private(set) var status = "任务未运行"
    private(set) var isTaskRunning = false

    private var enabled = true
    private var policy = AwakePolicy()
    private var activity: NSObjectProtocol?
    private var monitor: Task<Void, Never>?
    private var pollTask: Task<Void, Never>?
    private var session: URLSession?
    private var endpoint: URL?
    private var token = ""
    private var pollFailures = 0

    private init() {}

    // 应用设置；开启或调整阈值后立即重新评估。
    func configure(enabled: Bool, threshold: Int) {
        self.enabled = enabled
        policy.threshold = threshold
        evaluate()
    }

    // 任务运行状态变化。停止时释放闲置休眠断言；合盖设置保留到退出或手动关闭。
    func taskRunningChanged(_ running: Bool) {
        guard running != isTaskRunning else { return }
        isTaskRunning = running
        if running { startMonitoring() } else { stopMonitoring() }
        evaluate()
    }

    // 连接本机核心后独立轮询任务状态；即使主界面关闭，任务结束也能及时释放断言。
    func attach(url: URL, token: String) {
        endpoint = url
        self.token = token
        if session == nil {
            let configuration = URLSessionConfiguration.ephemeral
            configuration.connectionProxyDictionary = [:]
            configuration.timeoutIntervalForRequest = 5
            configuration.urlCache = nil
            session = URLSession(configuration: configuration)
        }
        guard pollTask == nil else { return }
        pollFailures = 0
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refreshTaskState()
                try? await Task.sleep(for: .seconds(5))
            }
        }
    }

    // 停止轮询并断开本机接口。
    func detach() {
        pollTask?.cancel(); pollTask = nil
        session?.invalidateAndCancel(); session = nil
        endpoint = nil; token = ""; pollFailures = 0
    }

    // 读取系统当前的合盖休眠开关，避免界面与真实状态不一致。
    func refreshSystemSleepState() {
        clamshellDisabled = Self.systemSleepDisabled() ?? clamshellDisabled
    }

    // 由用户显式开关合盖休眠；需要管理员授权。
    func setClamshell(_ disabled: Bool) {
        guard disabled != clamshellDisabled else { return }
        status = disabled ? "正在请求管理员授权…" : "正在恢复合盖休眠…"
        Task {
            let ok = await Self.applySystemSleep(disabled: disabled)
            clamshellDisabled = ok ? disabled : clamshellDisabled
            status = ok ? (disabled ? "合盖后保持运行已开启" : "已恢复合盖休眠")
                        : "合盖设置未生效（需要管理员授权）"
            evaluate()
        }
    }

    // 释放闲置休眠断言。合盖设置是持久项，退出应用时保持不变。
    func stop() async {
        stopMonitoring()
        detach()
        isTaskRunning = false
        releaseActivity()
        status = "已停止"
    }

    private func startMonitoring() {
        guard monitor == nil else { return }
        monitor = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                guard !Task.isCancelled else { return }
                self?.evaluate()
            }
        }
    }

    private func stopMonitoring() {
        monitor?.cancel()
        monitor = nil
    }

    private func evaluate() {
        refreshBattery()
        guard enabled, isTaskRunning else {
            releaseActivity()
            status = isTaskRunning ? "已关闭" : "任务未运行"
            return
        }
        if policy.allowsAwake(batteryPercent: batteryPercent, onBattery: onBattery) {
            acquireActivity()
            status = onBattery ? "保持唤醒 · 电池 \(batteryPercent ?? 0)%" : "保持唤醒 · 接通电源"
        } else {
            releaseActivity()
            status = "电池 \(batteryPercent ?? 0)% 低于 \(policy.threshold)%，已停止保持唤醒"
        }
    }

    // 阻止系统闲置休眠；屏幕仍可息屏以省电。
    private func acquireActivity() {
        guard activity == nil else { holding = true; return }
        activity = ProcessInfo.processInfo.beginActivity(
            options: [.userInitiated, .idleSystemSleepDisabled],
            reason: "ALAS 自动化任务运行中")
        holding = true
    }

    private func releaseActivity() {
        if let activity { ProcessInfo.processInfo.endActivity(activity) }
        activity = nil
        holding = false
    }

    private func refreshBattery() {
        guard let blob = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let sources = IOPSCopyPowerSourcesList(blob)?.takeRetainedValue() as? [CFTypeRef] else { return }
        for source in sources {
            guard let description = IOPSGetPowerSourceDescription(blob, source)?.takeUnretainedValue() as? [String: Any],
                  description[kIOPSTypeKey] as? String == kIOPSInternalBatteryType else { continue }
            batteryPercent = description[kIOPSCurrentCapacityKey] as? Int
            onBattery = (description[kIOPSPowerSourceStateKey] as? String) == kIOPSBatteryPowerValue
            return
        }
        batteryPercent = nil
        onBattery = false
    }

    private func refreshTaskState() async {
        guard let endpoint, let session, !token.isEmpty else { return }
        var request = URLRequest(url: endpoint.appendingPathComponent("native/snapshot"))
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        guard let (data, response) = try? await session.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let snapshot = try? JSONDecoder().decode(NativeSnapshot.self, from: data) else {
            // 连续失败视为核心已退出，释放断言，避免后台残留「保持唤醒」。
            pollFailures += 1
            if pollFailures >= 3 { taskRunningChanged(false) }
            return
        }
        pollFailures = 0
        taskRunningChanged(snapshot.profiles.contains { $0.state == 1 })
    }

    // 通过 osascript 请求管理员权限执行 pmset；授权对话框由系统弹出。
    private nonisolated static func applySystemSleep(disabled: Bool) async -> Bool {
        let command = disabled ? "/usr/bin/pmset -a disablesleep 1" : "/usr/bin/pmset -a disablesleep 0"
        return await withCheckedContinuation { continuation in
            DispatchQueue.global().async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
                process.arguments = ["-e", "do shell script \"\(command)\" with administrator privileges"]
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice
                do { try process.run() } catch {
                    continuation.resume(returning: false)
                    return
                }
                process.waitUntilExit()
                continuation.resume(returning: process.terminationStatus == 0)
            }
        }
    }

    private nonisolated static func systemSleepDisabled() -> Bool? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pmset")
        process.arguments = ["-g"]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() } catch { return nil }
        process.waitUntilExit()
        let output = String(decoding: pipe.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
        return output.split(separator: "\n").contains {
            let line = $0.trimmingCharacters(in: .whitespaces)
            return line.hasPrefix("SleepDisabled") && line.contains("1")
        }
    }
}

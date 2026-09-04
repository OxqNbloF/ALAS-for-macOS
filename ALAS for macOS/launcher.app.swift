import SwiftUI
import AppKit

// 应用入口，创建原生窗口。
@main struct MyApp: App {
    @NSApplicationDelegateAdaptor(LauncherDelegate.self) private var delegate
    @StateObject private var launcher = LauncherModel()
    var body: some Scene {
        Window("ALAS for macOS", id: "main") {
            ContentView().environmentObject(launcher)
                .onAppear { delegate.launcher = launcher }
        }
        .defaultSize(width: 1200, height: 820)
        .windowToolbarStyle(.unified)
    }
}

@MainActor
// 退出前检查未保存的修改并停止核心。
final class LauncherDelegate: NSObject, NSApplicationDelegate {
    var launcher: LauncherModel?
    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { false }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if launcher?.hasUnsavedNativeChanges == true {
            let alert = NSAlert()
            alert.messageText = "退出并放弃未保存的配置修改？"
            alert.addButton(withTitle: "取消"); alert.addButton(withTitle: "放弃并退出")
            guard alert.runModal() == .alertSecondButtonReturn else { return .terminateCancel }
        }
        Task {
            await launcher?.shutdown()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}

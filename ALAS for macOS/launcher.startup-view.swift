import SwiftUI

// 启动页：部署进度、日志和失败后的重试入口。
struct ContentView: View {
    @EnvironmentObject private var launcher: LauncherModel
    var body: some View {
        VStack(spacing: 0) {
            if let notice = launcher.notice {
                HStack {
                    Label(notice, systemImage: "exclamationmark.triangle")
                    Spacer()
                    if launcher.failureReport != nil {
                        Button("导出日志…") { launcher.exportFailureReport() }
                    }
                    Button { launcher.notice = nil } label: { Image(systemName: "xmark") }
                }.font(.callout).padding(10).background(Color.orange.opacity(0.12))
            }
            if let url = launcher.url {
                NativeMainView(url: url, token: launcher.apiToken)
            } else {
                VStack(spacing: 20) {
                    Image(systemName: "sailboat.circle.fill")
                        .font(.system(size: 76)).foregroundStyle(.blue.gradient)
                    Text(launcher.failure == nil ? "准备启航" : "启动需要处理").font(.largeTitle.bold())
                    Text(launcher.failure ?? "首次启动将下载 ALAS 核心，并配置专属运行环境。\n运行环境与数据将自动保存在 Application Support/AzurLaneAutoScript。")
                        .multilineTextAlignment(.center).foregroundStyle(.secondary).frame(maxWidth: 560)
                    if launcher.isFirstDeployment {
                        VStack(alignment: .leading, spacing: 10) {
                            HStack {
                                Text(launcher.deployment.title).font(.headline)
                                Spacer()
                                Text(launcher.deployment.label).monospacedDigit().foregroundStyle(.secondary)
                            }
                            Group {
                                if launcher.busy && !launcher.deployment.completed {
                                    ProgressView()
                                } else {
                                    ProgressView(value: launcher.deployment.fraction)
                                }
                            }
                                .progressViewStyle(.linear)
                                .tint(launcher.failure == nil ? .blue : .orange)
                                .accessibilityLabel("首次部署进度")
                                .accessibilityValue(launcher.deployment.label)
                            Text(launcher.failure == nil ? launcher.deployment.detail : "部署已暂停，请处理错误后重试。")
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .padding(18)
                        .frame(maxWidth: 520)
                        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
                    }
                    if launcher.busy && !launcher.isFirstDeployment {
                        ProgressView().controlSize(.small)
                    } else if !launcher.busy {
                        Button("重试启动") { launcher.start() }.buttonStyle(.borderedProminent)
                    }
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: 900, minHeight: 640)
        .modifier(SystemToolbarAppearance())
        .alert("核心请求更新", isPresented: $launcher.updateRequested) {
            Button("取消", role: .cancel) {}
            Button("停止服务并更新") { launcher.start(mode: "update") }
        } message: { Text("更新会停止当前自动化任务，仅同步 ALAS 核心并检查兼容性，不修改已安装的运行环境。") }
        .task { launcher.startIfNeeded() }
    }
}

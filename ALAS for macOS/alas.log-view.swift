import SwiftUI
import AppKit

// 显示当前配置的日志，支持筛选和复制。
struct NativeLogView: View {
    let text: String
    @Binding var filter: String
    @Binding var follow: Bool
    private var visible: String {
        filter.isEmpty ? text : text.components(separatedBy: .newlines).filter { $0.localizedCaseInsensitiveContains(filter) }.joined(separator: "\n")
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                TextField("筛选日志", text: $filter).textFieldStyle(.roundedBorder).frame(maxWidth: 250)
                Spacer(); Toggle("跟随滚动", isOn: $follow).toggleStyle(.checkbox)
                Button("复制") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(visible, forType: .string) }
            }.padding(12)
            Divider()
            ScrollViewReader { proxy in
                ScrollView([.vertical, .horizontal]) {
                    VStack(alignment: .leading) {
                        Text(visible.isEmpty ? "暂无日志，任务启动后会在此显示。" : visible)
                            .font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                        Color.clear.frame(height: 1).id("bottom")
                    }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                }.background(Color(nsColor: .textBackgroundColor))
                    .onChange(of: text) { _ in if follow { proxy.scrollTo("bottom", anchor: .bottom) } }
            }
        }
    }
}

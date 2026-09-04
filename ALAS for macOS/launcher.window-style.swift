import AppKit
import SwiftUI

// 配置系统窗口样式，不添加自绘窗口按钮。
struct PersistentSidebarAppearance: ViewModifier {
    @ViewBuilder func body(content: Content) -> some View {
        if #available(macOS 14.0, *) {
            content
                .toolbar(removing: .sidebarToggle)
                .background(SidebarResizeConfiguration().frame(width: 0, height: 0))
        } else {
            content.background(SidebarResizeConfiguration().frame(width: 0, height: 0))
        }
    }
}

// 允许调整侧栏宽度，禁止折叠。
private struct SidebarResizeConfiguration: NSViewRepresentable {
    func makeNSView(context: Context) -> ConfigurationView { ConfigurationView() }
    func updateNSView(_ view: ConfigurationView, context: Context) { view.needsLayout = true }

    final class ConfigurationView: NSView {
        override func layout() {
            super.layout()
            var ancestor = superview
            while let view = ancestor {
                if let split = view as? NSSplitView,
                   let controller = split.delegate as? NSSplitViewController,
                   let sidebar = controller.splitViewItems.first,
                   sidebar.behavior == .sidebar {
                    sidebar.canCollapse = false
                    sidebar.canCollapseFromWindowResize = false
                    sidebar.titlebarSeparatorStyle = .none
                    break
                }
                ancestor = view.superview
            }
        }
    }
}

// 应用系统背景和边缘效果。
struct SystemToolbarAppearance: ViewModifier {
    @ViewBuilder func body(content: Content) -> some View {
        if #available(macOS 26.0, *) {
            content
                .toolbarBackgroundVisibility(.visible, for: .windowToolbar)
                .scrollEdgeEffectStyle(.soft, for: .top)
                .scrollEdgeEffectHidden(false, for: .top)
                .background(WindowToolbarConfiguration().frame(width: 0, height: 0))
        } else if #available(macOS 15.0, *) {
            content
                .toolbarBackgroundVisibility(.visible, for: .windowToolbar)
                .background(WindowToolbarConfiguration().frame(width: 0, height: 0))
        } else {
            content
                .toolbarBackground(.visible, for: .windowToolbar)
                .background(WindowToolbarConfiguration().frame(width: 0, height: 0))
        }
    }
}

// 隐藏标题栏分割线。
private struct WindowToolbarConfiguration: NSViewRepresentable {
    func makeNSView(context: Context) -> ConfigurationView { ConfigurationView() }
    func updateNSView(_ view: ConfigurationView, context: Context) { view.configureWindow() }

    final class ConfigurationView: NSView {
        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            configureWindow()
        }

        func configureWindow() {
            window?.titlebarSeparatorStyle = .none
            window?.titlebarAppearsTransparent = false
        }
    }
}

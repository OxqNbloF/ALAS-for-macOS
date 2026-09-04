import SwiftUI
import AppKit

// 按字段类型生成编辑控件，显示说明和当前值。
struct NativeFieldView: View {
    let field: NativeField
    @Binding var value: ConfigValue
    @State private var reveal = false
    @State private var confirmClear = false
    private var text: Binding<String> { Binding(get: { value.text }, set: { value = .string($0) }) }
    private var title: String { field.title.hasSuffix(".name") ? String(field.id.split(separator: ".").last ?? "") : field.title }
    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(alignment: .top) {
                Text(title).font(.headline)
                if field.readOnly { Image(systemName: "lock").foregroundStyle(.secondary) }
                Spacer()
                if !field.readOnly { Button("默认值") { value = field.defaultValue }.buttonStyle(.link).font(.caption) }
            }
            if meaningful(field.help) { Text(cleanHelp(field.help)).font(.callout).foregroundStyle(.secondary).textSelection(.enabled) }
            control.disabled(field.readOnly)
            if field.kind == "storage", value != .object([:]) {
                Button("清空存储记录…", role: .destructive) { confirmClear = true }
                    .alert("清空此任务的存储记录？", isPresented: $confirmClear) {
                        Button("取消", role: .cancel) {}
                        Button("清空", role: .destructive) { value = .object([:]) }
                    } message: { Text("清空后仍需点击保存配置才会生效。") }
            }
        }.accessibilityElement(children: .contain).accessibilityLabel(title)
    }
    // 按字段类型选择原生控件
    @ViewBuilder private var control: some View {
        if field.readOnly {
            Text(value.text.isEmpty ? "—" : value.text).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        } else if field.kind == "checkbox" {
            Toggle("启用", isOn: Binding(get: { value == .bool(true) }, set: { value = .bool($0) })).toggleStyle(.switch)
        } else if field.kind == "select" {
            Picker(title, selection: $value) {
                if !field.options.contains(where: { $0.value == value }) { Text(value.text).tag(value) }
                ForEach(field.options, id: \.self) { option in
                    Text(option.title.contains(".\(option.value.text)") ? option.value.text : option.title).tag(option.value)
                }
            }.labelsHidden().frame(maxWidth: 560, alignment: .leading)
        } else if field.kind == "textarea" {
            TextEditor(text: text).font(.system(.body, design: .monospaced)).frame(minHeight: 90)
                .padding(5).overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.25)))
        } else if field.kind == "datetime" {
            HStack {
                TextField("yyyy-MM-dd HH:mm:ss", text: text).textFieldStyle(.roundedBorder).frame(maxWidth: 230)
                // 下次运行时间使用文本输入，保留核心时间格式。
                if field.id.split(separator: ".").last != "NextRun" {
                    DatePicker("选择时间", selection: Binding(get: { Self.dateFormatter.date(from: value.text) ?? Date() },
                        set: { value = .string(Self.dateFormatter.string(from: $0)) }), displayedComponents: [.date, .hourAndMinute]).labelsHidden()
                }
            }
        } else if field.id.localizedCaseInsensitiveContains("password") || field.id.localizedCaseInsensitiveContains("token") {
            HStack {
                if reveal { TextField(title, text: text).textFieldStyle(.roundedBorder) }
                else { SecureField(title, text: text).textFieldStyle(.roundedBorder) }
                Button { reveal.toggle() } label: { Image(systemName: reveal ? "eye.slash" : "eye") }.help("显示或隐藏")
            }
        } else {
            TextField(title, text: text).textFieldStyle(.roundedBorder)
        }
    }
    private static let dateFormatter: DateFormatter = {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd HH:mm:ss"; return f
    }()
}

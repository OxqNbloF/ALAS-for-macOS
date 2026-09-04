import Foundation

// 判断帮助文本是否有可显示的内容。
func meaningful(_ text: String) -> Bool { !text.isEmpty && !text.hasSuffix(".help") }
// 移除帮助文本中的格式标记。
func cleanHelp(_ text: String) -> String {
    text.replacingOccurrences(of: "<br>", with: "\n").replacingOccurrences(of: "<br/>", with: "\n")
        .replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
}

// 配置字段、任务目录和运行状态的数据模型。
import AppKit
import Combine
import Foundation
import UniformTypeIdentifiers

// 编解码 JSON 字段值，并转换为可编辑文本。
enum ConfigValue: Codable, Hashable {
    case null, bool(Bool), number(Double), string(String), array([ConfigValue]), object([String: ConfigValue])
    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Double.self) { self = .number(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([ConfigValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: ConfigValue].self)) }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let v): try c.encode(v)
        case .number(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        }
    }
    var text: String {
        switch self {
        case .null: return ""
        case .bool(let v): return v ? "true" : "false"
        case .number(let v): return v.rounded() == v ? String(format: "%.0f", v) : String(v)
        case .string(let v): return v
        default:
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            return (try? String(data: encoder.encode(self), encoding: .utf8)) ?? ""
        }
    }
    var any: Any { (try? JSONSerialization.jsonObject(with: JSONEncoder().encode(self), options: [.fragmentsAllowed])) ?? NSNull() }
}

// 字段选项。
struct NativeOption: Decodable, Hashable { let value: ConfigValue; let title: String }
// 字段类型、默认值和编辑限制。
struct NativeField: Decodable, Identifiable {
    let id, title, help, kind: String
    var value: ConfigValue
    let defaultValue: ConfigValue
    let readOnly: Bool
    let options: [NativeOption]
}
// 同组配置字段。
struct NativeGroup: Decodable, Identifiable { let id, title: String; var fields: [NativeField] }
// 任务及其配置分组。
struct NativeTask: Decodable, Identifiable {
    let id, title, help: String
    let tool: Bool
    var groups: [NativeGroup]
}
// 侧栏任务分组。
struct NativeSection: Decodable, Identifiable { let id, title: String; var tasks: [NativeTask] }
// 配置表单结构。
struct NativeCatalog: Decodable { let name, mod: String; var sections: [NativeSection] }
// 配置名称和运行状态。
struct NativeProfile: Decodable, Identifiable {
    let id, mod: String
    let state: Int
    var status: String { [1: "运行中", 2: "已停止", 3: "需要检查", 4: "更新中"][state] ?? "未知" }
}
// 任务调度时间。
struct NativeScheduledTask: Decodable, Identifiable { let id, title, nextRun, state: String }
// 核心状态快照。
struct NativeSnapshot: Decodable {
    let profiles: [NativeProfile]
    let templates: [String]
    let schedule: [NativeScheduledTask]
    let logs, revision, remoteAddress: String
    let remoteState: Int
    let remoteEnabled: Bool
}

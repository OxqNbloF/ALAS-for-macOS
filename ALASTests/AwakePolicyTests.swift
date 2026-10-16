import Testing
@testable import ALAS_for_macOS

// 电量阈值策略：低于阈值暂停，回升到阈值加回差后恢复。
struct AwakePolicyTests {
    @Test func suspendsBelowThresholdAndResumesWithHysteresis() {
        var policy = AwakePolicy()
        policy.threshold = 20
        policy.hysteresis = 5
        precondition(policy.allowsAwake(batteryPercent: 50, onBattery: true))
        precondition(!policy.allowsAwake(batteryPercent: 20, onBattery: true))
        precondition(!policy.allowsAwake(batteryPercent: 22, onBattery: true))
        precondition(policy.allowsAwake(batteryPercent: 25, onBattery: true))
        precondition(policy.allowsAwake(batteryPercent: nil, onBattery: true))
        precondition(policy.allowsAwake(batteryPercent: 5, onBattery: false))
        precondition(!policy.allowsAwake(batteryPercent: 10, onBattery: true))
    }
}

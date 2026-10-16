import Foundation
import Testing
@testable import ALAS_for_macOS

// 部署进度解析：UTF-8 分块、CR 行、阶段顺序、重置与完成。
struct DeploymentProgressTests {
    @Test func chunkedStreamStageOrderAndCompletion() {
        var download = DeploymentProgress()
        let messages = download.consume(Data("Receiving objects: 10%\rReceiving objects: 20%\rERROR: retry\n".utf8))
        precondition(messages == "ERROR: retry\n")
        precondition(download.detail.contains("20%"))
        download.consume(Data("Receiving objects: 50%, 2 MiB/s\r".utf8))
        precondition(download.detail.contains("50%") && download.detail.contains("2 MiB/s"))
        download.consume(Data("remote: Compressing objects: 60%\r".utf8))
        precondition(download.detail.contains("Compressing objects: 60%"))
        download.consume(Data("Updating files: 75%\r".utf8))
        precondition(download.detail.contains("Updating files: 75%"))
        var progress = DeploymentProgress()
        precondition(progress.fraction == 0)
        let marker = Data("@@ALAS_STAGE:4:下载核心\n".utf8)
        for byte in marker { progress.consume(Data([byte])) }
        precondition(progress.step == 4 && progress.title == "下载核心")
        progress.consume(Data("Receiving objects:  67% (67/100)\r".utf8))
        precondition(progress.detail.contains("67%"))
        progress.consume(Data("@@ALAS_STAGE:2:旧消息\n@@ALAS_STAGE:99:非法步骤\n".utf8))
        precondition(progress.step == 4)
        progress.consume(Data("@@ALAS_STAGE:6:".utf8))
        progress.resetStream()
        progress.consume(Data("@@ALAS_STAGE:7:验证模型\n".utf8))
        precondition(progress.step == 7)
        progress.advance(9, title: "启动界面")
        precondition(progress.fraction < 1)
        progress.finish()
        precondition(progress.fraction == 1 && progress.completed)
        progress.consume(Data("@@ALAS_STAGE:7:延迟日志\n".utf8))
        precondition(progress.title == "部署完成")
    }
}

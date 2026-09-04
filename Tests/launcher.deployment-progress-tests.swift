import Foundation

@main
struct DeploymentProgressTests {
    static func main() {
        var download = DeploymentProgress()
        let messages = download.consume(Data("Receiving objects: 10%\rReceiving objects: 20%\rERROR: retry\n".utf8))
        assert(messages == "ERROR: retry\n")
        assert(download.detail.contains("20%"))
        download.consume(Data("Receiving objects: 50%, 2 MiB/s\r".utf8))
        assert(download.detail.contains("50%") && download.detail.contains("2 MiB/s"))
        download.consume(Data("remote: Compressing objects: 60%\r".utf8))
        assert(download.detail.contains("Compressing objects: 60%"))
        download.consume(Data("Updating files: 75%\r".utf8))
        assert(download.detail.contains("Updating files: 75%"))
        var progress = DeploymentProgress()
        assert(progress.fraction == 0)
        let marker = Data("@@ALAS_STAGE:4:下载核心\n".utf8)
        for byte in marker { progress.consume(Data([byte])) }
        assert(progress.step == 4 && progress.title == "下载核心")
        progress.consume(Data("Receiving objects:  67% (67/100)\r".utf8))
        assert(progress.detail.contains("67%"))
        progress.consume(Data("@@ALAS_STAGE:2:旧消息\n@@ALAS_STAGE:99:非法步骤\n".utf8))
        assert(progress.step == 4)
        progress.consume(Data("@@ALAS_STAGE:6:".utf8))
        progress.resetStream()
        progress.consume(Data("@@ALAS_STAGE:7:验证模型\n".utf8))
        assert(progress.step == 7)
        progress.advance(9, title: "启动界面")
        assert(progress.fraction < 1)
        progress.finish()
        assert(progress.fraction == 1 && progress.completed)
        progress.consume(Data("@@ALAS_STAGE:7:延迟日志\n".utf8))
        assert(progress.title == "部署完成")
        print("DeploymentProgress: UTF-8 chunks, CR lines, stage order, reset and completion passed")
    }
}

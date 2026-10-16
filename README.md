# ALAS for macOS

[ALAS](https://github.com/LmeSzinc/AzurLaneAutoScript) 的 macOS 原生启动器，使用 SwiftUI 和 AppKit，提供环境部署、配置编辑、日志查看和核心进程管理。游戏任务与调度由 ALAS 核心执行。

## 直接使用

### 下载与安装

面向 Apple Silicon Mac，最低系统版本为 macOS 14。

1. 在 [Releases](https://github.com/OxqNbloF/ALAS-for-macOS/releases) 下载 `macOS-arm64.zip` 附件。
2. 解压后将 `ALAS.app` 拖入“应用程序”。
3. 打开 App，等待首次联网部署完成。无需预装 Python、Git、ADB 或 Homebrew。

App 仅使用 ad-hoc 签名，未经 Apple 公证。若 macOS 阻止打开，确认下载来源后，在系统设置的“隐私与安全性”中允许打开。

首次部署需要访问 GitHub 及依赖下载镜像。失败时可查看错误详情、导出日志并重试。

### 配置与运行

在主界面新建或导入 JSON 配置，填写设备连接和任务设置，保存后启动。支持配置复制与导出、任务与字段搜索、调度状态查看、日志筛选、核心启停和外观设置。

配置修改需要手动保存。未编辑的“下一次运行时间”随核心刷新，正在编辑的值会保留。不支持旧数据目录的整体导入。

任务运行时，启动器默认阻止系统闲置休眠，避免自动化被中断；这些设置位于侧边栏「保持唤醒」页，可关闭，或用「退出唤醒状态当电池电量低于」滑动条调整阈值。勾选「合盖后仍保持运行」需要管理员授权，会修改系统 `pmset` 的 `disablesleep`；该设置是持久的，退出应用后仍然生效，关闭该开关时才恢复。需要手动恢复时可在终端执行 `sudo pmset -a disablesleep 0`。

任务执行期间关闭主窗口不会退出应用，任务会在后台继续运行（启动器独立轮询任务状态，不依赖主界面）。在同一页的「后台运行」中开启「关闭主窗口后继续在后台运行」后，没有任务时也常驻后台；点按 Dock 图标可重新打开窗口，Cmd+Q 正常退出。

### 更新与回退

启动器会检查核心更新，也可以在“核心更新”页手动同步。更新前会停止任务；未保存的配置需要先保存或放弃修改。

核心更新复用已安装的环境，只保留一个可回退的核心版本。回退不恢复用户配置，也不切换运行环境；环境缺失或损坏时会报错。

启动器本身需手动更新：退出所有 ALAS 实例，用新 App 替换旧 App。替换或删除 App 不会删除运行数据。

### 数据与排错

运行数据固定保存在：

```text
~/Library/Application Support/AzurLaneAutoScript/
```

用户配置位于 `data/config/`，核心错误日志位于 `data/log/`，启动器错误摘要为 `launcher-errors.log`，首次部署失败报告位于 `reports/`。普通运行输出可直接在界面查看。

不要直接移动数据目录，已安装环境和状态记录包含绝对路径。完整首次部署、模拟器游戏任务和各系统版本兼容性仍需实际验证，构建成功不代表游戏任务可用。

## 开发

### 环境与构建

需要 Apple Silicon Mac 和完整 Xcode。首次使用 Xcode 时，先完成许可确认与组件安装。工程此前使用 Xcode 27 beta 构建。

在仓库根目录执行：

```sh
./scripts/build-app.sh
```

默认使用 `xcode-select` 选中的 Xcode，生成 `dist/ALAS.app`。也可以指定 Xcode 和新的输出路径：

```sh
DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer" \
./scripts/build-app.sh "$PWD/dist/ALAS-local.app"
```

或在 Xcode 中打开 `ALAS for macOS.xcodeproj`，选择 `ALAS for macOS` scheme 和 My Mac 构建。

Debug、Release 及打包脚本仅使用 ad-hoc 签名，不需要开发者账号、证书、团队 ID 或本地签名配置。App Sandbox 和 Hardened Runtime 均关闭，核心与子进程以当前用户权限运行。

### 发布打包

```sh
./scripts/package-release.sh
```

脚本构建 Release App，校验 ad-hoc 签名，压缩后重新解压验证，并在 `dist/` 生成包含版本号、Build 和架构的 ZIP 及 `.sha256` 校验文件。已有输出不会被覆盖，脚本不自动上传附件。

上传这两个文件到对应的 GitHub Release。下载后可在附件所在目录校验：

```sh
shasum -a 256 -c ALAS-0.1.0-build63-macOS-arm64.zip.sha256
```

### 代码与运行环境

源码位于 `ALAS for macOS/`：

- `launcher.*.swift`：应用入口、部署进度、进程管理、存储和错误报告。
- `alas.*.swift`：配置编辑、客户端模型、本机 API 客户端和日志界面。
- `Runtime/bootstrap.sh`、`runtime.py`：私有工具安装、环境部署、核心下载、更新和回退。
- `Runtime/serve.py`、`native_api.py`：核心服务与带令牌认证的本机 HTTP 接口。
- 其余 Runtime 模块：下载、设备缓存、依赖验证和错误日志。

Swift 文件由 Xcode 同步文件夹管理，Runtime 脚本在构建时复制到 App。部署工具使用 Python 3.11，核心环境使用 Python 3.8。核心从官方 GitHub 仓库的 `master` 分支获取，下载校验证书和提交，不允许协议降级或重定向。

原生界面不提供上游 Web 页面。ADB 使用独立本机端口，不接管已有的 5037 服务。macOS 适配放在启动器中，不直接修改下载的上游源码与已安装依赖；固定的运行依赖不会自动适配上游新增要求。

### 测试

一条命令即可创建虚拟环境并运行 Python 单元测试、离线 Git 集成测试和 Xcode 单元测试：

```sh
./scripts/test.sh
```

依赖安装到 `build/test-venv`，只运行 Python 部分可加 `ALAS_SKIP_XCODE_TESTS=1`。Swift 测试位于 `ALASTests/`，属于 `ALAS for macOS` scheme 的 `ALASTests` 单元测试目标（Swift Testing），可在 Xcode 中按 Cmd+U，或直接：

```sh
xcodebuild -project 'ALAS for macOS.xcodeproj' -scheme 'ALAS for macOS' \
  -destination 'platform=macOS,arch=arm64' test
```

`NativeModelTests/liveCatalogDecoding` 是可选集成测试，只有设置 `ALAS_TEST_DATA=<已部署的运行数据目录>` 后才访问本机核心。服务类集成测试需要事先部署的环境，参数见各脚本开头。部署、更新和恢复测试应使用临时数据。Debug 可通过 `ALAS_RUNTIME_ROOT` 指定 `/private/tmp/` 下的测试目录，Release 固定使用 Application Support 目录。

### 许可证

本项目采用 [GNU GPL v3](LICENSE)，与上游 ALAS 一致。

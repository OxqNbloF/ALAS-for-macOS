# ALAS for macOS

[ALAS](https://github.com/LmeSzinc/AzurLaneAutoScript) 的 macOS 原生启动器，使用 SwiftUI 和 AppKit。启动器负责安装环境、编辑配置、查看日志和管理进程，游戏任务与调度仍由 ALAS 核心执行。

当前版本为 0.1.0（Build 62），面向 Apple Silicon。工程的最低系统版本设为 macOS 13，尚未完成该版本的实机兼容性测试。当前使用 Xcode 27 beta 构建。

## 使用

首次打开 App 会联网部署，依次准备私有 Python、Git、ADB、ALAS 核心和运行依赖。无需预装 Python 或 Homebrew，也不需要选择数据目录。

部署工具使用 Python 3.11，核心环境使用 Python 3.8，两者分开安装。核心从官方 GitHub 仓库的 `master` 分支下载；工具和依赖使用脚本中配置的国内镜像。首次无法确认上游提交时会停止部署，可查看日志后重试。

进入主界面后，新建或导入配置，填写设备连接及任务设置，保存后启动。界面提供：

- 配置的新建、复制、删除及 JSON 导入导出。
- 任务和字段搜索、配置编辑、调度状态查看。
- 核心任务启停、日志筛选与复制。
- 核心更新、回退、服务重启和错误诊断。
- 配置字段语言及浅色、深色外观设置。

配置修改需要手动保存。未编辑的“下一次运行时间”跟随核心刷新，正在编辑的值不会被自动覆盖。

当前不提供旧数据目录的整体导入，也不发布上游 Web 页面。原生界面通过带令牌认证的本机 HTTP 接口连接核心，ADB 使用独立本机端口，不接管已有的 5037 服务。

## 数据与日志

所有运行数据保存在：

```text
~/Library/Application Support/AzurLaneAutoScript/
```

主要目录和文件：

```text
AzurLaneAutoScript/
├── bin/                  micromamba
├── bootstrap/            部署用 Python 和 Git
├── tools/                ADB
├── core-download/        首次下载的中间文件
├── core/                 核心 Git 工作树
├── environments/         核心运行环境
├── data/
│   ├── config/           用户配置和 deploy.yaml
│   ├── log/              核心错误日志
│   └── …                 截图等数据
├── cache/uiautomator2/    设备组件下载缓存
├── home/                 子进程私有 HOME
├── tmp/                  临时文件
├── reports/              首次部署失败报告
├── active.json           当前核心和环境记录
├── previous.json         上一个可回退版本
├── environment.json      已安装环境记录
├── installation.json     首次部署恢复记录
├── native-ui.json        界面偏好
└── launcher-errors.log   启动器错误摘要
```

普通输出实时显示在界面中，文件日志只保留错误和异常堆栈。排查问题时先看 `launcher-errors.log`，再看 `data/log/` 中对应配置的日志。首次部署失败还会保存阶段、原因和最近输出，可通过“导出日志…”另存。

App 可以移动、改名或整包替换，删除 App 不会删除运行数据。不要直接移动数据目录：Conda 环境和状态记录中包含绝对路径。

## 更新

普通启动会检查核心更新，“核心更新”页也可以手动检查和同步。更新前会停止核心任务；有未保存的配置时，需要先保存或放弃修改。

核心更新复用已有 Python、Git、ADB 和依赖，不重新安装环境。候选版本会在现有环境中验证，失败时尝试继续使用原版本；更新后的服务启动失败且有上一版本可用时，会尝试自动回退。环境缺失或损坏会报错，不会自动重装。

只保留一个核心回退版本。回退仅切换代码，不恢复用户配置，也不切换运行环境。

启动器本身没有自动更新服务。退出所有 ALAS 实例后，用完整的新 App 替换旧 App 即可，数据目录继续沿用。

## 构建

需要 Apple Silicon Mac 和完整 Xcode。在仓库根目录执行：

```sh
./scripts/build-app.sh
```

默认使用 `/Applications/Xcode-beta.app/Contents/Developer`，生成 `dist/ALAS.app`。脚本构建 Release 版本，执行本机临时签名并校验签名；输出路径已存在时会退出，不覆盖已有 App。

指定 Xcode 和输出路径：

```sh
DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer" \
./scripts/build-app.sh "$PWD/dist/ALAS-local.app"
```

也可以在 Xcode 中打开 `ALAS for macOS.xcodeproj`，选择 `ALAS for macOS` scheme 和 My Mac 构建。签名身份可通过 `ALAS_SIGN_IDENTITY` 指定，必须是本机可用的身份；构建脚本不执行公证。

Xcode 的 Debug 和 Release 签名配置会自动读取本机的 `Config/Signing.local.xcconfig`。首次设置时复制模板，并填写自己的 Apple 开发团队 ID：

```sh
cp Config/Signing.local.xcconfig.example Config/Signing.local.xcconfig
```

本地配置与 `xcuserdata/` 已加入 Git 忽略规则。请在本地配置文件中设置 `DEVELOPMENT_TEAM`，避免通过 Xcode 将个人团队 ID 写回共享工程。未创建本地配置时仍可使用上面的脚本构建本机临时签名包。

## 代码结构

源码位于 `ALAS for macOS/`：

- `launcher.*.swift`：应用入口、启动页、部署进度、进程管理、数据目录和错误报告。
- `alas.*.swift`：主界面、字段编辑、配置模型、本机接口客户端和日志视图。
- `Runtime/bootstrap.sh`：准备私有部署工具，进入 Python 安装器。
- `Runtime/runtime.py`：安装环境、下载核心、关联数据、更新与回退。
- `Runtime/deployment.py`、`git_download.py`：生成部署配置，处理下载进度和超时。
- `Runtime/serve.py`、`native_api.py`：启动核心与独立 ADB，提供原生界面接口。
- `Runtime/device_cache.py`：将设备组件缓存放到可写的数据目录。
- `Runtime/validate.py`、`error_logging.py`：检查依赖和 OCR 模型，过滤文件日志。

Swift 文件由 Xcode 同步文件夹管理，Runtime 脚本在构建时复制到 App。macOS 适配放在启动器中，不直接修改下载的上游源码和已安装依赖。

## 测试

Python 单元测试需要 Python、PyYAML 和 Starlette，离线更新测试还需要 Git：

```sh
python3 -B -m unittest discover -s Tests -p 'test_*.py'
python3 -B Tests/integration_git_updates.py
```

Swift 测试各自包含入口，分别编译运行。例如：

```sh
ALAS_TEST_DIR="$(mktemp -d /private/tmp/alas-tests.XXXXXX)"
xcrun swiftc -parse-as-library \
  "ALAS for macOS/launcher.storage.swift" \
  Tests/launcher.storage-tests.swift \
  -o "$ALAS_TEST_DIR/storage"
"$ALAS_TEST_DIR/storage"
```

服务集成测试需要已部署的环境，参数见各脚本开头。部署、更新和恢复测试应使用临时数据，不要使用日常配置。Debug 构建可通过 `ALAS_RUNTIME_ROOT` 指定 `/private/tmp/` 下的测试目录；Release 固定使用 Application Support 目录。

## 限制

- App Sandbox 关闭，Hardened Runtime 保留。核心和子进程以当前用户权限运行，私有环境不是安全沙盒。
- 核心下载使用官方 GitHub HTTPS 地址，校验证书和提交，不允许协议降级或重定向；未校验独立的发布签名。
- 运行环境按现有依赖固定，不自动适配上游新增的依赖要求。
- 本机临时签名包适合本机测试，不是已公证的分发包。
- 构建或服务启动成功不代表设备连接和游戏任务可用；完整首次部署、模拟器任务、macOS 13 兼容性及正式签名公证仍需实际验证。

## 许可证

本项目与 [ALAS](https://github.com/LmeSzinc/AzurLaneAutoScript/blob/master/LICENSE) 一样采用 GNU GPL v3 许可证

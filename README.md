# ALAS for macOS

[ALAS](https://github.com/LmeSzinc/AzurLaneAutoScript) 的 macOS 原生启动器。负责安装运行环境、编辑配置、查看日志和管理核心进程，游戏任务由 ALAS 核心执行。

## 直接使用

### 安装

要求：Apple Silicon Mac，macOS 14 或更高版本。不需要预装 Python、Git、ADB 或 Homebrew。

1. 在 [Releases](https://github.com/OxqNbloF/ALAS-for-macOS/releases) 下载 `ALAS-<版本>-macOS-arm64.zip`。
2. 解压后把 `ALAS.app` 拖进“应用程序”。
3. 打开 App，等待“正在准备”完成。

App 使用 ad-hoc 签名，未经 Apple 公证。若系统阻止打开，在“系统设置 → 隐私与安全性”中允许即可。

### 首次启动

首次启动会下载并配置 ALAS 核心和私有运行环境，需要联网，通常占用数百 MB 到 1 GB 以上。部分发布包内置了运行组件，可以离线完成。

失败时界面会显示原因，可导出日志后重试；重试会复用已下载的内容。

### 使用

- 新建或导入 JSON 配置，填写模拟器与任务设置，保存后启动。
- 侧栏可以查看调度、实时日志、配置管理和核心更新。
- 配置修改需要手动保存；有未保存修改时不能切换配置或更新。
- 任务运行时默认阻止系统空闲休眠。不支持合盖后继续运行。
- 关闭主窗口不会退出；可在「保持唤醒」页开启后台常驻，点 Dock 图标重新打开，`Cmd+Q` 退出。

### 更新

核心更新在「核心更新」页操作，会先停止任务，并保留一个可回退版本。回退只恢复核心代码，不影响配置和运行环境。

启动器本身需要手动更新：退出 App，用新版本替换旧 App。替换或删除 App 不会删除运行数据。

### 数据

运行数据保存在：

```text
~/Library/Application Support/AzurLaneAutoScript/
```

配置在 `data/config/`，日志在 `data/log/`。不要移动这个目录，环境记录包含绝对路径。删除 App 不会删除数据；彻底清除需要手动删除该目录。

## 开发

需要 Apple Silicon Mac 和完整 Xcode。

构建：

```sh
./scripts/build-app.sh          # 生成 dist/ALAS.app
```

测试：

```sh
./scripts/test.sh                         # Python + Swift
ALAS_SKIP_XCODE_TESTS=1 ./scripts/test.sh # 只跑 Python
```

发布：

```sh
./scripts/package-release.sh    # dist/ 下生成 ZIP 和 .sha256
```

也可以在 Xcode 中打开 `ALAS for macOS.xcodeproj`，选择 `ALAS for macOS` scheme 构建或按 `Cmd+U` 测试。

源码结构：

- `ALAS for macOS/`：SwiftUI 启动器与 `Runtime/` 部署脚本。
- `ALASTests/`：Swift Testing 单元测试；`Tests/`：Python 测试与集成测试。
- `scripts/`：构建、测试、打包，以及可选的 `bundle-runtime.sh`（离线种子）和 `lock-dependencies.sh`（依赖锁）。

`Runtime/` 在构建时复制到 App；首次安装按 `Runtime/locks/` 中的锁定版本安装，缺失时自动回退在线解析。

本项目采用 [GNU GPL v3](LICENSE)，与上游 ALAS 一致。

# 验证范围

当前为 Build 59，采用非沙盒 App、Application Support/AzurLaneAutoScript 固定目录和完整签名 App 替换更新。旧版包内环境、内置核心及沙盒方案的验证记录已移除，避免被误认为当前验收结果。

## 自动测试

- `test_*.py`：下载重试、部署恢复、环境固定、配置接口、错误日志及路径保护。
- `integration_git_updates.py`：临时仓库 A→B→C、单个回退引用、原地回退、中断恢复及配置保留；无需联网。
- `launcher.storage-tests.swift`：固定路径、自动创建、重复准备保留原数据、App 路径与符号链接拒绝、已有配置保留。
- 其余独立 Swift 测试：进度解析、错误日志、失败报告及原生客户端模型。

## 需要完整环境的集成测试

- `integration_runtime.py EXTERNAL_TEST_DATA`：临时安装的再次启动和服务 HTTP 检查，比较环境文件的内容与修改时间。
- `integration_app_startup.py APP_RESOURCES EXTERNAL_TEST_DATA`：独立外部目录、本机进程共享状态与服务启动。
- `integration_native_api.py APP_RESOURCES INSTALLED_DATA`：从已安装核心创建临时 Git 工作树，测试原生接口；不运行游戏任务。

这些测试需要事先部署的环境，不能以静态构建成功代替实际执行结果。当前尚未完成完整联网首次部署、模拟器任务、macOS 13 实机验证或 Developer ID 签名公证。

## Build 58 本轮结果

- 41 项 Python 单元测试通过。
- 离线真实 Git 更新、回退和中断恢复测试通过。
- Swift 存储测试、全部 Python 文件语法检查及 Shell 语法检查通过。
- Release 构建和严格签名验证通过；产物无沙盒 entitlement，保留 Hardened Runtime。
- 未运行需要已安装环境的三项联网/服务集成测试，未执行完整首次部署。

## Build 59 本轮结果

- 运行目录固定为 ~/Library/Application Support/AzurLaneAutoScript；移除目录选择类、路径记录及自动生成目录后缀逻辑。
- Swift 存储测试通过：固定目录名称与位置、自动创建、重复准备不覆盖已有配置、包内路径拒绝和已有配置保留。
- Release 构建及严格签名检查通过；未执行完整联网部署。

## Build 60：设备下载缓存修复

- 启动适配层重定向 uiautomator2 的缓存路径，避免核心重设 appdir 后写入只读 site-packages。通过 ALAS_DATA_ROOT 让 multiprocessing 子进程应用相同规则。
- 已安装的 uiautomator2cache 资源按需复制为可写缓存，不修改包权限、内容或上游核心。
- 使用现有 Python 3.8、uiautomator2 和真实核心运行 integration_device_cache.py：新进程加载核心、APK 资源复制、本机 HTTP 下载、停服后的离线复用均通过，已安装缓存文件的权限与修改时间不变。
- 41 项 Python 单元测试通过；Release Build 60 构建及签名检查通过。
- 本轮未重新运行模拟器游戏任务，ADB closed 是否仍发生需使用新版连接设备后确认。

## Build 61：调度时间显示同步

- 配置页未编辑的 Scheduler.NextRun 随调度总览的同一份 snapshot 刷新，沿用核心 get_next_task() 的调度结果。
- 存在本地编辑时保留输入值及原始冲突检查值，不提交自动保存；不修改后端调度代码或用户配置文件。
- Swift 客户端测试通过：时间同步、刷新不产生编辑、手动时间保留、原始值保留、清除编辑后恢复同步，以及原有消息计时与 JSON 测试。

## Build 62：高风险修复与导入清理

- 移除旧目录导入入口与递归复制实现，仅保留原生配置管理的 JSON 导入。
- 核心源切换到官方 GitHub HTTPS，Git 子进程强制验证证书、禁止非 HTTPS 传输及重定向、禁止仓库钩子执行；首次下载校验提交一致后才检出。
- 原生服务创建独立 Starlette 应用，仅复用上游生命周期回调；不复制原 Web 页面、静态资源、WebSocket 或中间件。
- 45 项 Python 单元测试通过，包括 ASGI 路由隔离、令牌/Origin 验证、旧生命周期保留、Git 协议拒绝和下载提交不一致拒绝。
- 临时仓库真实 Git 更新/回退集成测试、Swift 固定目录与已有配置保留测试通过。
- 不在真实数据目录中重新部署，不启动游戏任务；GitHub HTTPS 的实际下载可达性未作为离线测试结果。
- Release Build 62 构建成功，完整 App 的 `codesign --verify --deep --strict` 通过；使用本机 ad-hoc 签名，未公证。

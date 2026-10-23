# 内置运行时种子

此目录由 `scripts/bundle-runtime.sh` 生成，构建时随 `Runtime/` 一起复制进
`ALAS for macOS.app/Contents/Resources/Runtime/bundled/`。首次部署优先使用这里的
组件，缺失或不可用时自动回退到在线下载，因此普通开发构建保持空目录即可。

| 文件 | 用途 | 回退行为 |
|---|---|---|
| `micromamba` | 私有环境管理器，省去首次下载 | 校验可执行后使用，否则下载 |
| `platform-tools_r37.0.1-darwin.zip` | 私有大 ADB，仍需 SHA256 校验 | 校验失败或缺失时重新下载 |
| `core.bundle` | ALAS 核心的 Git 快照，支持离线检出 | 快照不可用时在线 clone |
| `conda-pkgs/` | Conda 包缓存，配合 `--offline` 安装 | 解析失败时自动改用在线镜像 |
| `mamba/` | Conda 仓库索引缓存，离线解析必需 | 缺失时只能在线解析 |
| `wheels/` | pip 依赖包，配合 `--no-index` 安装 | 安装失败时自动改用在线镜像 |

生成方式、体积和注意事项见仓库根目录 `README.md` 的「离线运行时种子」一节。
这些大文件不纳入版本控制，只作为发布构建的输入。

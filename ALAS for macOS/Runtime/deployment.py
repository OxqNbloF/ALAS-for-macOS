"""生成 macOS 部署配置，固定工具路径和启动器接管的选项。"""
from pathlib import Path
import re

UPSTREAM = "https://github.com/LmeSzinc/AzurLaneAutoScript.git"
BRANCH = "master"
PYPI_MIRRORS = (
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://repo.huaweicloud.com/repository/pypi/simple",
)


def managed_values(root, prefix):
    return {
        "Repository": UPSTREAM, "Branch": BRANCH, "SSLVerify": True,
        "GitExecutable": str(root / "bootstrap/bin/git"),
        "PythonExecutable": str(prefix / "bin/python"),
        "AdbExecutable": str(root / "tools/platform-tools/adb"),
        "PypiMirror": PYPI_MIRRORS[0],
        "EnableReload": False, "AutoUpdate": False, "InstallDependencies": False,
        "CheckUpdateInterval": 0, "AutoRestartTime": None, "ReplaceAdb": False,
        "EnableRemoteAccess": False, "CDN": False, "WebuiHost": "127.0.0.1",
    }


def render(text, values):
    # 保留注释和用户选项，按核心解析器要求写入普通标量。
    missing = []
    for key, value in values.items():
        value = "null" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
        if "\n" in value or "\r" in value:
            raise ValueError("配置值不能包含换行")
        text, count = re.subn(r"(?m)^([ \t]*)" + re.escape(key) + r":[^\n]*",
                             lambda match: match[1] + key + ": " + value, text)
        if not count:
            missing.append(f"{key}: {value}\n")
    return text.rstrip() + "\n" + "".join(missing)


def write_if_changed(path, text):
    # 写入链接目标，避免原子替换断开共享配置。
    path = path.resolve()
    if path.exists() and path.read_text() == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def configure_deploy(source, root, prefix, existing=None):
    values = managed_values(root, prefix)
    # 优先沿用上游模板，缺失时使用内置模板。
    upstream_template = source / "deploy/template"
    if not upstream_template.is_file():
        upstream_template = Path(__file__).with_name("deploy.macos.template.yaml")
    template = render(upstream_template.read_text(), values)
    macos_template = source / "deploy/macOS/template.yaml"
    write_if_changed(macos_template, template)
    target = source / "config/deploy.yaml"
    origin = existing if existing is not None and existing.is_file() else target
    text = origin.read_text() if origin.is_file() else template
    write_if_changed(target, render(text, values))

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
    """按 Deploy.<Section> 分组，便于模板缺键时插入正确层级。"""
    return {
        "Git": {
            "Repository": UPSTREAM, "Branch": BRANCH, "SSLVerify": True,
            "GitExecutable": str(root / "bootstrap/bin/git"), "AutoUpdate": False,
        },
        "Python": {
            "PythonExecutable": str(prefix / "bin/python"), "PypiMirror": PYPI_MIRRORS[0],
            "InstallDependencies": False,
        },
        "Adb": {
            "AdbExecutable": str(root / "tools/platform-tools/adb"), "ReplaceAdb": False,
        },
        "Update": {
            "EnableReload": False, "CheckUpdateInterval": 0, "AutoRestartTime": None,
        },
        "RemoteAccess": {"EnableRemoteAccess": False},
        "Webui": {"WebuiHost": "127.0.0.1", "CDN": False},
    }


def scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    value = str(value)
    if "\n" in value or "\r" in value:
        raise ValueError("配置值不能包含换行")
    return value


def insert_section(lines, section, entries):
    """在 Deploy 下找到或新建 section，按 4 空格缩进写入受管键。"""
    deploy = next((index for index, line in enumerate(lines) if re.match(r"^Deploy:\s*$", line)), None)
    if deploy is None:
        lines.append("Deploy:")
        deploy = len(lines) - 1
    end = len(lines)
    for index in range(deploy + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line[:1].isspace() and not line.lstrip().startswith("#"):
            end = index
            break
    target = next((index for index in range(deploy + 1, end)
                   if re.match(r"^[ \t]+" + re.escape(section) + r":\s*$", lines[index])), None)
    if target is None:
        lines.insert(end, "  " + section + ":")
        target, end = end, end + 1
    for offset, (key, value) in enumerate(entries.items()):
        lines.insert(target + 1 + offset, f"    {key}: {value}")


def render(text, sections):
    # 已有键保留原缩进与注释；缺失键插入到所属 Deploy.<Section>，避免落到顶层。
    lines = text.rstrip().split("\n")
    missing = {}
    for section, entries in sections.items():
        for key, value in entries.items():
            current = scalar(value)
            pattern = re.compile(r"^([ \t]*)" + re.escape(key) + r":[^\n]*")
            replaced = False
            for index, line in enumerate(lines):
                match = pattern.match(line)
                if match:
                    lines[index] = match.group(1) + key + ": " + current
                    replaced = True
            if not replaced:
                missing.setdefault(section, {})[key] = current
    for section, entries in missing.items():
        insert_section(lines, section, entries)
    return "\n".join(lines).rstrip() + "\n"


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

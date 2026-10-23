"""管理环境安装、核心更新与回退，以 active.json 为生效记录。"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import time
import threading
import uuid
import zipfile

import yaml
from deployment import BRANCH, UPSTREAM, PYPI_MIRRORS, configure_deploy

CONDA_FORGE = "https://mirror.nju.edu.cn/anaconda/cloud/conda-forge"
CONDA_MAIN = "https://mirror.nju.edu.cn/anaconda/pkgs/main"
ADB_MIRROR = "https://mirrors.cloud.tencent.com/AndroidSDK/"
RESOURCES = Path(__file__).resolve().parent
NATIVE = {"python", "pip", "numpy", "scipy", "py-mxnet", "libmxnet", "av", "lxml", "pyyaml", "pyzmq", "wrapt", "cffi", "opencv", "ffmpeg"}
ADB_ARCHIVE = "platform-tools_r37.0.1-darwin.zip"
ADB_SHA256 = "ee39ad5967e95c2a07f04dbcbde96b1a0c916ba376096db5d2f498b7727a5d1d"
PYTHON_PACKAGES = {
    "aiofiles", "anyio", "asgiref", "async_generator", "attrs", "certifi", "cffi",
    "charset-normalizer", "click", "colorama", "commonmark", "cryptography",
    "exceptiongroup", "future", "h11", "idna", "imageio", "importlib-metadata",
    "inflection", "jellyfish", "lz4", "pillow", "platformdirs", "prettytable",
    "psutil", "pycparser", "pydantic", "pygments", "pyopenssl", "pysocks", "pyyaml",
    "pyzmq", "requests", "retrying", "rich", "setuptools", "six", "sniffio",
    "sortedcontainers", "starlette", "tqdm", "trio", "typing-extensions", "urllib3",
    "uvicorn", "wcwidth", "websockets", "wheel", "wrapt", "zipp", "outcome",
}


def bundled(*parts):
    """应用包内的运行时种子路径；未打包时由在线下载补齐。"""
    return RESOURCES.joinpath("bundled", *parts)


def dependency_lock(name):
    """已提交的依赖锁；缺失时回退到 environment.macos-arm64.yml 的求解安装。"""
    path = RESOURCES / "locks" / name
    return path if path.is_file() else None


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def environment(root, prefix=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith(
        ("PYTHON", "CONDA", "MAMBA", "PIP_", "DYLD_", "VIRTUAL_ENV", "GIT_"))}
    # 仅为子进程设置私有 HOME，不改用户目录和 Shell 配置。
    env.update({
        "ALAS_DATA_ROOT": str(root.resolve()),
        "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"),
        "XDG_CACHE_HOME": str(root / "cache"), "XDG_CONFIG_HOME": str(root / "home/.config"),
        "PYTHONNOUSERSITE": "1", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "PIP_CONFIG_FILE": os.devnull, "PIP_CACHE_DIR": str(root / "cache/pip"),
        "MAMBA_ROOT_PREFIX": str(root / "mamba"), "CONDA_PKGS_DIRS": str(root / "cache/conda"),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0", "MPLCONFIGDIR": str(root / "cache/matplotlib"),
        "GIT_MERGE_AUTOEDIT": "no",
        # 命令级设置覆盖仓库的 TLS 和钩子配置。
        "GIT_ALLOW_PROTOCOL": "https",
        "GIT_CONFIG_COUNT": "3",
        "GIT_CONFIG_KEY_0": "http.sslVerify", "GIT_CONFIG_VALUE_0": "true",
        "GIT_CONFIG_KEY_1": "http.followRedirects", "GIT_CONFIG_VALUE_1": "false",
        "GIT_CONFIG_KEY_2": "core.hooksPath", "GIT_CONFIG_VALUE_2": os.devnull,
        "ALAS_ADB": str(root / "tools/platform-tools/adb"),
        "PATH": f"{prefix or root / 'bootstrap'}/bin:{root / 'bootstrap/bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
    })
    return env


def run(args, root, prefix=None, cwd=None, capture=False, timeout=1800):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=environment(root, prefix),
                            text=True, stdout=subprocess.PIPE if capture else None,
                            check=True, timeout=timeout)
    return result.stdout.strip() if capture else None


def specification(source):
    reference = source / "environment.macos-arm64.yml"
    if not reference.exists():
        reference = RESOURCES / "environment.macos-arm64.yml"
    data = yaml.safe_load(reference.read_text())
    conda, pip = [], []
    for entry in data["dependencies"]:
        if isinstance(entry, dict):
            for package in entry.get("pip", []):
                if package.split("==")[0] in NATIVE:
                    conda.append(package.replace("==", "="))
                else:
                    pip.append(package)
            continue
        parts = entry.split("=")
        name = parts[0]
        if name in NATIVE:
            package = "=".join(parts[:2])
            if name in {"py-mxnet", "libmxnet"}:
                package = CONDA_MAIN + "::" + package
            conda.append(package)
        elif name in PYTHON_PACKAGES:
            pip.append(name.replace("_", "-") + "==" + parts[1])
    if not {item.split("=")[0].split("::")[-1] for item in conda}.issuperset(NATIVE):
        raise RuntimeError("ARM64 配置缺少 Python / OCR / 图像核心依赖")
    # MXNet 需要 OpenCV .406 ABI；选用 conda-forge 4.6，避免引入额外图形依赖。
    pip += ["graphviz==0.8.4"]
    return {"channels": [CONDA_FORGE, CONDA_MAIN], "dependencies": conda}, sorted(set(pip))


def progress(step, title):
    print(f"\n@@ALAS_STAGE:{step}:{title}", flush=True)


class ProgressReporter:
    """向界面发送单调递增的安装百分比，避免重试时进度回退。"""

    def __init__(self):
        self.value = -1
        self.guard = threading.Lock()

    def set(self, percent):
        value = max(0, min(100, int(percent)))
        with self.guard:
            if value <= self.value:
                return
            self.value = value
        print(f"@@ALAS_PROGRESS:{value}", flush=True)


# 每个部署模式都是独立进程，模块级进度不会跨操作残留。
_progress = ProgressReporter()


def report_progress(percent):
    _progress.set(percent)


def lock_metadata(lock):
    """读取锁头部记录的包数量与总下载字节数；旧锁没有头部时返回 0。"""
    count, size = 0, 0
    if lock is None:
        return count, size
    try:
        for line in lock.read_text().splitlines():
            if line.startswith("# package-count:"):
                count = int(line.split(":", 1)[1])
            elif line.startswith("# total-size:"):
                size = int(line.split(":", 1)[1])
    except (OSError, ValueError):
        return 0, 0
    return count, size


def run_progress(args, root, prefix=None, on_line=None, timeout=1800):
    """流式执行命令，逐行回调、保留原始输出，并在超时后终止。"""
    process = subprocess.Popen([str(a) for a in args], env=environment(root, prefix),
                               text=True, bufsize=1, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
    lines = queue.Queue()

    def read():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=read, daemon=True).start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                if time.monotonic() > deadline:
                    process.kill()
                    raise subprocess.TimeoutExpired([str(a) for a in args], timeout)
                continue
            if line is None:
                break
            if on_line is not None:
                on_line(line)
            sys.stdout.write(line)
            sys.stdout.flush()
        code = process.wait()
    finally:
        process.stdout.close()
    if code:
        raise subprocess.CalledProcessError(code, [str(a) for a in args])


def install_adb(root):
    progress(3, "准备并校验 ADB")
    destination = root / "tools"
    if (destination / "platform-tools/.complete").exists():
        return
    archive = root / "tmp" / ADB_ARCHIVE
    seeded = bundled(ADB_ARCHIVE)
    if seeded.is_file():
        # 包内文件仍需通过固定版本校验；直接读取，不复制到数据目录。
        print("使用应用内打包的 ADB 安装包…", flush=True)
        archive = seeded
    elif not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != ADB_SHA256:
        print("从腾讯国内镜像下载 Google ADB（校验官方固定版本）…", flush=True)
        run(["/usr/bin/curl", "--fail", "--location", "--proto", "=https", "--retry", "2",
             "--retry-all-errors", "--connect-timeout", "20", "--max-time", "300",
             ADB_MIRROR + ADB_ARCHIVE, "-o", archive], root)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ADB_SHA256:
        raise RuntimeError("Google ADB 安装包 SHA256 校验失败")
    with zipfile.ZipFile(archive) as package:
        # 只解压指定文件，防止路径越界。
        for name in ("adb", "lib64/libc++.dylib", "NOTICE.txt", "source.properties"):
            package.extract("platform-tools/" + name, destination)
    (destination / "platform-tools/adb").chmod(0o700)
    (destination / "platform-tools/.complete").touch()


def fingerprint(source):
    spec, pip = specification(source)
    digest = hashlib.sha256(json.dumps([spec, pip]).encode())
    for name in ("requirements.txt", "requirements-in.txt"):
        if (source / name).exists():
            digest.update((source / name).read_bytes())
    digest.update((RESOURCES / "validate.py").read_bytes())
    # 锁内容参与指纹：更新锁会得到新的环境目录，不影响已安装环境。
    for name in ("conda-osx-arm64.lock", "requirements.lock.txt"):
        lock = dependency_lock(name)
        if lock is not None:
            digest.update(lock.read_bytes())
    return digest.hexdigest()[:20]


def validate(root, source, prefix):
    progress(7, "验证运行环境与 OCR 模型")
    print("验证 Web UI、设备控制、图像处理及 OCR 模型…", flush=True)
    run([prefix / "bin/python", RESOURCES / "validate.py", source], root, prefix, timeout=180)


def seed_package_cache(root):
    """复制应用内打包的 Conda 包与索引缓存，返回是否可用于离线解析。"""
    packages = bundled("conda-pkgs")
    if not bundled("conda-pkgs/.complete").is_file() or not packages.is_dir():
        return False
    destination = root / "cache/conda"
    destination.mkdir(parents=True, exist_ok=True)
    for entry in packages.iterdir():
        target = destination / entry.name
        if entry.name != ".complete" and entry.is_file() and not target.exists():
            shutil.copy2(entry, target)
    repodata = bundled("mamba")
    if repodata.is_dir():
        shutil.copytree(repodata, root / "mamba", dirs_exist_ok=True)
    print("已载入应用内打包的运行依赖缓存…", flush=True)
    return True


def create_environment(root, prefix, specfile, offline=False, use_lock=True, on_line=None):
    lock = dependency_lock("conda-osx-arm64.lock") if use_lock else None
    command = [root / "bin/micromamba", "--no-rc"]
    if offline:
        command.append("--offline")
    command += ["create", "-y", "-p", prefix]
    if lock is not None:
        # 显式锁包含完整 URL 与校验值，安装时不再调用求解器。
        command += ["-f", lock]
    else:
        command += ["--override-channels", "-f", specfile]
    if on_line is None:
        run(command, root)
    else:
        run_progress(command, root, on_line=on_line)


def pip_install(root, prefix, requirements, mirror=None, offline=False, hashes=False, on_line=None):
    command = [prefix / "bin/python", "-m", "pip", "--isolated", "install"]
    if offline:
        command += ["--no-index", "--find-links", bundled("wheels")]
    if mirror:
        command += ["--index-url", mirror, "--retries", "2", "--timeout", "20"]
    if hashes:
        command.append("--require-hashes")
    command += ["--disable-pip-version-check", "-r", requirements]
    if on_line is None:
        run(command, root, prefix)
    else:
        run_progress(command, root, prefix, on_line=on_line)


def install_from_mirrors(root, prefix, requirements, hashes=False, on_line=None):
    for index, mirror in enumerate(PYPI_MIRRORS):
        print(f"从国内 PyPI 镜像安装首次运行依赖：{mirror}", flush=True)
        try:
            pip_install(root, prefix, requirements, mirror=mirror, hashes=hashes, on_line=on_line)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if index == len(PYPI_MIRRORS) - 1:
                raise
            print("当前镜像安装失败，尝试下一个国内镜像…", flush=True)


def install_pip(root, prefix, requirements, reporter=None):
    progress(6, "安装 Python 运行依赖")
    # 仅首次安装依赖，不读取用户 pip 配置或更换依赖版本。
    lock = dependency_lock("requirements.lock.txt")
    total = 0
    try:
        source = lock if lock is not None else Path(requirements)
        total = sum(1 for line in source.read_text().splitlines()
                    if "==" in line and not line.lstrip().startswith("#"))
    except OSError:
        total = 0
    collected = 0

    def on_line(line):
        nonlocal collected
        if reporter is None:
            return
        if line.startswith("Collecting "):
            collected += 1
            reporter.set(60 + int(30 * min(collected / max(total, 1), 1)))
        elif line.startswith("Installing collected packages"):
            reporter.set(92)
        elif line.startswith("Successfully installed"):
            reporter.set(94)

    callback = on_line if reporter is not None else None
    wheels = bundled("wheels")
    if wheels.is_dir():
        print("使用应用内打包的 Python 依赖…", flush=True)
        try:
            pip_install(root, prefix, lock or requirements, offline=True,
                        hashes=lock is not None, on_line=callback)
            return
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            print("应用内依赖不完整，改用在线镜像…", flush=True)
    try:
        install_from_mirrors(root, prefix, lock or requirements, hashes=lock is not None,
                             on_line=callback)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if lock is None:
            raise
        print("锁定的 Python 依赖不可用，回退到求解安装…", flush=True)
        install_from_mirrors(root, prefix, requirements, on_line=callback)


def watch_conda_cache(root, total, reporter, stop):
    """安装 Conda 依赖时按包缓存体积估算下载百分比。"""
    cache = root / "cache/conda"
    while not stop.wait(0.4):
        try:
            size = sum(path.stat().st_size for path in cache.iterdir() if path.is_file())
        except OSError:
            continue
        reporter.set(10 + int(45 * min(size / total, 1)))


def directory_size(path):
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def slim_environment(prefix, label="运行环境"):
    """删除运行期不需要的编译产物、文档和测试，尽量减小部署占用。

    只处理确定不会参与运行的文件：C 头文件、静态库、包测试、字节码缓存和
    安装后才能删掉的 pip。任何删除失败都跳过，不影响启动。
    """
    before = directory_size(prefix)
    targets = []
    for name in ("include", "share/man", "share/doc", "share/info", "man", "info"):
        targets.append(prefix / name)
    for pattern in ("lib/python*/test", "lib/python*/config-*", "lib/python*/ensurepip"):
        targets.extend(prefix.glob(pattern))
    for packages in prefix.glob("lib/python*/site-packages"):
        targets.extend(packages.glob("*/tests"))
        targets.extend(packages.glob("*/test"))
        targets.extend([packages / "pip", packages / "wheel"])
    targets.extend(prefix.rglob("__pycache__"))
    root = prefix.resolve()
    for target in targets:
        try:
            if not target.is_dir() or target.is_symlink():
                continue
            # 防止异常符号链接把删除操作带出环境目录。
            if root not in target.resolve().parents:
                continue
            shutil.rmtree(target)
        except OSError:
            continue
    for pattern in ("**/*.pyc", "**/*.pyo", "lib/*.a", "lib/*.la"):
        for path in prefix.glob(pattern):
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                path.unlink()
            except OSError:
                continue
    saved = max(0, before - directory_size(prefix))
    print(f"已精简{label}，释放 {saved // (1024 * 1024)} MB", flush=True)
    return saved


def install_environment(root, source):
    if (root / "active.json").exists() or (root / "environment.json").exists():
        raise RuntimeError("环境已保存，禁止自动重装或升级依赖")
    progress(5, "创建 ARM64 独立环境")
    report_progress(10)
    key = fingerprint(source)
    # 原生库包含绝对路径，安装后不能移动 Conda 环境。
    prefix = root / "environments" / key
    if not (prefix / ".complete").exists():
        if prefix.exists():
            prefix.rename(prefix.with_name(key + ".incomplete-" + uuid.uuid4().hex[:8]))
        spec, requirements = specification(source)
        specfile, reqfile = root / "tmp" / f"{key}.yml", root / "tmp" / f"{key}.txt"
        specfile.write_text(yaml.safe_dump(spec))
        reqfile.write_text("\n".join(requirements) + "\n")
        print("创建完整 ARM64 运行环境（优先使用锁定的依赖）…", flush=True)
        offline = seed_package_cache(root)
        conda_lock = dependency_lock("conda-osx-arm64.lock")
        package_count, download_size = lock_metadata(conda_lock)
        linked = 0

        def on_conda_line(line):
            nonlocal linked
            if line.startswith("Linking "):
                linked += 1
                if package_count:
                    _progress.set(56 + int(2 * min(linked / package_count, 1)))
        # 先试锁定版本（可离线），再试锁定版本在线，最后才退回求解器。
        attempts = [(True, offline)]
        if offline:
            attempts.append((True, False))
        if conda_lock is not None:
            attempts.append((False, False))
        for index, (use_lock, use_offline) in enumerate(attempts):
            stop = threading.Event()
            watcher = None
            if download_size:
                watcher = threading.Thread(target=watch_conda_cache,
                                           args=(root, download_size, _progress, stop), daemon=True)
                watcher.start()
            try:
                create_environment(root, prefix, specfile, use_offline, use_lock,
                                   on_line=on_conda_line)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if index == len(attempts) - 1:
                    raise
                print("应用内依赖不完整，改用在线镜像重试…" if use_offline
                      else "锁定的 Conda 版本不可用，改用求解器解析…", flush=True)
                if prefix.exists():
                    prefix.rename(prefix.with_name(key + ".incomplete-" + uuid.uuid4().hex[:8]))
            finally:
                stop.set()
                if watcher is not None:
                    watcher.join(timeout=1)
        report_progress(58)
        install_pip(root, prefix, reqfile, reporter=_progress)
        report_progress(95)
        run([prefix / "bin/python", "-m", "pip", "check"], root, prefix)
        report_progress(96)
        validate(root, source, prefix)
        slim_environment(prefix)
        (prefix / ".complete").touch()
    else:
        validate(root, source, prefix)
    return prefix


def is_user_config(entry):
    return entry.is_file() and entry.suffix in (".json", ".yaml", ".yml") and not entry.name.startswith(
        ("template", "deploy.template"))


def preserve_configs(root, source):
    # 更新前收集核心目录中新增的配置。
    for entry in (source / "config").iterdir():
        if is_user_config(entry) and not entry.is_symlink():
            shutil.copy2(entry, root / "data/config" / entry.name)


def attach_data(root, source):
    config = source / "config"
    config.mkdir(exist_ok=True)
    destination = root / "data/config"
    for entry in config.iterdir():
        if is_user_config(entry) and not (destination / entry.name).exists():
            shutil.copy2(entry, destination / entry.name)
    for entry in destination.iterdir():
        target = config / entry.name
        if target.is_symlink():
            continue
        if target.is_file():
            target.unlink()  # 删除核心目录内的副本，持久配置已保存在 data/config。
        if not target.exists():
            target.symlink_to(entry)
    for name in ("log", "screenshot", "screenshots"):
        destination, bundled = root / "data" / name, source / name
        destination.mkdir(parents=True, exist_ok=True)
        if bundled.exists() and not bundled.is_symlink():
            shutil.copytree(bundled, destination, dirs_exist_ok=True)
            bundled.rename(source / (name + ".seed"))
        if not bundled.is_symlink():
            bundled.symlink_to(destination)


def saved_environment(root, active=None):
    record = root / "environment.json"
    saved = json.loads(record.read_text()) if record.exists() else active
    if not saved:
        return None
    prefix = Path(saved["environment"])
    if root.resolve() not in prefix.resolve().parents:
        raise RuntimeError("固定环境不在当前数据目录内；请恢复数据目录或导入配置后重新部署")
    if not (prefix / ".complete").is_file() or not os.access(prefix / "bin/python", os.X_OK):
        raise RuntimeError("已保存的运行环境损坏；不会自动下载、重建或升级依赖")
    if not os.access(root / "tools/platform-tools/adb", os.X_OK):
        raise RuntimeError("已保存的 ADB 缺失；不会在后续启动中重新安装工具")
    if not record.exists() or saved.get("locked") is not True:
        # 补齐环境状态记录，不改已安装的包。
        atomic_json(record, {"environment": str(prefix), "locked": True,
                             "frozen": bool(saved.get("frozen", False)),
                             "cacheCleaned": bool(saved.get("cacheCleaned", False))})
    return prefix


def clean_download_cache(root):
    """清理首次安装缓存，保留核心、工具和环境。"""
    record = root / "environment.json"
    state = json.loads(record.read_text())
    if state.get("cacheCleaned") is True:
        return
    print("清理首次安装下载缓存…", flush=True)
    # 同时清理 HOME 下的 pip / 构建缓存，避免首次安装后残留。
    allowed = [root / "cache", root / "tmp", root / "mamba",
               root / "home/Library/Caches", root / "home/.cache", root / "home/.conda/pkgs"]
    root_resolved = root.resolve()
    for path in allowed:
        resolved = path.resolve()
        if resolved == root_resolved or root_resolved not in resolved.parents:
            raise RuntimeError("拒绝清理运行目录之外的缓存")
        if path.exists():
            shutil.rmtree(path)
    for name in ("cache", "tmp"):
        (root / name).mkdir(mode=0o700)
    state.update({"locked": True, "cacheCleaned": True})
    atomic_json(record, state)
    print("下载缓存已清理；运行环境已固定。", flush=True)


def freeze_environment(root, prefix):
    """验证通过后，将工具和依赖设为只读。"""
    record = root / "environment.json"
    state = json.loads(record.read_text())
    if state.get("frozen") is True:
        return
    print("固定私有 Python、Git、ADB 与运行依赖…", flush=True)
    targets = [root / "bootstrap", root / "tools/platform-tools", root / "bin", prefix]
    resolved_root = root.resolve()
    for target in targets:
        if not target.exists():
            continue
        if resolved_root not in target.resolve().parents:
            raise RuntimeError("拒绝固定数据目录之外的文件")
        entries = [target] + list(target.rglob("*"))
        # 先处理文件，再从内到外处理目录，不修改符号链接的目标权限。
        for path in reversed(entries):
            if path.is_symlink():
                continue
            mode = path.stat().st_mode & 0o777
            path.chmod(mode & ~0o222)
    state.update({"locked": True, "frozen": True})
    atomic_json(record, state)
    print("运行环境已设为只读固定状态。", flush=True)


ROLLBACK_REF = "refs/alas/rollback"
CANDIDATE_REF = "refs/alas/candidate"


def git_revision(root, repository, revision="HEAD"):
    return run([root / "bootstrap/bin/git", "-C", repository, "rev-parse", revision],
               root, capture=True)


def checkout_core(root, repository, revision):
    git = root / "bootstrap/bin/git"
    run([git, "-C", repository, "checkout", "--force", "-B", BRANCH, revision], root)
    run([git, "-C", repository, "submodule", "update", "--init", "--recursive", "--depth", "1"],
        root, timeout=900)


def begin_core_update(root, repository, expected_revision=None):
    """下载候选版本，暂不切换当前版本。"""
    progress(4, "从上游更新 ALAS 核心")
    if not (repository / ".git/HEAD").is_file():
        raise RuntimeError("ALAS 核心不是可更新的 Git 工作树")
    git = root / "bootstrap/bin/git"
    old_revision = git_revision(root, repository)
    print(f"从 {UPSTREAM} 获取 {BRANCH} 差异…", flush=True)
    run([git, "-C", repository, "remote", "set-url", "origin", UPSTREAM], root)
    run([git, "-C", repository, "update-ref", "-d", CANDIDATE_REF], root)
    run([git, "-C", repository, "fetch", "--progress", "--force", "--no-tags", "--depth", "1",
         "origin", f"+refs/heads/{BRANCH}:{CANDIDATE_REF}"], root, timeout=900)
    new_revision = git_revision(root, repository, CANDIDATE_REF)
    if expected_revision is None:
        expected_revision = run([git, "ls-remote", "--exit-code", UPSTREAM,
                                 f"refs/heads/{BRANCH}"], root, capture=True, timeout=30).split()[0]
    if expected_revision and new_revision != expected_revision:
        compact_core(root, repository)
        raise RuntimeError("上游提交在检查与下载期间发生变化，请重试")
    try:
        run([git, "-C", repository, "checkout", "--force", "--detach", CANDIDATE_REF], root)
        if not (repository / "gui.py").is_file():
            raise RuntimeError("上游代码不完整：缺少 gui.py")
    except Exception:
        abort_core_update(root, repository, old_revision)
        raise
    return old_revision, new_revision


def compact_core(root, repository):
    """保留当前版本和一个回退引用，清理多余历史。"""
    git = root / "bootstrap/bin/git"
    run([git, "-C", repository, "update-ref", "-d", CANDIDATE_REF], root)
    # 同步远程引用，避免初始版本一直被保留。
    refs = run([git, "-C", repository, "for-each-ref", "--format=%(refname)",
                "refs/remotes/origin"], root, capture=True)
    for ref in refs.splitlines():
        run([git, "-C", repository, "update-ref", "--no-deref", "-d", ref], root)
    run([git, "-C", repository, "reflog", "expire", "--expire=now", "--all"], root)
    run([git, "-C", repository, "gc", "--prune=now"], root, timeout=900)


def finish_core_update(root, repository, old_revision, new_revision):
    git = root / "bootstrap/bin/git"
    run([git, "-C", repository, "update-ref", ROLLBACK_REF, old_revision], root)
    checkout_core(root, repository, new_revision)


def abort_core_update(root, repository, old_revision):
    checkout_core(root, repository, old_revision)
    compact_core(root, repository)


def recover_core(root):
    """更新或启动服务前，恢复中断的版本切换。"""
    record = root / "active.json"
    if not record.is_file():
        record = root / "installation.json"
    if not record.is_file():
        return
    saved = json.loads(record.read_text())
    repository = Path(saved["repository"])
    if git_revision(root, repository) != saved["revision"]:
        print("恢复中断更新前的 ALAS 核心…", flush=True)
        checkout_core(root, repository, saved["revision"])


def clean_core_history(root, repository):
    # 版本已生效，后续清理失败不再触发回退。
    try:
        compact_core(root, repository)
    except (OSError, subprocess.SubprocessError) as error:
        print(f"核心已保存，Git 历史清理稍后重试：{error}", flush=True)


def bundled_core_bundle():
    bundle = bundled("core.bundle")
    return bundle if bundle.is_file() else None


def clone_bundled_core(root, bundle, checkout):
    """从应用内 Git 打包文件检出核心；仅对本次命令放开 file 协议。"""
    from git_download import download
    git = root / "bootstrap/bin/git"
    print("从应用内打包的核心快照检出…", flush=True)
    download([git, "clone", "--quiet", "--branch", BRANCH, bundle, checkout],
             dict(environment(root), GIT_ALLOW_PROTOCOL="file"))
    run([git, "-C", checkout, "remote", "set-url", "origin", UPSTREAM], root)
    (checkout / ".git/alas-seed").touch()


def install_remote_core(root):
    from git_download import download
    progress(4, "从远程下载 ALAS 核心")
    source = root / "core"
    git = root / "bootstrap/bin/git"
    if not source.exists():
        # 保留仓库供失败后重试
        checkout = root / "core-download"
        if checkout.is_symlink():
            raise RuntimeError("下载目录异常，请检查安装日志")
        bundle = bundled_core_bundle()
        seeded = (checkout / ".git/alas-seed").is_file()
        if not (checkout / ".git/HEAD").is_file() and bundle is not None:
            try:
                clone_bundled_core(root, bundle, checkout)
                seeded = True
            except (OSError, subprocess.SubprocessError) as error:
                print(f"应用内核心快照不可用，改用在线下载：{error}", flush=True)
                shutil.rmtree(checkout, ignore_errors=True)
        if not (checkout / ".git/HEAD").is_file():
            run([git, "init", checkout], root, timeout=30)
        if not seeded:
            remote = run([git, "ls-remote", "--exit-code", UPSTREAM,
                          f"refs/heads/{BRANCH}"], root, capture=True, timeout=30).split()[0]
            reference = f"refs/remotes/origin/{BRANCH}"
            try:
                received = run([git, "-C", checkout, "rev-parse", "--verify", "--quiet", reference],
                               root, capture=True, timeout=30)
            except subprocess.CalledProcessError:
                received = None
            run([git, "-C", checkout, "config", "remote.origin.url", UPSTREAM], root, timeout=30)
            if received != remote:
                print("继续下载核心，复用已完成对象；等待服务器打包…", flush=True)
                download([git, "-C", checkout, "fetch", "--progress", "--depth", "1",
                          "--no-tags", "origin", f"+refs/heads/{BRANCH}:{reference}"], environment(root))
            fetched = run([git, "-C", checkout, "rev-parse", "--verify", reference],
                          root, capture=True, timeout=30)
            if fetched != remote:
                raise RuntimeError("上游提交在检查与下载期间发生变化，请重试")
            print("核心对象已下载，正在检出文件…", flush=True)
            download([git, "-C", checkout, "checkout", "--progress", "--force", "-B", BRANCH,
                      reference], environment(root))
        if not (checkout / ".git/HEAD").is_file() or not (checkout / "gui.py").is_file():
            raise RuntimeError("下载的核心不完整，请重试")
        checkout.rename(source)
    if not (source / ".git/HEAD").is_file() or not (source / "gui.py").is_file():
        raise RuntimeError("核心目录异常，请检查安装日志")
    revision = run([git, "-C", source, "rev-parse", "HEAD"], root, capture=True)
    return source, revision


def initial_core(root):
    progress(4, "准备 ALAS 核心")
    pending = root / "installation.json"
    if pending.is_file():
        saved = json.loads(pending.read_text())
        source = Path(saved["repository"])
        if source == root / "core" and (source / "gui.py").is_file():
            print("继续首次安装，复用已部署的 ALAS 核心…", flush=True)
            return source, saved["revision"]
        raise RuntimeError("首次安装记录中的核心缺失或损坏，请检查安装日志")
    source, revision = install_remote_core(root)
    record = {"repository": str(source), "revision": revision}
    if (source / ".git/alas-seed").is_file():
        record["bundled"] = True
        print("已从应用内核心快照安装核心，本次不访问上游。", flush=True)
    atomic_json(pending, record)
    return source, revision


def seeded_core(root):
    """首次安装的核心是否来自应用内快照。"""
    record = root / "installation.json"
    if not record.is_file():
        return False
    try:
        return json.loads(record.read_text()).get("bundled") is True
    except (OSError, ValueError):
        return False


def refresh_initial_core(root, source, revision):
    # 续装时同步最新核心
    progress(4, "检查 ALAS 核心更新")
    print("检查已下载核心是否为上游最新版本…", flush=True)
    git = root / "bootstrap/bin/git"
    try:
        remote = run([git, "ls-remote", "--exit-code", UPSTREAM, f"refs/heads/{BRANCH}"],
                     root, capture=True, timeout=30)
        remote_revision = remote.split()[0]
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, IndexError):
        raise RuntimeError("无法确认最新核心版本，请联网后重试")
    if remote_revision == revision:
        print("ALAS 核心已是上游最新版本", flush=True)
        return source, revision
    print("发现更新，下载核心差异…", flush=True)
    old_revision, updated_revision = begin_core_update(root, source, remote_revision)
    finish_core_update(root, source, old_revision, updated_revision)
    atomic_json(root / "installation.json", {
        "repository": str(source), "revision": updated_revision})
    clean_core_history(root, source)
    return source, updated_revision


def prepare(root):
    # 启动和手动更新只检查核心，复用首次安装的工具与依赖。
    report_progress(1)
    active_path = root / "active.json"
    active = json.loads(active_path.read_text()) if active_path.exists() else None
    prefix = saved_environment(root, active)
    reuse_environment = prefix is not None
    if reuse_environment:
        freeze_environment(root, prefix)
        clean_download_cache(root)
    if active:
        current = Path(active["repository"])
        configure_deploy(current, root, prefix)
        print("检查 ALAS 核心更新（不修改运行环境）…", flush=True)
        remote = run([root / "bootstrap/bin/git", "ls-remote", "--exit-code", UPSTREAM,
                      f"refs/heads/{BRANCH}"], root, capture=True, timeout=30)
        revision = remote.split()[0]
        if revision == active.get("revision"):
            print("已是上游最新版本", flush=True)
            return
    elif prefix is None:
        install_adb(root)
        report_progress(5)
    old_revision = None
    if active:
        release = Path(active["repository"])
        preserve_configs(root, release)
        old_revision, revision = begin_core_update(root, release, revision)
    else:
        release, revision = initial_core(root)
        if seeded_core(root):
            # 包内快照是随 App 发布的固定版本，首次启动无需联网校验。
            print("使用应用内核心快照，跳过首次在线版本检查", flush=True)
        else:
            release, revision = refresh_initial_core(root, release, revision)
    report_progress(9)
    if prefix is None:
        prefix = install_environment(root, release)
        # 立即记录已安装环境，避免后续写入失败导致重复安装。
        atomic_json(root / "environment.json", {
            "environment": str(prefix), "locked": False, "frozen": False,
            "cacheCleaned": False})
    try:
        configure_deploy(release, root, prefix,
                         Path(active["repository"]) / "config/deploy.yaml" if active else None)
        if reuse_environment:
            # 用现有环境验证兼容性，不安装依赖。
            validate(root, release, prefix)
        progress(8, "保存 macOS 部署配置")
        attach_data(root, release)
        report_progress(98)
        if active:
            finish_core_update(root, release, old_revision, revision)
        new = {"repository": str(release), "environment": str(prefix), "revision": revision}
        if active:
            previous = dict(active)
            previous["repository"] = str(release)
            previous["revision"] = old_revision
            atomic_json(root / "previous.json", previous)
        else:
            try:
                rollback_revision = git_revision(root, release, ROLLBACK_REF)
            except subprocess.CalledProcessError:
                rollback_revision = None
            if rollback_revision and rollback_revision != revision:
                atomic_json(root / "previous.json", {
                    "repository": str(release), "environment": str(prefix),
                    "revision": rollback_revision})
        atomic_json(active_path, new)
    except Exception:
        if active and old_revision:
            abort_core_update(root, release, old_revision)
            attach_data(root, release)
            configure_deploy(release, root, prefix)
        raise
    if not active:
        slim_environment(root / "bootstrap", label="工具链")
        freeze_environment(root, prefix)
        clean_download_cache(root)
    clean_core_history(root, release)
    report_progress(99)
    print(f"部署占用：{directory_size(root) // (1024 * 1024)} MB", flush=True)
    print("核心更新完成；运行环境未改变，上一版本可回退。" if active else "完整运行环境已就绪", flush=True)


def rollback(root):
    previous = json.loads((root / "previous.json").read_text())
    current = json.loads((root / "active.json").read_text())
    prefix = saved_environment(root, current)
    repository = Path(current["repository"])
    previous_revision = previous["revision"]
    current_revision = current["revision"]
    preserve_configs(root, repository)
    try:
        checkout_core(root, repository, previous_revision)
        attach_data(root, repository)
        configure_deploy(repository, root, prefix)
        restored = {"repository": str(repository), "environment": str(prefix),
                    "revision": previous_revision}
        alternate = {"repository": str(repository), "environment": str(prefix),
                     "revision": current_revision}
        run([root / "bootstrap/bin/git", "-C", repository, "update-ref",
             ROLLBACK_REF, current_revision], root)
        atomic_json(root / "active.json", restored)
        atomic_json(root / "previous.json", alternate)
    except Exception:
        checkout_core(root, repository, current_revision)
        raise
    clean_core_history(root, repository)
    print("已回退 ALAS 核心；运行环境和用户配置保持不变", flush=True)


@contextlib.contextmanager
def lock(root):
    with (root / "runtime.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("另一项安装、更新或服务正在运行")
        yield


# 拒绝包内及越界运行路径
def validate_storage(root):
    root = root.resolve()
    if root == Path("/") or any(part.lower().endswith(".app") for part in root.parts):
        raise RuntimeError("运行数据必须位于 App 外的独立目录")
    for name in ("active.json", "previous.json", "installation.json", "environment.json"):
        path = root / name
        if not path.is_file():
            continue
        saved = json.loads(path.read_text())
        for key in ("repository", "environment"):
            if key in saved:
                target = Path(saved[key]).resolve()
                if root not in target.parents:
                    raise RuntimeError("旧运行路径不可复用，请通过配置管理导入配置后重新部署")


def main():
    # 启动器退出时统一终止进程组，包括安装器和核心子进程。
    if os.getpgrp() != os.getpid():
        os.setsid()
    owner = os.environ.get("ALAS_LAUNCHER_PID")
    if owner:
        def watch_owner():
            while True:
                time.sleep(1)
                if os.getppid() != int(owner):
                    os.killpg(os.getpgrp(), signal.SIGKILL)
        threading.Thread(target=watch_owner, daemon=True).start()
    mode, raw_root = sys.argv[1:3]
    root = Path(raw_root).resolve()
    validate_storage(root)
    for name in ("tmp", "home", "cache", "environments", "data/config"):
        (root / name).mkdir(parents=True, exist_ok=True)
    with lock(root):
        recover_core(root)
        if mode in ("prepare", "update"):
            prepare(root)
        elif mode == "rollback":
            rollback(root)
        elif mode == "serve":
            active = json.loads((root / "active.json").read_text())
            prefix = saved_environment(root, active)
            child = subprocess.Popen([str(prefix / "bin/python"), str(RESOURCES / "serve.py"),
                                      active["repository"], str(root / "endpoint.json"), str(root)],
                                     env=environment(root, prefix))
            def stop(signum, frame):
                if child.poll() is None:
                    child.terminate()
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            code = child.wait()
            if code:
                raise RuntimeError(f"Web 服务退出：{code}")
        else:
            raise ValueError("未知操作")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"操作失败：{error}", file=sys.stderr, flush=True)
        sys.exit(1)

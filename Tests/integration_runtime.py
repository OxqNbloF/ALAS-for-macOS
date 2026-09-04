"""检查临时环境的再次启动和 HTTP 服务，不改已安装的依赖。

用法：python -B Tests/integration_runtime.py /private/tmp/alas-...
会写入运行代码、配置及日志元数据，仅用于临时测试环境。
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

RUNTIME = Path(__file__).resolve().parents[1] / "ALAS for macOS/Runtime"


def snapshot(root):
    result = {}
    for directory in ("bootstrap", "environments", "tools", "bin"):
        for path in sorted((root / directory).rglob("*")):
            info = path.lstat()
            if path.is_symlink():
                content = os.readlink(path)
            elif path.is_file():
                content = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                continue
            result[str(path.relative_to(root))] = (info.st_mtime_ns, info.st_mode, content)
    return result


def main():
    root = Path(sys.argv[1]).resolve()
    if not str(root).startswith("/private/tmp/alas-"):
        raise ValueError("Only an explicit temporary ALAS test root is allowed")
    before = snapshot(root)
    print(f"Recorded {len(before)} immutable files/symlinks", flush=True)
    command = ["/bin/bash", str(RUNTIME / "bootstrap.sh")]
    subprocess.run(command + ["prepare", str(root)], check=True, timeout=1200)
    assert before == snapshot(root), "Warm start changed installed tools or packages"
    print("Warm start: installed environment byte hashes and mtimes unchanged", flush=True)

    endpoint = root / "endpoint.json"
    endpoint.unlink(missing_ok=True)
    with (root / "integration-service.log").open("w") as log:
        process = subprocess.Popen(command + ["serve", str(root)], stdout=log, stderr=log,
                                   start_new_session=True)
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Web service exited; inspect integration-service.log")
                if endpoint.is_file():
                    url = json.loads(endpoint.read_text())["url"]
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(url, timeout=3) as response:
                        assert response.status == 200
                        html = response.read()
                        assert b"pywebio" in html.lower()
                        print(f"Web UI HTTP 200: {len(html)} bytes at {url}", flush=True)
                        break
                time.sleep(0.2)
            else:
                raise TimeoutError("Web UI never became ready")
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            # 只清理本次测试进程组中的残留子进程。
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    assert before == snapshot(root), "Serve changed installed tools or packages"
    print("PASS: warm startup and Web UI preserved all installed files", flush=True)


if __name__ == "__main__":
    main()

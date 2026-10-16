"""检查临时环境的再次启动和本机原生接口，不改已安装的依赖。

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
                    raise RuntimeError("Native service exited; inspect integration-service.log")
                if endpoint.is_file():
                    ready = json.loads(endpoint.read_text())
                    url = ready["url"]
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    # 根路由只返回健康检查；上游网页在 Build 62 后不再挂载。
                    with opener.open(url + "/", timeout=3) as response:
                        assert response.status == 200
                        assert json.loads(response.read()).get("status") == "ok"
                    request = urllib.request.Request(url + "/native/ui-preferences",
                        headers={"Authorization": "Bearer " + ready["token"]})
                    with opener.open(request, timeout=3) as response:
                        assert response.status == 200
                        assert "language" in json.loads(response.read())
                    print(f"Native service ready (health + authenticated API) at {url}", flush=True)
                    break
                time.sleep(0.2)
            else:
                raise TimeoutError("Native service never became ready")
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
    print("PASS: warm startup and native service preserved all installed files", flush=True)


if __name__ == "__main__":
    main()

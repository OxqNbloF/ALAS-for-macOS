"""检查长临时路径、进程共享状态和核心服务启动。

用法：APP_BOOTSTRAP_PYTHON -B Tests/integration_app_startup.py APP_RESOURCES EXTERNAL_TEST_DATA
复用已安装的测试环境，不安装或更新依赖和核心。
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from types import SimpleNamespace
from integration_runtime import snapshot


def main():
    resources, root = [Path(value).resolve() for value in sys.argv[1:3]]
    if not str(root).startswith("/private/tmp/alas-"):
        raise ValueError("Use an explicit temporary external runtime")
    sys.path.insert(0, str(resources / "Runtime"))
    import runtime
    import serve
    active = json.loads((root / "active.json").read_text())
    prefix = Path(active["environment"])
    before = snapshot(root)
    with runtime.lock(root):
        os.environ.update(runtime.environment(root, prefix))
        tempfile.tempdir = str(root / "tmp")
        state = SimpleNamespace(_init=False)
        serve.initialize_shared_state(state)
        try:
            assert state.manager.address[0] == "127.0.0.1"
            shared = state.manager.dict()
            shared["ready"] = True
            assert shared["ready"]
            event = state.manager.Event()
            event.set()
            assert event.is_set()
            print(f"PASS: authenticated Manager proxies on loopback; TMPDIR {len(tempfile.tempdir.encode())} bytes", flush=True)
        finally:
            state.manager.shutdown()
        with tempfile.TemporaryDirectory(prefix="startup-test-", dir=root / "tmp") as temporary:
            endpoint = Path(temporary) / "endpoint.json"
            log_path = Path(temporary) / "service.log"
            with log_path.open("w") as log:
                process = subprocess.Popen([str(prefix / "bin/python"), "-B",
                    str(resources / "Runtime/serve.py"), active["repository"], str(endpoint), str(root)],
                    env=runtime.environment(root, prefix), stdout=log, stderr=log,
                    start_new_session=True)
                try:
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError(log_path.read_text())
                        if endpoint.is_file():
                            url = json.loads(endpoint.read_text())["url"]
                            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                            with opener.open(url, timeout=5) as response:
                                html = response.read()
                                assert response.status == 200 and b"pywebio" in html.lower()
                            print(f"PASS: Web UI startup and HTTP 200 ({len(html)} bytes)", flush=True)
                            break
                        time.sleep(0.2)
                    else:
                        raise TimeoutError(log_path.read_text())
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
            assert "Application startup failed" not in log_path.read_text()
    assert before == snapshot(root), "Installed tools/environment changed"
    print(f"PASS: {len(before)} installed files/symlinks unchanged; temporary test files removed")


if __name__ == "__main__":
    main()

"""启动本机原生接口和独立 ADB，退出时清理服务。"""
import json
import multiprocessing
from multiprocessing.managers import SyncManager
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from error_logging import install_error_logging

install_error_logging()

from deployment import BRANCH, UPSTREAM, configure_deploy

# 子进程同样使用外部缓存
if os.environ.get("ALAS_DATA_ROOT"):
    from device_cache import configure_device_cache
    configure_device_cache(Path(os.environ["ALAS_DATA_ROOT"]))


def initialize_shared_state(cls):
    # 使用带认证的本机 TCP，避开 Unix 套接字的路径长度限制。
    manager = SyncManager(address=("127.0.0.1", 0),
                          ctx=multiprocessing.get_context("spawn"))
    manager.start()
    cls.manager = manager
    cls._init = True


def route_core_updates(updater, source, private_root):
    def request_update(*args, **kwargs):
        (private_root / "update-request").touch()
        return False

    def check_update():
        updater.state = "checking"
        git = str(private_root / "bootstrap/bin/git")
        try:
            remote = subprocess.check_output(
                [git, "ls-remote", "--exit-code", UPSTREAM, f"refs/heads/{BRANCH}"],
                text=True, timeout=30).split()[0]
            current = subprocess.check_output(
                [git, "-C", str(source), "rev-parse", "HEAD"], text=True, timeout=10).strip()
            return remote != current
        except (OSError, subprocess.SubprocessError, IndexError):
            return False

    # 核心更新统一交给启动器，确保先停服、再验证，失败可回退。
    updater._check_update = check_update
    updater.run_update = request_update
    updater.update = request_update


def listener():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    return sock


def main():
    source, endpoint, private_root = map(Path, sys.argv[1:4])
    os.environ["ALAS_DATA_ROOT"] = str(private_root.resolve())
    from device_cache import configure_device_cache
    configure_device_cache(private_root)
    os.chdir(source)
    sys.path.insert(0, str(source))
    sys.argv = ["gui.py"]
    configure_deploy(source, private_root, Path(sys.executable).parent.parent)
    # 分配独立端口，不占用或关闭用户的 ADB 5037 服务。
    adb_socket = listener()
    adb_port = adb_socket.getsockname()[1]
    adb_socket.close()
    os.environ["ANDROID_ADB_SERVER_PORT"] = str(adb_port)
    os.environ["ADB_SERVER_SOCKET"] = f"tcp:127.0.0.1:{adb_port}"
    adb = Path(os.environ["ALAS_ADB"])
    # ADB 监听参数只接受 tcp:端口；不加 -a，仅监听本机。
    adb_process = subprocess.Popen([str(adb), "-L", f"tcp:{adb_port}", "nodaemon", "server"])
    try:
        deadline = time.monotonic() + 15
        while True:
            if adb_process.poll() is not None:
                raise RuntimeError(f"应用私有 ADB 启动失败：{adb_process.returncode}")
            try:
                with socket.create_connection(("127.0.0.1", adb_port), timeout=0.5) as connection:
                    connection.sendall(b"000chost:version")
                    if connection.recv(4) == b"OKAY":
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("应用私有 ADB 在 15 秒内未就绪")
            time.sleep(0.1)
        import uvicorn
        from module.webui.setting import State
        State.init = classmethod(initialize_shared_state)
        from module.webui.app import app
        from module.webui.updater import updater
        # 将核心更新请求转交启动器。
        route_core_updates(updater, source, private_root)
        sock = listener()
        sock.listen(128)
        port = sock.getsockname()[1]
        from native_api import native_only_application
        application, native_token = native_only_application(app(), source, private_root)
        server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, log_level="info"))

        def publish_ready():
            while not server.started and not server.should_exit:
                time.sleep(0.1)
            if server.started:
                temp = endpoint.with_suffix(".tmp")
                temp.write_text(json.dumps({"url": f"http://127.0.0.1:{port}", "pid": os.getpid(), "token": native_token}))
                temp.chmod(0o600)
                temp.replace(endpoint)

        threading.Thread(target=publish_ready, daemon=True).start()
        server.run(sockets=[sock])
    finally:
        endpoint.unlink(missing_ok=True)
        # 核心可能重启过 ADB，退出时只清理本应用端口。
        try:
            subprocess.run([str(adb), "-P", str(adb_port), "kill-server"], timeout=4,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            pass
        adb_process.terminate()
        try:
            adb_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            adb_process.kill()
            adb_process.wait()


if __name__ == "__main__":
    main()

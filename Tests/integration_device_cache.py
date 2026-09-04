"""用已安装的核心 Python 测试设备缓存，不操作设备或访问外网。"""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

RUNTIME = Path(__file__).resolve().parents[1] / "ALAS for macOS/Runtime"
sys.path.insert(0, str(RUNTIME))


def worker(core, root, url, queue):
    os.chdir(root)
    sys.path.insert(0, core)
    import serve
    from module.device.method import utils
    import uiautomator2.init as initializer
    import uiautomator2cache
    cache = Path(root) / "cache/uiautomator2"
    for _, asset_url in initializer.app_uiautomator_apk_urls():
        copied = Path(initializer.gen_cachepath(asset_url))
        seed = Path(uiautomator2cache.__file__).parent / "cache" / copied.relative_to(cache)
        assert seed.is_file()
        assert copied.read_bytes() == seed.read_bytes()
        assert os.access(copied, os.W_OK), "Copied cache must be writable"
    path = Path(initializer.cache_download(url))
    assert path.read_bytes() == b"device-cache-test"
    assert Path(root) / "cache/uiautomator2" in path.parents
    assert initializer.appdir == str(Path(uiautomator2cache.__file__).parent)
    queue.put(str(path))


def main():
    installed = Path(sys.argv[1]).resolve()
    active = json.loads((installed / "active.json").read_text())
    import uiautomator2cache
    package = Path(uiautomator2cache.__file__).parent
    def snapshot():
        return {str(p): (p.stat().st_mode, p.stat().st_mtime_ns, p.stat().st_size)
                for p in package.rglob("*")}
    before = snapshot()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"device-cache-test"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="alas-device-cache-") as temporary:
            root = str(Path(temporary).resolve())
            os.environ["ALAS_DATA_ROOT"] = root
            os.environ["NO_PROXY"] = "127.0.0.1,localhost"
            context = multiprocessing.get_context("spawn")
            url = "http://127.0.0.1:%s/agent-test.tar.gz" % server.server_port
            queue = context.Queue()
            for attempt in range(2):
                process = context.Process(target=worker, args=(active["repository"], root, url, queue))
                process.start()
                process.join(30)
                if process.is_alive():
                    process.terminate(); process.join()
                    raise TimeoutError("cache worker")
                assert process.exitcode == 0
                path = Path(queue.get(timeout=3))
                if attempt == 0:
                    first_mtime = path.stat().st_mtime_ns
                    server.shutdown()
                else:
                    assert path.stat().st_mtime_ns == first_mtime
            queue.close()
        assert before == snapshot(), "Installed cache changed"
        print("PASS: actual core import, spawned worker download, offline reuse, immutable package unchanged")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

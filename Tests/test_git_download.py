import contextlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

path = Path(__file__).resolve().parents[1] / "ALAS for macOS/Runtime/git_download.py"
spec = importlib.util.spec_from_file_location("git_download", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GitDownloadTests(unittest.TestCase):
    # 无终端时仍转发下载进度
    def test_progress_and_failure(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            module.download([sys.executable, "-c", "import sys; sys.stderr.write('Receiving objects: 50%, 2 MiB/s\\r')"], os.environ)
        self.assertIn("50%, 2 MiB/s\r", output.getvalue())
        with self.assertRaises(subprocess.CalledProcessError):
            module.download([sys.executable, "-c", "raise SystemExit(3)"], os.environ)

    # 无输出时及时终止等待
    def test_idle_timeout(self):
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            module.download([sys.executable, "-c", "import time; time.sleep(20)"],
                            os.environ, idle_timeout=0.3)
        self.assertLess(time.monotonic() - started, 5)

    # 持续输出也限制总时长
    def test_total_timeout(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(TimeoutError):
            module.download([sys.executable, "-u", "-c",
                             "import time\nwhile True: print('progress'); time.sleep(0.05)"],
                            os.environ, idle_timeout=5, total_timeout=0.3)

"""转发 Git 下载进度，限制无输出等待和总下载时长。"""
import codecs
import os
import selectors
import subprocess
import sys
import time


# 超时或退出时回收下载进程。
def download(args, env, idle_timeout=120, total_timeout=900):
    process = subprocess.Popen(list(map(str, args)), env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    started = last_output = time.monotonic()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                now = time.monotonic()
                if now - started > total_timeout or now - last_output > idle_timeout:
                    raise TimeoutError("核心下载超时，已保留仓库，点击重试可复用完整对象")
                if not selector.select(timeout=0.2):
                    continue
                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    break
                last_output = time.monotonic()
                sys.stdout.write(decoder.decode(chunk))
                sys.stdout.flush()
            sys.stdout.write(decoder.decode(b"", final=True))
            sys.stdout.flush()
        process.wait(timeout=5)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, args)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        process.stdout.close()

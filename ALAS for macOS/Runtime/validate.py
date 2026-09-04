"""检查核心依赖，并在 CPU 上逐个运行 OCR 模型。"""
import os
from pathlib import Path
import subprocess
import sys


def main():
    source = Path(sys.argv[1]).resolve()
    os.chdir(source)
    sys.path.insert(0, str(source))
    import av
    import cv2
    import numpy as np
    import scipy
    import mxnet as mx
    import adbutils
    import uiautomator2
    import zerorpc
    import onepush
    from alas import AzurLaneAutoScript
    from module.ocr.models import OCR_MODEL
    assert cv2.resize(np.zeros((8, 8, 3), dtype=np.uint8), (16, 16)).shape == (16, 16, 3)
    assert float(mx.nd.sum(mx.nd.ones((2, 2))).asscalar()) == 4
    for name in ("azur_lane", "azur_lane_jp", "cnocr", "jp", "tw"):
        getattr(OCR_MODEL, name).ocr_for_single_line(np.full((32, 128), 255, dtype=np.uint8))
        print(f"OCR {name}: OK", flush=True)
    subprocess.run([os.environ["ALAS_ADB"], "version"], check=True)
    # 上游界面会替换 PIL 模块，另起进程验证真实依赖。
    subprocess.run([sys.executable, "-c", "from module.webui.app import app; assert callable(app)"], check=True)
    print("完整运行环境验证通过", flush=True)


if __name__ == "__main__":
    main()

"""将设备组件下载到外部缓存，保持 Python 环境只读。"""
from pathlib import Path
import shutil
import uuid


def configure_device_cache(root):
    import uiautomator2.init as initializer
    import uiautomator2cache

    if getattr(initializer.gen_cachepath, "_alas_cache_root", None) == str(root):
        return
    original = initializer.gen_cachepath
    cache = Path(root).resolve() / "cache" / "uiautomator2"
    bundled = Path(uiautomator2cache.__file__).resolve().parent / "cache"

    def writable_cachepath(url):
        relative = Path(original(url)).relative_to(Path(initializer.appdir) / "cache")
        target = cache / relative
        if cache not in target.resolve().parents:
            raise ValueError("设备缓存路径越界")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = bundled / relative
        if not target.exists() and source.is_file() and source.stat().st_size:
            temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                shutil.copyfile(source, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        return str(target)

    writable_cachepath._alas_cache_root = str(root)
    initializer.gen_cachepath = writable_cachepath

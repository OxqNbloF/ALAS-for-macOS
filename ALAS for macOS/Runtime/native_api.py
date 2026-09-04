"""为原生界面提供带令牌认证的本机接口，不改上游源码。"""
import io
import json
from pathlib import Path
import re
import secrets
import threading
from datetime import datetime


class NativeAPI:
    def __init__(self, source, root, token):
        self.source, self.root, self.token = source, root, token
        self.guard = threading.RLock()
        self.configs = {}

    @staticmethod
    def name(value):
        if (not isinstance(value, str) or not value.strip() or len(value.encode()) > 200
                or any(c in value for c in ".\\/:*?\"'<>|") or any(ord(c) < 32 for c in value)
                or value.lower().startswith("template")):
            raise ValueError("配置名不能为空、不能以 template 开头，或包含路径分隔符等非法字符")
        return value

    def known(self, name):
        from module.config.utils import alas_instance
        self.name(name)
        if name not in alas_instance():
            raise ValueError("配置不存在，请刷新列表")
        return name

    @staticmethod
    def translate(key, language):
        from module.webui.lang import dic_lang
        return dic_lang.get(language, {}).get(key, dic_lang.get("en-US", {}).get(key, key))

    def context(self, name):
        from module.submodule.utils import get_config_mod
        from module.submodule.submodule import load_config
        from module.webui.setting import State
        from module.config.utils import filepath_args
        mod = get_config_mod(name)
        updater = State.config_updater if mod == "alas" else load_config(name)
        args = json.loads(Path(filepath_args("args", mod)).read_text())
        menu = json.loads(Path(filepath_args("menu", mod)).read_text())
        return mod, updater, args, menu

    def catalog(self, name, language):
        from module.config.deep import deep_get
        from module.config.server import to_server
        self.known(name)
        mod, updater, args, menu = self.context(name)
        config = updater.read_file(name)
        server = to_server(deep_get(config, "Alas.Emulator.PackageName", "cn"))
        t = lambda key: self.translate(key, language)
        sections = []
        for menu_id, meta in menu.items():
            tasks = []
            for task_id in meta.get("tasks", []):
                groups = []
                for group_id, fields in args.get(task_id, {}).items():
                    output = []
                    for field_id, spec in fields.items():
                        if spec.get("display") == "hide":
                            continue
                        key = f"{task_id}.{group_id}.{field_id}"
                        options = spec.get(f"option_{server}") or spec.get("option", [])
                        value = deep_get(config, key, spec.get("value"))
                        # 与上游一致：空记录不生成控件，空分组也跳过。
                        if spec["type"] == "storage" and value == {}:
                            continue
                        output.append({"id": key, "title": t(f"{group_id}.{field_id}.name"),
                            "help": t(f"{group_id}.{field_id}.help"), "kind": spec["type"],
                            "value": value, "defaultValue": spec.get("value"),
                            "readOnly": spec.get("display") == "disabled" or spec["type"] in ("lock", "state", "storage", "stored"),
                            "options": [{"value": v, "title": t(f"{group_id}.{field_id}.{v}")} for v in options]})
                    if output:
                        groups.append({"id": group_id, "title": t(f"{group_id}._info.name"), "fields": output})
                tasks.append({"id": task_id, "title": t(f"Task.{task_id}.name"),
                    "help": t(f"Task.{task_id}.help"), "tool": meta.get("page") == "tool", "groups": groups})
            sections.append({"id": menu_id, "title": t(f"Menu.{menu_id}.name"), "tasks": tasks})
        return {"name": name, "mod": mod, "sections": sections}

    def commit(self, name, data, mod):
        from module.config.config_updater import ConfigUpdater
        from module.config.utils import filepath_config
        ConfigUpdater.write_file(name, data, mod)
        # 核心写入可能替换符号链接，及时将配置迁回数据目录并重新关联。
        path = Path(filepath_config(name, mod))
        target = self.root / "data/config" / path.name
        if path.resolve() != target.resolve():
            temporary = target.with_suffix(".native-tmp")
            temporary.write_bytes(path.read_bytes())
            temporary.replace(target)
            path.unlink()
            path.symlink_to(target)

    def save(self, body):
        from module.config.deep import deep_get, deep_set
        from module.webui.utils import parse_pin_value, re_fullmatch
        name = self.known(body.get("name"))
        mod, updater, args, _ = self.context(name)
        data = updater.read_file(name)
        changes = body.get("changes", [])
        if not isinstance(changes, list) or len(changes) > 2000:
            raise ValueError("配置修改格式错误")
        for change in changes:
            key = change["id"]
            spec = deep_get(args, key)
            clearing_storage = isinstance(spec, dict) and spec.get("type") == "storage" and change.get("value") == {}
            if not isinstance(spec, dict) or (not clearing_storage and (spec.get("display") in ("hide", "disabled") or spec.get("type") in ("lock", "state", "storage", "stored"))):
                raise ValueError(f"不可修改字段：{key}")
            original = json.loads(json.dumps(deep_get(data, key), default=str))
            if original != change.get("original"):
                raise ValueError(f"{key} 已被核心或另一窗口修改，请重新载入后再保存")
            raw = change.get("value")
            if raw is None or raw == "":
                value = spec.get("value")
            elif spec["type"] == "checkbox":
                if not isinstance(raw, bool):
                    raise ValueError("开关值必须为布尔值")
                value = raw
            else:
                value = parse_pin_value(raw, spec.get("valuetype"))
            pattern = spec.get("validate")
            if pattern and value is not None and not re_fullmatch(pattern, str(value)):
                raise ValueError(f"字段格式不正确：{key}")
            if spec["type"] == "select":
                options = list(spec.get("option", []))
                for option_key, values in spec.items():
                    if option_key.startswith("option_") and isinstance(values, list):
                        options.extend(values)
                if options and value not in options:
                    raise ValueError(f"选项无效：{key}")
            deep_set(data, key, value)
            for changed_key, changed_value in updater.save_callback(key, value):
                deep_set(data, changed_key, changed_value)
        self.commit(name, data, mod)
        return {"ok": True}

    def snapshot(self, name, language):
        from module.config.utils import alas_instance, alas_template
        from module.submodule.utils import get_config_mod
        from module.webui.process_manager import ProcessManager
        from module.webui.remote_access import RemoteAccess
        from module.webui.setting import State
        from rich.console import Console
        profiles = [{"id": n, "mod": get_config_mod(n), "state": ProcessManager.get_manager(n).state}
                    for n in alas_instance()]
        result = {"profiles": profiles, "templates": alas_template(), "schedule": [], "logs": "",
                  "revision": json.loads((self.root / "active.json").read_text()).get("revision", ""),
                  "remoteState": RemoteAccess.get_state(), "remoteAddress": RemoteAccess.get_entry_point() or "",
                  "remoteEnabled": bool(State.deploy_config.EnableRemoteAccess)}
        if not name:
            return result
        self.known(name)
        pm = ProcessManager.get_manager(name)
        from module.submodule.submodule import load_config
        config = self.configs.get(name)
        if config is None:
            config = self.configs[name] = load_config(name)
        config.load()
        config.get_next_task()
        for i, task in enumerate(config.pending_task):
            result["schedule"].append({"id": task.command, "title": self.translate(f"Task.{task.command}.name", language),
                "nextRun": str(task.next_run), "state": "running" if i == 0 and pm.alive else "pending"})
        for task in config.waiting_task:
            result["schedule"].append({"id": task.command, "title": self.translate(f"Task.{task.command}.name", language),
                "nextRun": str(task.next_run), "state": "waiting"})
        output = io.StringIO()
        console = Console(file=output, width=120, no_color=True, force_terminal=False)
        for item in list(pm.renderables)[-200:]:
            console.print(item)
        result["logs"] = output.getvalue()[-150000:]
        return result

    def action(self, body):
        from module.webui.process_manager import ProcessManager
        from module.webui.updater import updater
        from module.submodule.utils import get_available_func, get_available_mod_func, get_config_mod, get_func_mod
        name = self.known(body.get("name"))
        manager = ProcessManager.get_manager(name)
        if body.get("action") == "stop":
            manager.stop()
        elif body.get("action") == "start":
            func = body.get("function")
            if func is not None and func not in get_available_func() and func not in get_available_mod_func():
                raise ValueError("未知工具")
            if func in get_available_mod_func() and get_func_mod(func) != get_config_mod(name):
                raise ValueError("工具与配置类型不匹配")
            if manager.alive:
                raise ValueError("配置正在运行，请先停止当前任务")
            manager.start(func, updater.event)
        else:
            raise ValueError("未知操作")
        return {"ok": True}

    def create(self, body):
        from module.config.utils import alas_instance, alas_template
        from module.submodule.utils import get_config_mod
        from module.webui.setting import State
        from module.submodule.submodule import load_config
        name = self.name(body.get("name"))
        if name in alas_instance():
            raise ValueError("配置名称已存在")
        origin = body.get("origin", "template-alas")
        if origin not in alas_instance() + alas_template():
            raise ValueError("复制来源不存在")
        mod = get_config_mod(origin)
        updater = State.config_updater if mod == "alas" else load_config(origin)
        data = updater.read_file("template" if origin == "template-alas" else origin)
        self.commit(name, data, mod)
        return {"ok": True}

    def delete(self, body):
        from module.config.utils import filepath_config
        from module.submodule.utils import get_config_mod
        from module.webui.process_manager import ProcessManager
        name = self.known(body.get("name"))
        if body.get("confirm") is not True:
            raise ValueError("删除配置需要确认")
        if ProcessManager.get_manager(name).alive:
            raise ValueError("请先停止该配置再删除")
        path = Path(filepath_config(name, get_config_mod(name)))
        target = self.root / "data/config" / path.name
        # 不读取指向应用配置目录之外的链接。
        if path.is_symlink() and path.resolve() != target.resolve():
            raise ValueError("配置路径异常，未删除")
        if target.is_symlink():
            raise ValueError("配置路径异常，未删除")
        path.unlink()
        if target != path and target.exists():
            target.unlink()
        self.configs.pop(name, None)
        ProcessManager._processes.pop(name, None)
        return {"ok": True}

    def transfer(self, body):
        from module.config.utils import filepath_config, alas_instance
        from module.submodule.utils import get_config_mod, get_available_mod
        name = self.name(body.get("name"))
        if body.get("action") == "export":
            self.known(name)
            mod = get_config_mod(name)
            path = Path(filepath_config(name, mod))
            return {"filename": path.name, "content": path.read_text()}
        if body.get("action") != "import":
            raise ValueError("未知传输操作")
        mod = body.get("mod", "alas")
        if mod != "alas" and mod not in get_available_mod():
            raise ValueError("未知配置类型")
        content = body.get("content", "")
        if len(content.encode()) > 1024 * 1024:
            raise ValueError("配置文件超过 1 MB")
        data = json.loads(content)
        if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
            raise ValueError("配置文件不是有效的 ALAS 配置对象")
        if name in alas_instance():
            if not body.get("overwrite"):
                raise ValueError("配置已存在，需要明确确认覆盖")
            from module.webui.process_manager import ProcessManager
            if ProcessManager.get_manager(name).alive:
                raise ValueError("请先停止该配置再导入")
            if get_config_mod(name) != mod:
                raise ValueError("不能覆盖不同类型的配置")
        self.commit(name, data, mod)
        self.configs.pop(name, None)
        return {"ok": True}

    def dispatch(self, operation, body, query):
        with self.guard:
            if operation == "ui-preferences":
                path = self.root / "native-ui.json"
                return json.loads(path.read_text()) if path.is_file() else {"language": "zh-CN", "appearance": "system"}
            if operation == "save-preferences":
                from runtime import atomic_json
                if body.get("language") not in ("zh-CN", "zh-TW", "en-US", "ja-JP") or body.get("appearance") not in ("system", "light", "dark"):
                    raise ValueError("未知界面设置")
                atomic_json(self.root / "native-ui.json", {"language": body["language"], "appearance": body["appearance"]})
                return {"ok": True}
            if operation == "snapshot":
                return self.snapshot(query.get("name", ""), query.get("language", "zh-CN"))
            if operation == "catalog":
                return self.catalog(query.get("name"), query.get("language", "zh-CN"))
            if operation == "save":
                return self.save(body)
            if operation == "action":
                return self.action(body)
            if operation == "create":
                return self.create(body)
            if operation == "transfer":
                return self.transfer(body)
            if operation == "delete":
                return self.delete(body)
            if operation == "check-update":
                import subprocess
                from deployment import UPSTREAM, BRANCH
                git = str(self.root / "bootstrap/bin/git")
                output = subprocess.check_output([git, "ls-remote", "--exit-code", UPSTREAM,
                    f"refs/heads/{BRANCH}"], text=True, timeout=30)
                return {"revision": output.split()[0]}
            if operation == "diagnostic":
                raise ValueError("原生诊断测试：错误信息已正常传递，核心服务未被中断。")
            raise ValueError("未知接口")

    async def handle(self, request):
        from starlette.responses import JSONResponse
        from starlette.concurrency import run_in_threadpool
        if request.headers.get("origin") or not secrets.compare_digest(
                request.headers.get("authorization", ""), "Bearer " + self.token):
            return JSONResponse({"error": "未授权"}, status_code=401)
        operation = request.path_params["operation"]
        read_only = operation in ("snapshot", "catalog", "check-update", "ui-preferences")
        if request.method != ("GET" if read_only else "POST"):
            return JSONResponse({"error": "请求方法不允许"}, status_code=405)
        try:
            data = b""
            async for chunk in request.stream():
                data += chunk
                if len(data) > 2 * 1024 * 1024:
                    raise ValueError("请求过大")
            body = json.loads(data) if data else {}
            if not isinstance(body, dict):
                raise ValueError("请求格式错误")
            result = await run_in_threadpool(self.dispatch, operation, body, request.query_params)
            return JSONResponse(json.loads(json.dumps(result, default=str)), headers={"Cache-Control": "no-store"})
        except Exception as error:
            return JSONResponse({"error": str(error)}, status_code=400)


def install_native_api(app, source, root):
    from starlette.routing import Route
    token = secrets.token_urlsafe(32)
    api = NativeAPI(source, root, token)
    app.router.routes.insert(0, Route("/native/{operation}", api.handle, methods=["GET", "POST"]))
    return token


def native_only_application(core_app, source, root):
    """复用核心生命周期回调，不挂载上游网页和中间件。"""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(request):
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    app = Starlette(debug=False, routes=[Route("/", health)],
                    on_startup=list(core_app.router.on_startup),
                    on_shutdown=list(core_app.router.on_shutdown))
    token = install_native_api(app, source, root)
    return app, token

"""在临时核心工作树中测试原生接口，不启动游戏任务。

用法：ENGINE_PYTHON -B Tests/integration_native_api.py BUILD_RESOURCES INSTALLED_DATA
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
import urllib.error


def main():
    resources, installed = map(lambda s: Path(s).resolve(), sys.argv[1:3])
    if not str(resources).startswith("/private/tmp/alas-"):
        raise ValueError("Use a disposable built App only")
    sys.path.insert(0, str(resources / "Runtime"))
    import runtime
    active = json.loads((installed / "active.json").read_text())
    prefix = Path(active["environment"])
    with tempfile.TemporaryDirectory(prefix="alas-native-api-") as temporary:
        root = Path(temporary) / ("long-external-data-path-" * 4)
        for folder in ("tmp", "home", "cache", "data/config", "tools", "bootstrap/bin"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        source = root / "core"
        subprocess.run([str(installed / "bootstrap/bin/git"), "clone", "--no-local", "--depth", "1",
                        "--no-recurse-submodules", active["repository"], str(source)], check=True)
        (root / "bootstrap/bin/git").symlink_to(installed / "bootstrap/bin/git")
        (root / "tools/platform-tools").symlink_to(installed / "tools/platform-tools")
        (root / "active.json").write_text(json.dumps(dict(active, repository=str(source))))
        endpoint = root / "endpoint.json"
        log_path = root / "service.log"
        with log_path.open("w") as log:
            process = subprocess.Popen([str(prefix / "bin/python"), "-B", str(resources / "Runtime/serve.py"),
                str(source), str(endpoint), str(root)], env=runtime.environment(root, prefix),
                stdout=log, stderr=log, start_new_session=True)
            try:
                deadline = time.monotonic() + 60
                while not endpoint.is_file():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError(log_path.read_text())
                    time.sleep(0.2)
                ready = json.loads(endpoint.read_text())
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                def call(operation, body=None, query="", auth=True, origin=None, expected=200):
                    headers = {"Content-Type": "application/json"}
                    if auth: headers["Authorization"] = "Bearer " + ready["token"]
                    if origin: headers["Origin"] = origin
                    req = urllib.request.Request(ready["url"] + "/native/" + operation + query,
                        data=json.dumps(body).encode() if body is not None else None, headers=headers)
                    try:
                        with opener.open(req, timeout=15) as response:
                            code, data = response.status, json.loads(response.read())
                    except urllib.error.HTTPError as error:
                        code, data = error.code, json.loads(error.read())
                    assert code == expected, (operation, code, data)
                    return data
                call("snapshot", auth=False, expected=401)
                call("snapshot", origin="http://untrusted.invalid", expected=401)
                call("save", expected=405)
                assert call("ui-preferences")["appearance"] == "system"
                call("save-preferences", {"language": "zh-CN", "appearance": "dark"})
                assert call("ui-preferences")["appearance"] == "dark"
                call("create", {"name": "../escape", "origin": "template-alas"}, expected=400)
                call("create", {"name": "native_test", "origin": "template-alas"})
                catalog = call("catalog", query="?name=native_test&language=zh-CN")
                tasks = [task for section in catalog["sections"] for task in section["tasks"]]
                fields = [field for task in tasks for group in task["groups"] for field in group["fields"]]
                schema = json.loads((source / "module/config/argument/args.json").read_text())
                expected_fields = {f"{t}.{g}.{f}" for t, groups in schema.items() for g, args in groups.items()
                    for f, spec in args.items() if spec.get("display") != "hide"
                    and not (spec["type"] == "storage" and spec.get("value") == {})}
                assert {f["id"] for f in fields} == expected_fields
                assert len(tasks) == 68, len(tasks)
                assert {t["id"] for t in tasks if t["tool"]} == {"Daemon", "OpsiDaemon", "EventStory",
                    "IslandProductionPlanner", "Benchmark", "AzurLaneUncensored", "GameManager"}
                edits = []
                for key, value in [("Alas.Emulator.Serial", "native-test-device"), ("Main.Scheduler.Enable", False),
                                   ("Main.Scheduler.NextRun", "2026-09-05 10:20:30")]:
                    field = next(f for f in fields if f["id"] == key)
                    edits.append({"id": key, "value": value, "original": field["value"]})
                call("save", {"name": "native_test", "changes": edits})
                call("save", {"name": "native_test", "changes": edits}, expected=400)
                call("save", {"name": "native_test", "changes": [{"id": "bogus", "value": True}]}, expected=400)
                exported = call("transfer", {"action": "export", "name": "native_test"})
                saved = json.loads(exported["content"])
                assert saved["Alas"]["Emulator"]["Serial"] == "native-test-device"
                assert saved["Main"]["Scheduler"]["NextRun"] == "2026-09-05 10:20:30"
                assert (source / "config/native_test.json").is_symlink()
                saved["Alas"]["Storage"]["Storage"] = {"native_test": 1}
                call("transfer", {"action": "import", "name": "native_test", "content": json.dumps(saved), "overwrite": True})
                populated = call("catalog", query="?name=native_test&language=zh-CN")
                stored_fields = [f for s in populated["sections"] for t in s["tasks"] for g in t["groups"]
                                 for f in g["fields"] if f["kind"] == "storage"]
                assert len(stored_fields) == 1 and stored_fields[0]["value"] == {"native_test": 1}
                call("save", {"name": "native_test", "changes": [{"id": "Alas.Storage.Storage",
                    "original": {"native_test": 1}, "value": {}}]})
                cleared = call("transfer", {"action": "export", "name": "native_test"})
                assert json.loads(cleared["content"])["Alas"]["Storage"]["Storage"] == {}
                empty = call("catalog", query="?name=native_test&language=zh-CN")
                assert not any(f["kind"] == "storage" for s in empty["sections"] for t in s["tasks"]
                               for g in t["groups"] for f in g["fields"])
                call("transfer", {"action": "import", "name": "native_import", "content": exported["content"]})
                call("transfer", {"action": "import", "name": "native_import", "content": exported["content"]}, expected=400)
                snapshot = call("snapshot", query="?name=native_test&language=zh-CN")
                assert {p["id"] for p in snapshot["profiles"]} >= {"native_test", "native_import"}
                call("action", {"name": "native_test", "action": "start", "function": "invalid"}, expected=400)
                call("action", {"name": "native_test", "action": "stop"})
                call("diagnostic", {}, expected=400)
                print(f"PASS: {len(tasks)} native task pages, {len(fields)} visible fields, seven tools; authenticated HTTP, save/conflict, import/export, schedule/logs and validation")
                (root / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False))
            finally:
                process.terminate()
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
            if "Application startup failed" in log_path.read_text():
                raise RuntimeError(log_path.read_text())


if __name__ == "__main__":
    main()

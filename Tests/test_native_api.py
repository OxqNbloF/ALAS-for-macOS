import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

RUNTIME = Path(__file__).resolve().parents[1] / "ALAS for macOS/Runtime"
spec = importlib.util.spec_from_file_location("native_api", RUNTIME / "native_api.py")
native_api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native_api)


class NativeAPITests(unittest.TestCase):
    def test_delete_requires_confirmation_stopped_process_and_safe_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            durable = root / "data/config"
            durable.mkdir(parents=True)
            source = root / "core"
            source.mkdir()
            target = durable / "test.json"
            target.write_text("{}")
            link = source / "test.json"
            link.symlink_to(target)
            manager = SimpleNamespace(alive=False)
            pm = SimpleNamespace(get_manager=lambda _: manager, _processes={"test": manager})
            modules = {
                "module.config.utils": SimpleNamespace(filepath_config=lambda *_: str(link)),
                "module.submodule.utils": SimpleNamespace(get_config_mod=lambda _: "alas"),
                "module.webui.process_manager": SimpleNamespace(ProcessManager=pm),
            }
            api = native_api.NativeAPI(source, root, "test")
            api.configs["test"] = object()
            with patch.dict(sys.modules, modules), patch.object(api, "known", return_value="test"):
                with self.assertRaises(ValueError): api.delete({"name": "test"})
                manager.alive = True
                with self.assertRaises(ValueError): api.delete({"name": "test", "confirm": True})
                manager.alive = False
                outside = root / "unrelated.json"
                outside.write_text("keep")
                link.unlink()
                link.symlink_to(outside)
                with self.assertRaises(ValueError): api.delete({"name": "test", "confirm": True})
                self.assertEqual(outside.read_text(), "keep")
                link.unlink()
                link.symlink_to(target)
                self.assertEqual(api.delete({"name": "test", "confirm": True}), {"ok": True})
                self.assertFalse(link.is_symlink())
                self.assertFalse(target.exists())
                self.assertNotIn("test", api.configs)
                self.assertNotIn("test", pm._processes)

    def test_catalog_hides_empty_storage_and_restores_nonempty_records(self):
        def deep_get(data, key, default=None):
            for part in key.split("."):
                if not isinstance(data, dict) or part not in data:
                    return default
                data = data[part]
            return data
        args = {"Main": {
            "Settings": {"Enable": {"type": "checkbox", "value": True}},
            "Storage": {"Storage": {"type": "storage", "value": {}, "display": "disabled"}},
        }}
        data = {"Main": {"Storage": {"Storage": {}}}}
        updater = SimpleNamespace(read_file=lambda _: data)
        api = native_api.NativeAPI(Path("."), Path("."), "test")
        modules = {
            "module.config.deep": SimpleNamespace(deep_get=deep_get),
            "module.config.server": SimpleNamespace(to_server=lambda _: "cn"),
        }
        with patch.dict(sys.modules, modules), patch.object(api, "known"), patch.object(
                api, "context", return_value=("alas", updater, args, {"Farm": {"tasks": ["Main"]}})), patch.object(
                api, "translate", side_effect=lambda key, _: key):
            for record in ({}, {"progress": 1}, {}):
                data["Main"]["Storage"]["Storage"] = record
                groups = api.catalog("alas", "zh-CN")["sections"][0]["tasks"][0]["groups"]
                self.assertEqual([g["id"] for g in groups], ["Settings", "Storage"] if record else ["Settings"])
                if record:
                    self.assertEqual(groups[1]["fields"][0]["value"], record)
                    self.assertTrue(groups[1]["fields"][0]["readOnly"])
                self.assertEqual(data["Main"]["Storage"]["Storage"], record)

    def test_names_preserve_upstream_legal_names_and_reject_paths(self):
        for name in ("alas", "配置一", "配置(备用)", "my-alas_2"):
            self.assertEqual(native_api.NativeAPI.name(name), name)
        for name in ("", "  ", "../escape", "template-alas", "a/b", "a\\b", "a.json", "a\n"):
            with self.assertRaises(ValueError): native_api.NativeAPI.name(name)

    def test_control_delegates_to_core_process_manager_without_reimplementation(self):
        manager = Mock(alive=False)
        event = object()
        pm = SimpleNamespace(get_manager=Mock(return_value=manager))
        modules = {
            "module.config.utils": SimpleNamespace(alas_instance=lambda: ["alas"]),
            "module.webui.process_manager": SimpleNamespace(ProcessManager=pm),
            "module.webui.updater": SimpleNamespace(updater=SimpleNamespace(event=event)),
            "module.submodule.utils": SimpleNamespace(get_available_func=lambda: ("Benchmark",),
                get_available_mod_func=lambda: (), get_config_mod=lambda _: "alas", get_func_mod=lambda _: None),
        }
        api = native_api.NativeAPI(Path("."), Path("."), "test")
        with patch.dict(sys.modules, modules):
            api.action({"name": "alas", "action": "start"})
            manager.start.assert_called_once_with(None, event)
            manager.start.reset_mock()
            api.action({"name": "alas", "action": "start", "function": "Benchmark"})
            manager.start.assert_called_once_with("Benchmark", event)
            api.action({"name": "alas", "action": "stop"})
            manager.stop.assert_called_once_with()
            with self.assertRaises(ValueError): api.action({"name": "alas", "action": "start", "function": "exec"})
            manager.alive = True
            with self.assertRaises(ValueError): api.action({"name": "alas", "action": "start"})


if __name__ == "__main__":
    unittest.main()

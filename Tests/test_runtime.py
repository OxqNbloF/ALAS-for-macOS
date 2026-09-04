import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
import subprocess
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "ALAS for macOS/Runtime"
sys.path.insert(0, str(RUNTIME))
import deployment
import serve
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location("runtime", RUNTIME / "runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
REAL_FREEZE_ENVIRONMENT = runtime.freeze_environment


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="alas-runtime-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        adb = patch.object(runtime, "install_adb")
        self.adb = adb.start()
        self.addCleanup(adb.stop)
        freeze = patch.object(runtime, "freeze_environment")
        self.freeze = freeze.start()
        self.addCleanup(freeze.stop)
        for name in ("finish_core_update", "abort_core_update", "checkout_core", "compact_core"):
            mocked = patch.object(runtime, name)
            mocked.start()
            self.addCleanup(mocked.stop)
        revision = patch.object(runtime, "git_revision", return_value=None)
        revision.start()
        self.addCleanup(revision.stop)
        for folder in ("data/config", "tmp", "environments"):
            (self.root / folder).mkdir(parents=True)

    def source(self, name="core"):
        source = self.root / name
        (source / "config").mkdir(parents=True)
        (source / "config/template.json").write_text('{"template": 1}')
        (source / "config/alas.json").write_text('{"user": 1}')
        (source / "gui.py").touch()
        return source

    def test_web_update_check_never_fetches_and_install_is_routed(self):
        updater = SimpleNamespace(state=0)
        source = self.source()
        serve.route_core_updates(updater, source, self.root)
        with patch.object(serve.subprocess, "check_output", side_effect=["new\trefs/heads/master", "old\n"]) as run:
            self.assertTrue(updater._check_update())
        self.assertEqual(run.call_args_list[0].args[0][1], "ls-remote")
        self.assertEqual(run.call_args_list[1].args[0][-2:], ["rev-parse", "HEAD"])
        self.assertFalse(updater.run_update())
        self.assertTrue((self.root / "update-request").is_file())
        (self.root / "update-request").unlink()
        self.assertFalse(updater.update())
        self.assertTrue((self.root / "update-request").is_file())

    def test_shared_manager_uses_loopback_tcp_and_spawn(self):
        state = SimpleNamespace(_init=False)
        with patch.object(serve, "SyncManager") as manager:
            serve.initialize_shared_state(state)
        self.assertEqual(manager.call_args.kwargs["address"], ("127.0.0.1", 0))
        self.assertEqual(manager.call_args.kwargs["ctx"].get_start_method(), "spawn")
        manager.return_value.start.assert_called_once_with()
        self.assertIs(state.manager, manager.return_value)
        self.assertTrue(state._init)

    def installed(self):
        source = self.source("old")
        prefix = self.root / "environments/fixed"
        (prefix / "bin").mkdir(parents=True)
        (prefix / "bin/python").touch(mode=0o700)
        (prefix / ".complete").touch()
        adb = self.root / "tools/platform-tools/adb"
        adb.parent.mkdir(parents=True)
        adb.touch(mode=0o700)
        active = {"repository": str(source), "environment": str(prefix), "revision": "old"}
        runtime.atomic_json(self.root / "active.json", active)
        return active, prefix

    def test_reference_keeps_full_engine_without_browser_stack(self):
        conda, pip = runtime.specification(self.root)
        deps = conda["dependencies"]
        self.assertIn("python=3.8.19", deps)
        self.assertIn(runtime.CONDA_MAIN + "::py-mxnet=1.5.1", deps)
        self.assertIn("av=10.0.0", deps)
        self.assertFalse(any("qt" in item for item in deps))
        self.assertIn("cnocr==1.2.3", pip)
        self.assertIn("uiautomator2==2.16.17", pip)
        self.assertIn("opencv=4.6.0", deps)

    def test_child_environment_ignores_external_python_and_pip(self):
        with patch.dict(runtime.os.environ, {"PYTHONPATH": "/unsafe", "PIP_INDEX_URL": "http://unsafe", "DYLD_LIBRARY_PATH": "/unsafe"}):
            env = runtime.environment(self.root)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PIP_INDEX_URL", env)
        self.assertNotIn("DYLD_LIBRARY_PATH", env)
        self.assertEqual(env["HOME"], str(self.root / "home"))
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")

    def test_saved_environment_must_remain_inside_current_app_root(self):
        outside = self.root.parent / "another-app/environments/fixed"
        runtime.atomic_json(self.root / "environment.json", {
            "environment": str(outside), "locked": True})
        with self.assertRaisesRegex(RuntimeError, "不在当前数据目录内"):
            runtime.saved_environment(self.root)

    def test_configs_persist_and_templates_remain_release_local(self):
        first = self.source()
        runtime.attach_data(self.root, first)
        (first / "config/alas.json").write_text('{"user": 2}')
        # 模拟核心原子替换配置链接并新建配置。
        (first / "config/new.json").write_text('{"new": 1}')
        runtime.preserve_configs(self.root, first)
        second = self.source("new")
        (second / "config/template.json").write_text('{"template": 3}')
        runtime.attach_data(self.root, second)
        self.assertEqual(json.loads((second / "config/alas.json").read_text())["user"], 2)
        self.assertTrue((second / "config/new.json").is_symlink())
        self.assertEqual(json.loads((second / "config/template.json").read_text())["template"], 3)
        self.assertEqual(json.loads((first / "config/template.json").read_text())["template"], 1)

    def test_incompatible_code_never_promotes_or_changes_environment(self):
        active, prefix = self.installed()
        candidate = self.source("new")
        with patch.object(runtime, "run", return_value="new\trefs/heads/master"), patch.object(
                runtime, "begin_core_update", return_value=("old", "new")), patch.object(
                runtime, "install_environment") as install, patch.object(
                runtime, "validate", side_effect=RuntimeError("OCR failed")):
            with self.assertRaisesRegex(RuntimeError, "OCR failed"):
                runtime.prepare(self.root)
        install.assert_not_called()
        self.adb.assert_not_called()
        self.assertEqual(json.loads((self.root / "active.json").read_text()), active)

    def test_first_install_promotes_only_validated_pair(self):
        candidate = self.source()
        order = []
        self.adb.side_effect = lambda root: order.append("adb")
        def clone(root):
            order.append("clone")
            return candidate, "new"
        def install(root, source):
            order.append("environment")
            return self.root / "engine"
        with patch.object(runtime, "install_remote_core", side_effect=clone), patch.object(
                runtime, "refresh_initial_core", side_effect=lambda root, source, revision: (source, revision)), patch.object(
                runtime, "install_environment", side_effect=install):
            runtime.prepare(self.root)
        active = json.loads((self.root / "active.json").read_text())
        self.assertEqual(order, ["adb", "clone", "environment"])
        self.assertEqual(active["environment"], str(self.root / "engine"))
        self.assertEqual(active["revision"], "new")
        self.assertEqual(json.loads((self.root / "environment.json").read_text())["environment"], active["environment"])
        self.assertTrue(Path(active["repository"]).is_dir())
        self.assertTrue((candidate / "config/deploy.yaml").is_file())

    def test_warm_start_checks_only_remote_when_unchanged(self):
        active, prefix = self.installed()
        before = (prefix / "bin/python").stat().st_mtime_ns
        with patch.object(runtime, "run", return_value="old\trefs/heads/master") as run, patch.object(
                runtime, "install_environment") as install, patch.object(runtime, "validate") as validate:
            runtime.prepare(self.root)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][1], "ls-remote")
        self.assertIn("https://github.com/LmeSzinc/AzurLaneAutoScript.git", run.call_args.args[0])
        install.assert_not_called()
        validate.assert_not_called()
        self.adb.assert_not_called()
        self.assertEqual(before, (prefix / "bin/python").stat().st_mtime_ns)
        self.assertEqual(json.loads((self.root / "active.json").read_text()), active)

    def test_code_update_reuses_fixed_environment_even_with_new_requirements(self):
        active, prefix = self.installed()
        candidate = Path(active["repository"])
        (candidate / "requirements.txt").write_text("brand-new-dependency==99")
        with patch.object(runtime, "run", return_value="new\trefs/heads/master"), patch.object(
                runtime, "begin_core_update", return_value=("old", "new")), patch.object(
                runtime, "install_environment") as install, patch.object(runtime, "fingerprint") as fingerprint, patch.object(
                runtime, "validate") as validate:
            runtime.prepare(self.root)
        validate.assert_called_once_with(self.root, candidate, prefix)
        install.assert_not_called()
        fingerprint.assert_not_called()
        self.adb.assert_not_called()
        new = json.loads((self.root / "active.json").read_text())
        self.assertEqual(new["environment"], active["environment"])
        self.assertEqual(new["revision"], "new")
        self.assertEqual(json.loads((self.root / "previous.json").read_text()), active)

    def test_offline_keeps_active_record_and_never_installs(self):
        active, prefix = self.installed()
        with patch.object(runtime, "run", side_effect=OSError("offline")), patch.object(
                runtime, "install_environment") as install:
            with self.assertRaisesRegex(OSError, "offline"):
                runtime.prepare(self.root)
        install.assert_not_called()
        self.adb.assert_not_called()
        self.assertEqual(json.loads((self.root / "active.json").read_text()), active)

    def test_missing_adb_or_python_does_not_trigger_reinstallation(self):
        active, prefix = self.installed()
        (self.root / "tools/platform-tools/adb").unlink()
        with patch.object(runtime, "install_environment") as install:
            with self.assertRaisesRegex(RuntimeError, "ADB 缺失"):
                runtime.prepare(self.root)
            (prefix / "bin/python").unlink()
            with self.assertRaisesRegex(RuntimeError, "运行环境损坏"):
                runtime.prepare(self.root)
        install.assert_not_called()
        self.adb.assert_not_called()

    def test_bootstrap_warm_start_skips_missing_manager(self):
        self.installed()
        bootstrap = self.root / "bootstrap"
        (bootstrap / "bin").mkdir(parents=True)
        (bootstrap / ".complete").touch()
        for name in ("python", "git"):
            executable = bootstrap / "bin" / name
            executable.write_text("#!/bin/sh\nprintf 'reused-private-tool\\n'\n")
            executable.chmod(0o700)
        result = subprocess.run(["/bin/bash", str(RUNTIME / "bootstrap.sh"), "prepare", str(self.root)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reused-private-tool", result.stdout)
        self.assertFalse((self.root / "bin/micromamba").exists())
        (bootstrap / "bin/git").unlink()
        result = subprocess.run(["/bin/bash", str(RUNTIME / "bootstrap.sh"), "prepare", str(self.root)],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不会自动重建环境", result.stdout)

    def test_install_function_rejects_already_saved_environment(self):
        self.installed()
        with patch.object(runtime, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "禁止自动重装"):
                runtime.install_environment(self.root, self.root / "old")
        run.assert_not_called()

    def test_cache_cleanup_keeps_fixed_environment_core_and_tools(self):
        active, prefix = self.installed()
        runtime.atomic_json(self.root / "environment.json", {
            "environment": str(prefix), "locked": True, "cacheCleaned": False})
        for name in ("cache/pip/download", "tmp/archive.zip", "mamba/pkgs/index"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("cache")
        tool = self.root / "tools/platform-tools/adb"
        core = Path(active["repository"]) / "gui.py"
        runtime.clean_download_cache(self.root)
        self.assertTrue(tool.exists())
        self.assertTrue(core.exists())
        self.assertTrue((prefix / ".complete").exists())
        self.assertFalse((self.root / "mamba").exists())
        self.assertEqual(list((self.root / "cache").iterdir()), [])
        self.assertEqual(list((self.root / "tmp").iterdir()), [])
        state = json.loads((self.root / "environment.json").read_text())
        self.assertTrue(state["locked"] and state["cacheCleaned"])

    def test_fixed_environment_removes_write_permissions(self):
        _, prefix = self.installed()
        bootstrap = self.root / "bootstrap/bin"
        bootstrap.mkdir(parents=True)
        (bootstrap / "git").touch(mode=0o700)
        runtime.atomic_json(self.root / "environment.json", {
            "environment": str(prefix), "locked": False, "frozen": False,
            "cacheCleaned": False})
        targets = [self.root / "bootstrap", self.root / "tools", prefix]
        def restore_permissions():
            for target in targets:
                if target.exists():
                    target.chmod(0o700)
                    for path in target.rglob("*"):
                        if not path.is_symlink():
                            path.chmod(0o700 if path.is_dir() else 0o600)
        self.addCleanup(restore_permissions)
        REAL_FREEZE_ENVIRONMENT(self.root, prefix)
        for target in (bootstrap / "git", self.root / "tools/platform-tools/adb",
                       prefix / "bin/python", prefix / ".complete"):
            self.assertEqual(target.stat().st_mode & 0o222, 0)
        self.assertTrue(json.loads((self.root / "environment.json").read_text())["frozen"])

    def test_first_install_pip_uses_domestic_fallback_without_version_changes(self):
        with patch.object(runtime, "run", side_effect=[subprocess.CalledProcessError(1, "pip"), None]) as run:
            runtime.install_pip(self.root, self.root / "engine", self.root / "requirements.txt")
        self.assertEqual(run.call_count, 2)
        for index, call in enumerate(run.call_args_list):
            self.assertIn(deployment.PYPI_MIRRORS[index], call.args[0])
            self.assertEqual(call.args[0][-1], self.root / "requirements.txt")

    def test_first_install_retry_reuses_downloaded_repository(self):
        source = self.source("core")
        with patch.object(runtime, "install_remote_core", return_value=(source, "new")) as clone:
            self.assertEqual(runtime.initial_core(self.root), (source, "new"))
            self.assertEqual(runtime.initial_core(self.root), (source, "new"))
        clone.assert_called_once()

    def test_partial_first_install_recovers_without_touching_saved_environment(self):
        active, prefix = self.installed()
        runtime.saved_environment(self.root, active)
        (self.root / "active.json").unlink()
        candidate = self.source("new")
        with patch.object(runtime, "install_remote_core", return_value=(candidate, "new")), patch.object(
                runtime, "refresh_initial_core", side_effect=lambda root, source, revision: (source, revision)), patch.object(
                runtime, "install_environment") as install, patch.object(runtime, "validate") as validate:
            runtime.prepare(self.root)
        validate.assert_called_once_with(self.root, candidate, prefix)
        install.assert_not_called()
        self.adb.assert_not_called()
        self.assertEqual(json.loads((self.root / "active.json").read_text())["environment"], str(prefix))

    def test_update_fetches_into_same_repository_without_clone(self):
        source = self.source()
        (source / ".git").mkdir()
        (source / ".git/HEAD").touch()
        with patch.object(runtime, "run", return_value="") as run, patch.object(
                runtime, "git_revision", side_effect=["old", "new"]):
            revisions = runtime.begin_core_update(self.root, source, "new")
        self.assertEqual(revisions, ("old", "new"))
        commands = [call.args[0] for call in run.call_args_list]
        self.assertTrue(any("fetch" in command for command in commands))
        self.assertFalse(any("clone" in command for command in commands))
        self.assertTrue(all(command[2] == source for command in commands))

    def test_failed_fetch_preserves_repository_for_retry(self):
        checkout = self.root / "core-download"
        (checkout / ".git").mkdir(parents=True)
        (checkout / ".git/HEAD").write_text("ref: refs/heads/master\n")
        marker = checkout / ".git/complete-object"
        marker.write_text("preserve")
        with patch.object(runtime, "run", side_effect=["new", "old", None]), patch(
                "git_download.download", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                runtime.install_remote_core(self.root)
        self.assertEqual(marker.read_text(), "preserve")
        self.assertFalse((self.root / "core").exists())

    def test_retry_skips_completed_fetch(self):
        checkout = self.root / "core-download"
        (checkout / ".git").mkdir(parents=True)
        (checkout / ".git/HEAD").write_text("ref: refs/heads/master\n")
        (checkout / "gui.py").touch()
        with patch.object(runtime, "run", side_effect=["new", "new", None, "new", "new"]), patch(
                "git_download.download") as download:
            source, revision = runtime.install_remote_core(self.root)
        self.assertEqual(source, self.root / "core")
        self.assertEqual(revision, "new")
        self.assertEqual(download.call_count, 1)
        self.assertIn("checkout", download.call_args.args[0])
        self.assertIn("--progress", download.call_args.args[0])
        self.assertFalse(checkout.exists())

    def test_storage_rejects_bundle_and_external_record(self):
        with self.assertRaisesRegex(RuntimeError, "App 外"):
            runtime.validate_storage(self.root / "Test.app/Contents/Resources/ALASData")
        runtime.atomic_json(self.root / "active.json", {
            "repository": "/outside/core", "environment": str(self.root / "environments/test")})
        with self.assertRaisesRegex(RuntimeError, "旧运行路径"):
            runtime.validate_storage(self.root)
        runtime.atomic_json(self.root / "active.json", {
            "repository": str(self.root / "core"), "environment": str(self.root / "environments/test")})
        runtime.validate_storage(self.root)

    def test_real_git_clone_selects_latest_commit(self):
        upstream = self.root / "upstream"
        def git(*args):
            return subprocess.check_output(["/usr/bin/git", *map(str, args)], text=True).strip()
        git("init", "-b", "master", upstream)
        (upstream / "gui.py").write_text("first")
        git("-C", upstream, "add", "gui.py")
        git("-C", upstream, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "first")
        (upstream / "gui.py").write_text("latest")
        git("-C", upstream, "add", "gui.py")
        git("-C", upstream, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-m", "latest")
        bootstrap = self.root / "bootstrap/bin"
        bootstrap.mkdir(parents=True, exist_ok=True)
        (bootstrap / "git").symlink_to("/usr/bin/git")
        original_environment = runtime.environment
        def local_environment(*args, **kwargs):
            return dict(original_environment(*args, **kwargs), GIT_ALLOW_PROTOCOL="https:file")
        with patch.object(runtime, "UPSTREAM", upstream.as_uri()), patch.object(runtime, "environment", side_effect=local_environment):
            source, revision = runtime.install_remote_core(self.root)
        self.assertEqual(revision, git("-C", upstream, "rev-parse", "HEAD"))
        self.assertEqual((source / "gui.py").read_text(), "latest")
        self.assertEqual(git("-C", source, "rev-list", "--count", "HEAD"), "1")

    def test_first_install_checks_upstream_without_downloading_when_current(self):
        source = self.source("downloaded")
        with patch.object(runtime, "run", return_value="downloaded\trefs/heads/master") as run, patch.object(
                runtime, "begin_core_update") as clone:
            selected = runtime.refresh_initial_core(self.root, source, "downloaded")
        self.assertEqual(selected, (source, "downloaded"))
        self.assertEqual(run.call_args.args[0][1], "ls-remote")
        clone.assert_not_called()

    def test_first_install_downloads_only_delta_when_downloaded_core_is_old(self):
        source = self.source("downloaded")
        updated = self.source("updated")
        with patch.object(runtime, "run", return_value="new\trefs/heads/master"), patch.object(
                runtime, "begin_core_update", return_value=("downloaded", "new")) as clone:
            selected = runtime.refresh_initial_core(self.root, source, "downloaded")
        clone.assert_called_once_with(self.root, source, "new")
        self.assertEqual(selected, (source, "new"))
        self.assertEqual(json.loads((self.root / "installation.json").read_text())["revision"], "new")

    def test_first_install_requires_latest_version_check(self):
        source = self.source("downloaded")
        with patch.object(runtime, "run", side_effect=OSError("offline")), patch.object(
                runtime, "begin_core_update") as update:
            with self.assertRaisesRegex(RuntimeError, "无法确认最新核心版本"):
                runtime.refresh_initial_core(self.root, source, "downloaded")
        update.assert_not_called()

    def test_rollback_changes_code_only_even_for_legacy_previous_environment(self):
        active, prefix = self.installed()
        previous = self.source("previous")
        runtime.atomic_json(self.root / "previous.json", {
            "repository": str(previous), "environment": "/not-the-fixed-environment", "revision": "previous"})
        with patch.object(runtime, "install_environment") as install, patch.object(runtime, "run"):
            runtime.rollback(self.root)
        restored = json.loads((self.root / "active.json").read_text())
        self.assertEqual(restored["environment"], str(prefix))
        self.assertEqual(restored["repository"], active["repository"])
        install.assert_not_called()

    def test_deploy_preserves_user_values_and_updates_private_paths(self):
        source = self.source()
        config = source / "config/deploy.yaml"
        config.write_text("Deploy:\n  Webui:\n    Language: ja-JP\n    Theme: dark\n    Password: secret\n  Python:\n    PythonExecutable: /external/python\n")
        deployment.configure_deploy(source, self.root, self.root / "engine")
        text = config.read_text()
        self.assertIn("Language: ja-JP", text)
        self.assertIn("Password: secret", text)
        self.assertIn("PythonExecutable: " + str(self.root / "engine/bin/python"), text)
        self.assertIn("Repository: https://github.com/LmeSzinc/AzurLaneAutoScript.git", text)
        self.assertIn("InstallDependencies: false", text)
        self.assertTrue((source / "deploy/macOS/template.yaml").is_file())
        runtime.attach_data(self.root, source)
        self.assertTrue(config.is_symlink())
        deployment.configure_deploy(source, self.root, self.root / "engine")
        self.assertTrue(config.is_symlink())
        before = config.stat().st_mtime_ns
        deployment.configure_deploy(source, self.root, self.root / "engine")
        self.assertEqual(config.stat().st_mtime_ns, before)

    def test_macos_template_inherits_upstream_linux_defaults(self):
        source = self.source()
        (source / "deploy").mkdir()
        (source / "deploy/template").write_text("Deploy:\n  Webui:\n    Language: en-US\n    NewUpstreamOption: 42\n")
        deployment.configure_deploy(source, self.root, self.root / "engine")
        self.assertIn("NewUpstreamOption: 42", (source / "config/deploy.yaml").read_text())

    def test_new_requirements_invalidate_environment(self):
        seed = self.source()
        first = runtime.fingerprint(seed)
        (seed / "requirements.txt").write_text("new-dependency==1.0")
        self.assertNotEqual(first, runtime.fingerprint(seed))

    def test_lock_excludes_concurrent_operations_and_releases_after_failure(self):
        with runtime.lock(self.root):
            with self.assertRaises(RuntimeError):
                with runtime.lock(self.root):
                    pass
        with runtime.lock(self.root):
            pass

    def test_existing_logs_are_preserved(self):
        seed = self.source()
        (seed / "log").mkdir()
        (seed / "log/old.txt").write_text("old logs")
        runtime.attach_data(self.root, seed)
        self.assertTrue((seed / "log").is_symlink())
        self.assertEqual((self.root / "data/log/old.txt").read_text(), "old logs")


if __name__ == "__main__":
    unittest.main()

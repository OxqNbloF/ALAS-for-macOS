"""用临时 Git 仓库离线测试更新、回退和中断恢复。"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / "ALAS for macOS/Runtime"
sys.path.insert(0, str(RUNTIME))
spec = importlib.util.spec_from_file_location("runtime", RUNTIME / "runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def git(repository, *args):
    return subprocess.check_output(["/usr/bin/git", "-C", str(repository), *args],
                                   text=True, stderr=subprocess.DEVNULL).strip()


def main():
    with tempfile.TemporaryDirectory(prefix="alas-single-git-") as temporary:
        base = Path(temporary)
        upstream = base / "upstream"
        upstream.mkdir()
        git(upstream, "init", "-b", "master")
        git(upstream, "config", "user.email", "test@localhost")
        git(upstream, "config", "user.name", "Test")
        (upstream / ".gitignore").write_text("config/*.yaml\nconfig/*.json\n")
        def commit(version):
            (upstream / "gui.py").write_text(version)
            git(upstream, "add", ".")
            git(upstream, "commit", "-m", version)
            return git(upstream, "rev-parse", "HEAD")
        a = commit("A")
        root = base / "ALASData"
        root.mkdir()
        core = root / "core"
        git(base, "clone", "--no-local", "--depth", "1", "--no-tags", str(upstream), str(core))
        for folder in ("bootstrap/bin", "tmp", "home", "data/config"):
            (root / folder).mkdir(parents=True)
        (root / "bootstrap/bin/git").symlink_to("/usr/bin/git")
        (core / "config").mkdir()
        (core / "config/alas.json").write_text('{"user":42}')
        original_environment = runtime.environment
        def local_environment(*args, **kwargs):
            return dict(original_environment(*args, **kwargs), GIT_ALLOW_PROTOCOL="https:file")
        with patch.object(runtime, "UPSTREAM", str(upstream)), patch.object(runtime, "environment", side_effect=local_environment):
            b = commit("B")
            old, new = runtime.begin_core_update(root, core, b)
            assert (old, new) == (a, b)
            runtime.finish_core_update(root, core, old, new)
            runtime.compact_core(root, core)
            assert git(core, "rev-parse", runtime.ROLLBACK_REF) == a
            c = commit("C")
            old, new = runtime.begin_core_update(root, core, c)
            runtime.finish_core_update(root, core, old, new)
            runtime.compact_core(root, core)
            assert git(core, "rev-parse", runtime.ROLLBACK_REF) == b
            assert subprocess.run(["/usr/bin/git", "-C", str(core), "cat-file", "-e", a],
                                  stderr=subprocess.DEVNULL).returncode != 0
            assert git(core, "for-each-ref", "--format=%(refname)").splitlines() == [
                runtime.ROLLBACK_REF, "refs/heads/master"]
            for name, revision in (("active", c), ("previous", b)):
                runtime.atomic_json(root / (name + ".json"), {
                    "repository": str(core), "environment": str(root / "env"), "revision": revision})
            with patch.object(runtime, "saved_environment", return_value=root / "env"), patch.object(
                    runtime, "configure_deploy"):
                runtime.rollback(root)
            assert git(core, "rev-parse", "HEAD") == b
            assert git(core, "rev-parse", runtime.ROLLBACK_REF) == c
            assert json.loads((root / "active.json").read_text())["repository"] == str(core)
            assert json.loads((core / "config/alas.json").read_text()) == {"user": 42}
            old, new = runtime.begin_core_update(root, core, c)
            runtime.recover_core(root)
            assert git(core, "rev-parse", "HEAD") == b
            runtime.abort_core_update(root, core, old)
            assert not (root / "releases").exists()
        print("PASS: A→B→C, one rollback ref, A pruned, in-place rollback, interrupted update recovery, config preserved")


if __name__ == "__main__":
    main()

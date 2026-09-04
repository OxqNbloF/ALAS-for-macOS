"""测试原生接口的路由和认证边界，不开端口或访问用户数据。"""
import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ALAS for macOS/Runtime'))
import native_api
import runtime
from starlette.applications import Starlette
from starlette.routing import Route, WebSocketRoute


class SecurityBoundaryTests(unittest.TestCase):
    def test_only_native_api_and_health_are_exposed(self):
        async def forbidden(request):
            self.fail('An upstream route was executed')
        started = []
        core = Starlette(debug=True, routes=[Route('/', forbidden), Route('/manage', forbidden),
                          Route('/static/secrets', forbidden), WebSocketRoute('/ws', forbidden)],
                         on_startup=[lambda: started.append('start')],
                         on_shutdown=[lambda: started.append('stop')])
        with tempfile.TemporaryDirectory() as directory:
            app, token = native_api.native_only_application(core, Path(directory), Path(directory))
            self.assertFalse(app.debug)
            async def request(path, headers=(), websocket=False):
                messages = []
                async def receive():
                    return {'type': 'websocket.connect'} if websocket else {'type': 'http.request', 'body': b'', 'more_body': False}
                async def send(message):
                    messages.append(message)
                scope = dict(type='websocket' if websocket else 'http', asgi={'version': '3.0'},
                             path=path, raw_path=path.encode(), root_path='', query_string=b'',
                             headers=list(headers), method='GET', http_version='1.1', scheme='http',
                             server=('127.0.0.1', 8000), client=('127.0.0.1', 1000), subprotocols=[])
                await app(scope, receive, send)
                return messages
            async def check():
                await app.router.startup()
                self.assertEqual((await request('/'))[0]['status'], 200)
                for path in ['/manage', '/static/secrets', '/unknown']:
                    self.assertEqual((await request(path))[0]['status'], 404)
                self.assertEqual((await request('/ws', websocket=True))[0]['type'], 'websocket.close')
                self.assertEqual((await request('/native/ui-preferences'))[0]['status'], 401)
                auth = [(b'authorization', ('Bearer ' + token).encode())]
                self.assertEqual((await request('/native/ui-preferences', auth))[0]['status'], 200)
                self.assertEqual((await request('/native/ui-preferences', auth + [(b'origin', b'https://evil.example')]))[0]['status'], 401)
                await app.router.shutdown()
            asyncio.run(check())
            self.assertEqual(started, ['start', 'stop'])

    def test_config_json_import_remains_available_with_validation(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            api = native_api.NativeAPI(Path(directory), Path(directory), "test")
            modules = {
                "module.config.utils": SimpleNamespace(filepath_config=lambda *args: "", alas_instance=lambda: []),
                "module.submodule.utils": SimpleNamespace(get_config_mod=lambda name: "alas", get_available_mod=lambda: []),
            }
            with patch.dict(sys.modules, modules), patch.object(api, "commit") as commit:
                content = '{"Alas": {"Emulator": {"Serial": "127.0.0.1:5555"}}}'
                self.assertEqual(api.transfer({"action": "import", "name": "test", "content": content}), {"ok": True})
                self.assertEqual(commit.call_args.args[0], "test")
                commit.reset_mock()
                for body in [
                    {"name": "../outside", "content": content},
                    {"name": "test", "content": "[]"},
                    {"name": "test", "content": content, "mod": "unknown"},
                ]:
                    with self.assertRaises(ValueError):
                        api.transfer(dict(body, action="import"))
                commit.assert_not_called()

    def test_git_policy_rejects_plaintext_and_overrides_local_tls_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(['/usr/bin/git', 'init', '-q', directory], check=True)
            subprocess.run(['/usr/bin/git', '-C', directory, 'config', 'http.sslVerify', 'false'], check=True)
            env = runtime.environment(root)
            result = subprocess.check_output(['/usr/bin/git', '-C', directory, 'config', '--get', 'http.sslVerify'], env=env, text=True)
            self.assertEqual(result.strip(), 'true')
            for url in ['git://127.0.0.1/repo', 'http://127.0.0.1/repo', 'file:///tmp/repo', 'ext::anything']:
                result = subprocess.run(['/usr/bin/git', 'ls-remote', url], env=env, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('not allowed', result.stderr)

    def test_mismatched_initial_commit_is_rejected_before_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'core-download/.git').mkdir(parents=True)
            (root / 'core-download/.git/HEAD').touch()
            with patch.object(runtime, 'run', side_effect=['expected', 'old', None, 'different']), patch('git_download.download') as download:
                with self.assertRaisesRegex(RuntimeError, '提交'):
                    runtime.install_remote_core(root)
                self.assertEqual(download.call_count, 1)
                self.assertIn('fetch', download.call_args.args[0])
                self.assertFalse((root / 'core').exists())

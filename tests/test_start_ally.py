"""Launcher lifecycle checks without Word, certificates, or private project data."""

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "start_ally.py"
SPEC = importlib.util.spec_from_file_location("start_ally_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
LAUNCHER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = LAUNCHER
SPEC.loader.exec_module(LAUNCHER)


class LauncherTests(unittest.TestCase):
    def test_project_path_does_not_depend_on_current_directory(self):
        original = Path.cwd()
        with tempfile.TemporaryDirectory(prefix="Ally 中文 空格 ") as folder:
            try:
                os.chdir(folder)
                self.assertEqual(LAUNCHER.project_root(), SCRIPT.parent.parent)
            finally:
                os.chdir(original)

    def test_bound_port_is_refused_without_stopping_its_owner(self):
        with patch.object(LAUNCHER.socket, "socket") as create_socket:
            create_socket.return_value.__enter__.return_value.bind.side_effect = OSError("busy")
            with patch.object(LAUNCHER, "stop_process_tree") as stop:
                with self.assertRaisesRegex(LAUNCHER.LaunchError, "8083"):
                    LAUNCHER.ensure_ports_available([8083])
                stop.assert_not_called()

    def test_missing_environment_gives_installation_guidance(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(LAUNCHER.LaunchError, "手册"):
                LAUNCHER.find_python(Path(folder), windows=False)

    def test_environment_selection_prefers_venv_and_supports_mac_fallback(self):
        with tempfile.TemporaryDirectory(prefix="Ally 中文 空格 ") as folder:
            root = Path(folder)
            fallback = root / ".venv-mac" / "bin" / "python"
            primary = root / ".venv" / "bin" / "python"
            fallback.parent.mkdir(parents=True)
            fallback.touch()
            self.assertEqual(LAUNCHER.find_python(root, windows=False), fallback)
            primary.parent.mkdir(parents=True)
            primary.touch()
            self.assertEqual(LAUNCHER.find_python(root, windows=False), primary)

    def test_missing_node_dependency_is_reported_before_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(LAUNCHER.LaunchError, "npm"):
                LAUNCHER.check_project_files(Path(folder))

    def test_failed_process_start_closes_log(self):
        with tempfile.TemporaryDirectory() as folder:
            owner = LAUNCHER.ProcessOwner(Path(folder), {})
            log = io.StringIO()
            with patch.object(Path, "open", return_value=log):
                with patch.object(LAUNCHER.subprocess, "Popen", side_effect=OSError("test")):
                    with self.assertRaises(OSError):
                        owner.start_service("test", ["missing-command"])
            self.assertTrue(log.closed)
            self.assertEqual(owner.services, [])

    def test_cleanup_continues_when_one_process_cannot_be_stopped(self):
        owner = LAUNCHER.ProcessOwner(Path("."), {})
        logs = [io.StringIO(), io.StringIO()]
        processes = [Mock(pid=101), Mock(pid=102)]
        owner.services = [
            LAUNCHER.Service("first", processes[0], logs[0]),
            LAUNCHER.Service("second", processes[1], logs[1]),
        ]
        with patch.object(LAUNCHER, "stop_process_tree", side_effect=[OSError("test"), None]) as stop:
            with patch("sys.stdout", new=io.StringIO()):
                owner.close()
        self.assertEqual(stop.call_count, 2)
        self.assertTrue(all(log.closed for log in logs))

    def test_windows_cleanup_targets_only_owned_pid(self):
        process = Mock(pid=12345)
        process.poll.return_value = None
        with patch.object(LAUNCHER.subprocess, "run") as run:
            run.return_value.returncode = 0
            LAUNCHER.stop_process_tree(process, windows=True)
        command = run.call_args.args[0]
        self.assertEqual(command, ["taskkill", "/PID", "12345", "/T", "/F"])
        process.wait.assert_called_once()

    @unittest.skipIf(os.name == "nt", "POSIX process groups")
    def test_posix_cleanup_stops_a_real_owned_process(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
        )
        try:
            LAUNCHER.stop_process_tree(process)
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_office_exit_zero_without_success_marker_is_failure(self):
        self.assertFalse(LAUNCHER.office_started("Unable to start debugging.\nError: test\n"))
        self.assertFalse(LAUNCHER.office_started("Started.\nUnable to start the dev server.\n"))
        self.assertTrue(LAUNCHER.office_started("The dev server is already running.\nStarted.\n"))

    def test_loopback_warning_is_not_a_startup_failure(self):
        """A non-admin run still sideloads; it only cannot add the loopback exemption."""
        output = (
            "? Allow localhost loopback for Microsoft Edge WebView? Yes\n"
            "\u9519\u8bef: \u8bbf\u95ee\u88ab\u62d2\u7edd\u3002\n"
            "Failed to add loopback exemption.\n"
            "Will try to sideload the Office Add-in without the loopback exemption, "
            "but it might not load correctly from localhost.\n"
            "\nSideloading the Office Add-in...\nStarted.\n"
        )
        self.assertTrue(LAUNCHER.office_started(output))
        self.assertTrue(LAUNCHER.office_needs_loopback_exemption(output))
        self.assertFalse(
            LAUNCHER.office_needs_loopback_exemption("Sideloading the Office Add-in...\nStarted.\n")
        )
        # A genuine failure is still reported as one.
        self.assertFalse(LAUNCHER.office_started("Failed to sideload the Office Add-in.\n"))

    def test_inherited_npm_commands_cannot_spawn_an_extra_server(self):
        inherited = {
            "npm_package_json": "/other/project/package.json",
            "npm_package_scripts_dev_server": "unwanted",
            "npm_package_scripts_packager": "unwanted",
        }
        with patch.dict(os.environ, inherited):
            actual = LAUNCHER.launcher_environment()
        self.assertTrue(all(name not in actual for name in inherited))

    def test_project_node_is_used_without_a_global_node_installation(self):
        with tempfile.TemporaryDirectory(prefix="Ally 中文 空格 ") as folder:
            root = Path(folder)
            node = root / (".ally-tools/node/node.exe" if os.name == "nt" else ".ally-tools/node/bin/node")
            node.parent.mkdir(parents=True)
            node.write_text("#!/bin/sh\nexit 0\n")
            node.chmod(0o755)
            with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
                env = LAUNCHER.launcher_environment(root)
            # Windows may resolve the shim as node.EXE, so compare case-insensitively.
            resolved = LAUNCHER.shutil.which("node", path=env["PATH"])
            self.assertIsNotNone(resolved)
            self.assertEqual(os.path.normcase(resolved), os.path.normcase(str(node)))

    def test_setup_connection_profile_is_reused_at_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / ".ally-tools/promptflow"
            profile.mkdir(parents=True)
            self.assertEqual(LAUNCHER.launcher_environment(root)["PF_HOME_DIRECTORY"], str(profile))

    def test_flow_exit_points_user_to_connection_initialization(self):
        owner = LAUNCHER.ProcessOwner(Path("."), {})
        process = Mock(pid=123)
        process.poll.return_value = 1
        owner.services = [LAUNCHER.Service("flow", process, io.StringIO())]
        with self.assertRaisesRegex(LAUNCHER.LaunchError, "本地连接初始化"):
            owner.check_running()

    def test_second_launcher_window_is_refused_while_the_first_holds_the_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = LAUNCHER.acquire_launcher_lock(root)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(LAUNCHER.acquire_launcher_lock(root))
            finally:
                LAUNCHER.release_launcher_lock(first)
            again = LAUNCHER.acquire_launcher_lock(root)
            self.assertIsNotNone(again, "the lock must be reusable after a clean exit")
            LAUNCHER.release_launcher_lock(again)

    @patch.object(LAUNCHER, "ensure_desktop_shortcut")
    def test_startup_timeout_cleans_every_started_service(self, desktop_shortcut):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(LAUNCHER, "check_dependencies", return_value=(Path("python"), "node")):
                with patch.object(LAUNCHER, "ensure_ports_available"):
                    with patch.object(LAUNCHER, "ProcessOwner") as owner_type:
                        owner = owner_type.return_value
                        with patch.object(LAUNCHER, "wait_for_services", side_effect=LAUNCHER.LaunchError("timeout")):
                            with patch("sys.stdout", new=io.StringIO()):
                                with self.assertRaisesRegex(LAUNCHER.LaunchError, "timeout"):
                                    LAUNCHER.run_launcher(Path(folder))
                        self.assertEqual(owner.start_service.call_count, 4)
                        owner.close.assert_called_once()
                        desktop_shortcut.assert_called_once_with(Path(folder))

    def test_check_only_does_not_create_desktop_entry_or_start_services(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(LAUNCHER, "check_dependencies", return_value=(Path("python"), "node")):
                with patch.object(LAUNCHER, "ensure_ports_available"):
                    with patch.object(LAUNCHER, "ensure_desktop_shortcut") as desktop_shortcut:
                        with patch.object(LAUNCHER, "ProcessOwner") as owner_type:
                            with patch("sys.stdout", new=io.StringIO()):
                                self.assertEqual(LAUNCHER.run_launcher(Path(folder), check_only=True), 0)
                        owner_type.assert_not_called()
                    desktop_shortcut.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_desktop_error_does_not_prevent_service_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(LAUNCHER, "check_dependencies", return_value=(Path("python"), "node")):
                with patch.object(LAUNCHER, "ensure_ports_available"):
                    with patch.object(LAUNCHER, "create_desktop_shortcut", side_effect=PermissionError("desktop")):
                        with patch.object(LAUNCHER, "ProcessOwner") as owner_type:
                            owner = owner_type.return_value
                            with patch.object(LAUNCHER, "wait_for_services", side_effect=LAUNCHER.LaunchError("services started")):
                                output = io.StringIO()
                                with patch("sys.stdout", new=output):
                                    with self.assertRaisesRegex(LAUNCHER.LaunchError, "services started"):
                                        LAUNCHER.run_launcher(Path(folder))
                            self.assertEqual(owner.start_service.call_count, 4)
                            self.assertIn("未能创建桌面启动入口", output.getvalue())
                            owner.close.assert_called_once()


class ServiceHealthTests(unittest.TestCase):
    def test_health_check_uses_each_service_route_not_the_root_path(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/policy-sets":
                    body = json.dumps({"policySets": ["A"]}).encode()
                    self.send_response(200)
                else:
                    body = b"not found"
                    self.send_response(404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            self.assertEqual(LAUNCHER.probe_service("policy", port), (True, "/policy-sets 可用"))
            ok, detail = LAUNCHER.probe_service("flow", port)
            self.assertFalse(ok, "a 404 at the wrong route must not count as ready")
            self.assertIn("404", detail)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_wait_succeeds_only_when_all_four_routes_answer(self):
        owner = Mock(log_dir=Path("logs"))
        with patch.object(LAUNCHER, "probe_service", return_value=(True, "ok")):
            self.assertIsNone(LAUNCHER.wait_for_services(owner, timeout=1))
        owner.check_running.assert_called()

    def test_wait_reports_the_service_and_reason_that_never_answered(self):
        owner = Mock(log_dir=Path("logs"))

        def probe(name, port):
            if name == "policy":
                return True, "/policy-sets 可用"
            return False, "连接被拒绝"

        with patch.object(LAUNCHER, "probe_service", side_effect=probe), \
                patch.object(LAUNCHER.time, "sleep"):
            with self.assertRaises(LAUNCHER.LaunchError) as caught:
                LAUNCHER.wait_for_services(owner, timeout=0.2)
        message = str(caught.exception)
        self.assertIn("合同分析服务", message)
        self.assertIn("8083", message)
        self.assertIn("连接被拒绝", message)

    def test_webpack_compile_error_is_reported_as_a_frontend_failure(self):
        owner = Mock(log_dir=Path("logs"))
        with patch.object(LAUNCHER, "probe_service", return_value=(False, "连接被拒绝")), \
                patch.object(LAUNCHER, "web_compile_failure",
                             return_value="ERROR in ./src/taskpane/taskpane.js\nModule not found: x"), \
                patch.object(LAUNCHER.time, "sleep"):
            with self.assertRaisesRegex(LAUNCHER.LaunchError, "前端编译"):
                LAUNCHER.wait_for_services(owner, timeout=5)


class PortReuseTests(unittest.TestCase):
    def test_project_listener_is_recognised_and_other_listeners_are_not(self):
        with tempfile.TemporaryDirectory(prefix="Ally 中文 ") as folder:
            root = Path(folder)
            own = f"python {root / 'index_server.py'}"
            with patch.object(LAUNCHER, "port_owner", return_value=(10, "python.exe", own)):
                self.assertTrue(LAUNCHER.port_served_by_project(8084, root))
                self.assertFalse(LAUNCHER.port_served_by_project(8085, root))
            other = 'python C:\\Other\\index_server.py'
            with patch.object(LAUNCHER, "port_owner", return_value=(11, "python.exe", other)):
                self.assertFalse(LAUNCHER.port_served_by_project(8084, root))

    def test_existing_project_service_is_reused_instead_of_started_twice(self):
        with tempfile.TemporaryDirectory() as folder:
            owner = LAUNCHER.ProcessOwner(Path(folder), {})
            with patch.object(LAUNCHER, "port_served_by_project", return_value=True), \
                    patch.object(LAUNCHER.subprocess, "Popen") as popen, \
                    patch("sys.stdout", new=io.StringIO()):
                owner.start_service("policy", ["python", "index_server.py"], port=8084)
            popen.assert_not_called()
            self.assertEqual(len(owner.services), 1)
            self.assertTrue(owner.services[0].reused)
            # A reused service belongs to an earlier session, so it must survive cleanup.
            with patch.object(LAUNCHER, "stop_process_tree") as stop:
                owner.close()
            stop.assert_not_called()

    def test_own_running_service_does_not_block_startup(self):
        with patch.object(LAUNCHER.socket, "socket") as create_socket:
            create_socket.return_value.__enter__.return_value.bind.side_effect = OSError("busy")
            with patch.object(LAUNCHER, "port_served_by_project", return_value=True):
                self.assertEqual(LAUNCHER.ensure_ports_available([8084], root=Path(".")), {8084})

    def test_foreign_port_owner_is_reported_without_being_stopped(self):
        with patch.object(LAUNCHER.socket, "socket") as create_socket:
            create_socket.return_value.__enter__.return_value.bind.side_effect = OSError("busy")
            with patch.object(LAUNCHER, "port_served_by_project", return_value=False), \
                    patch.object(LAUNCHER, "port_owner",
                                 return_value=(4321, "chrome.exe", "chrome --remote-debugging-port=9222")), \
                    patch.object(LAUNCHER, "stop_process_tree") as stop:
                with self.assertRaises(LAUNCHER.LaunchError) as caught:
                    LAUNCHER.ensure_ports_available([3000], root=Path("."))
        message = str(caught.exception)
        self.assertIn("3000", message)
        self.assertIn("chrome.exe", message)
        self.assertIn("4321", message)
        stop.assert_not_called()


class DesktopShortcutTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "macOS entry uses POSIX permissions and Bash")
    def test_mac_entry_executes_launcher_at_a_quoted_absolute_path(self):
        with tempfile.TemporaryDirectory(prefix="Ally 中文 ' ") as folder:
            home = Path(folder)
            (home / "Desktop").mkdir()
            root = home / "project 中文 ' folder"
            root.mkdir()
            target = root / "Start-Ally.command"
            target.write_text('#!/bin/bash\nprintf \'%s\\n\' "$@"\n', encoding="utf-8")
            with patch.object(Path, "home", return_value=home):
                self.assertEqual(LAUNCHER.create_desktop_shortcut(root, platform="darwin"), "created")
            shortcut = home / "Desktop" / "Ally Legal Flex.command"
            self.assertEqual(shortcut.stat().st_mode & 0o777, 0o755)
            result = subprocess.run(
                ["/bin/bash", str(shortcut), "argument 中文 ' spaced", "second"],
                cwd=home, capture_output=True, text=True, check=True,
            )
            self.assertEqual(result.stdout, "argument 中文 ' spaced\nsecond\n")

    def test_mac_existing_desktop_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "Desktop").mkdir()
            shortcut = home / "Desktop" / "Ally Legal Flex.command"
            shortcut.write_text("User content", encoding="utf-8")
            with patch.object(Path, "home", return_value=home):
                self.assertEqual(LAUNCHER.create_desktop_shortcut(home, platform="darwin"), "existing")
            self.assertEqual(shortcut.read_text(encoding="utf-8"), "User content")

    def test_mac_missing_desktop_is_not_created(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            with patch.object(Path, "home", return_value=home):
                with self.assertRaises(FileNotFoundError):
                    LAUNCHER.create_desktop_shortcut(home, platform="darwin")
            self.assertEqual(list(home.iterdir()), [])

    def test_mac_missing_project_launcher_leaves_no_broken_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            desktop = home / "Desktop"
            desktop.mkdir()
            with patch.object(Path, "home", return_value=home):
                with self.assertRaises(OSError):
                    LAUNCHER.create_desktop_shortcut(home, platform="darwin")
            self.assertEqual(list(desktop.iterdir()), [])

    def test_windows_paths_are_passed_as_data_to_a_system_desktop_lookup(self):
        with tempfile.TemporaryDirectory(prefix="Ally 中文 ' ") as folder:
            root = Path(folder)
            with patch.object(LAUNCHER.subprocess, "run") as run:
                run.return_value.stdout = "created\r\n"
                self.assertEqual(LAUNCHER.create_desktop_shortcut(root, platform="win32"), "created")
            command = run.call_args.args[0]
            script = base64.b64decode(command[-1]).decode("utf-16le")
            self.assertEqual(command[:4], ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand"])
            self.assertNotIn(str(root), script)
            self.assertEqual(run.call_args.kwargs["env"]["ALLY_SHORTCUT_PROJECT_ROOT"], str(root.resolve()))
            self.assertIn("[Environment+SpecialFolder]::DesktopDirectory", script)
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_windows_existing_entry_is_reported_without_failure(self):
        with patch.object(LAUNCHER.subprocess, "run") as run:
            run.return_value.stdout = "existing\r\n"
            self.assertEqual(LAUNCHER.create_desktop_shortcut(Path("."), platform="win32"), "existing")

    def test_windows_command_failure_is_nonfatal(self):
        for error in (FileNotFoundError("powershell"), subprocess.TimeoutExpired("powershell", 15),
                      subprocess.CalledProcessError(1, "powershell")):
            with self.subTest(error=type(error).__name__):
                with patch.object(LAUNCHER, "create_desktop_shortcut", side_effect=error):
                    output = io.StringIO()
                    with patch("sys.stdout", new=output):
                        LAUNCHER.ensure_desktop_shortcut(Path("."))
                    self.assertIn("仍可从项目文件夹", output.getvalue())


if __name__ == "__main__":
    unittest.main()

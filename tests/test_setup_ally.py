"""First-install, retry and migration checks without Word or model requests."""

import hashlib
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import signal
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("setup_ally", ROOT / "scripts/setup_ally.py")
SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SETUP)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Ally 中文 ' 空格 ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/runtime-downloads.json").write_text(
            (ROOT / "scripts/runtime-downloads.json").read_text(), encoding="utf-8"
        )
        self.requirements = self.root / "backend/PromptFlow/legal-main-flow/requirements.txt"
        self.requirements.parent.mkdir(parents=True)
        self.requirements.write_text("promptflow\nopenai\n")
        (self.root / "package-lock.json").write_text('{"lockfileVersion":3}')
        (self.root / "package.json").write_text('{"name":"test"}')
        database = self.root / ".ally-tools/promptflow/pf.sqlite"
        database.parent.mkdir(parents=True)
        database.touch()

    def test_platforms_are_selected_without_guessing_windows_arm(self):
        self.assertEqual(SETUP.platform_key("darwin", "arm64"), "mac-arm64")
        self.assertEqual(SETUP.platform_key("darwin", "x86_64"), "mac-x64")
        self.assertEqual(SETUP.platform_key("win32", "AMD64"), "windows-x64")
        with self.assertRaises(SETUP.SetupError):
            SETUP.platform_key("win32", "ARM64")

    def test_manifest_has_pinned_official_downloads(self):
        manifest = SETUP.load_manifest(self.root)
        for target in manifest["platforms"].values():
            for name in ("uv", "node"):
                self.assertRegex(target[name]["sha256"], r"^[0-9a-f]{64}$")
                self.assertTrue(target[name]["url"].startswith((
                    "https://github.com/astral-sh/uv/releases/download/",
                    "https://nodejs.org/dist/",
                )))

    def test_download_hash_failure_preserves_previous_file(self):
        target = self.root / "node.zip"
        target.write_bytes(b"previous")
        with patch.object(SETUP.urllib.request, "urlopen", return_value=io.BytesIO(b"bad")):
            with self.assertRaisesRegex(SETUP.SetupError, "SHA256"):
                SETUP.download_verified("https://nodejs.org/test.zip", "0" * 64, target)
        self.assertEqual(target.read_bytes(), b"previous")
        self.assertEqual(sorted(p.name for p in self.root.glob("*.part")), [])

    def test_verified_download_is_atomic_and_reuses_valid_cache(self):
        data = b"valid archive"
        target = self.root / "node.zip"
        digest = hashlib.sha256(data).hexdigest()
        with patch.object(SETUP.urllib.request, "urlopen", return_value=io.BytesIO(data)) as network:
            SETUP.download_verified("https://nodejs.org/test.zip", digest, target)
            SETUP.download_verified("https://nodejs.org/test.zip", digest, target)
        self.assertEqual(target.read_bytes(), data)
        self.assertEqual(network.call_count, 1)

    def test_archives_cannot_escape_installation_folder(self):
        for relative in ("../escape.txt", "/absolute.txt", "C:/outside.txt"):
            archive = self.root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr(relative, "bad")
            with self.assertRaises(SETUP.SetupError):
                SETUP.extract_archive(archive, self.root / "extract")
        archive = self.root / "bad.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            link = tarfile.TarInfo("node/bin/evil")
            link.type = tarfile.SYMTYPE
            link.linkname = "../../../escape"
            handle.addfile(link)
        with self.assertRaises(SETUP.SetupError):
            SETUP.extract_archive(archive, self.root / "extract")

    def test_node_archive_keeps_relative_npm_symlink(self):
        archive = self.root / "node.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            source = b"npm"
            member = tarfile.TarInfo("node/lib/npm.js")
            member.size = len(source)
            handle.addfile(member, io.BytesIO(source))
            link = tarfile.TarInfo("node/bin/npm")
            link.type = tarfile.SYMTYPE
            link.linkname = "../lib/npm.js"
            handle.addfile(link)
        destination = self.root / "extract"
        SETUP.extract_archive(archive, destination)
        self.assertEqual((destination / "node/bin/npm").read_bytes(), b"npm")

    def test_private_environment_does_not_modify_global_path_or_registry(self):
        env = SETUP.setup_environment(self.root)
        self.assertEqual(env["UV_PYTHON_INSTALL_DIR"], str(self.root / ".ally-tools/python"))
        self.assertEqual(env["UV_PYTHON_INSTALL_REGISTRY"], "0")
        self.assertEqual(env["UV_PYTHON_INSTALL_BIN"], "0")
        self.assertEqual(env["UV_NO_MODIFY_PATH"], "1")
        self.assertEqual(env["PYTHONUTF8"], "1")
        self.assertEqual(env["PF_HOME_DIRECTORY"], str(self.root / ".ally-tools/promptflow"))

    def test_flow_profile_is_local_and_existing_preferences_are_preserved(self):
        SETUP.prepare_flow_profile(self.root)
        profile = self.root / ".ally-tools/promptflow/pf.yaml"
        self.assertIn("enabled: false", profile.read_text())
        profile.write_text("user preference")
        SETUP.prepare_flow_profile(self.root)
        self.assertEqual(profile.read_text(), "user preference")

    def test_first_install_and_repair_preserve_all_user_configuration(self):
        names = ("model_config.json", "policy.json", "policy_sets.json", "prompt_settings.json")
        for name in names:
            (self.root / name).write_text("private user content", encoding="utf-8")
        with patch.object(SETUP, "ensure_node", return_value=Path("node")), \
                patch.object(SETUP, "ensure_venv", return_value=Path("python")), \
                patch.object(SETUP, "run_command") as run, \
                patch.object(SETUP, "verify_installation"), \
                patch.object(SETUP, "initialize_connection"), \
                patch.object(SETUP, "ensure_desktop_shortcut") as shortcut:
            SETUP.install(self.root, no_shortcut=True)
            SETUP.install(self.root, repair=True, no_shortcut=True)
        self.assertTrue((self.root / ".ally-tools/setup-receipt.json").is_file())
        self.assertTrue(any("ci" in call.args[0] for call in run.call_args_list))
        shortcut.assert_not_called()
        for name in names:
            self.assertEqual((self.root / name).read_text(), "private user content")

    def test_completed_install_skips_downloaded_dependencies_but_rechecks_readiness(self):
        with patch.object(SETUP, "ensure_node", return_value=Path("node")), \
                patch.object(SETUP, "ensure_venv", return_value=Path("python")), \
                patch.object(SETUP, "run_command") as run, \
                patch.object(SETUP, "verify_installation") as verify, \
                patch.object(SETUP, "initialize_connection") as initialize, \
                patch.object(SETUP, "ensure_desktop_shortcut"):
            SETUP.install(self.root)
            initial_calls = run.call_count
            SETUP.install(self.root)
            self.assertEqual(run.call_count, initial_calls)
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(initialize.call_count, 1)
            (self.root / ".ally-tools/promptflow/pf.sqlite").unlink()
            SETUP.install(self.root)
            self.assertEqual(initialize.call_count, 2)
            self.requirements.write_text("promptflow\nopenai\n# changed\n")
            SETUP.install(self.root)
            self.assertGreater(run.call_count, initial_calls)

    def test_failure_invalidates_receipt_and_can_be_retried(self):
        with patch.object(SETUP, "ensure_node", return_value=Path("node")), \
                patch.object(SETUP, "ensure_venv", return_value=Path("python")), \
                patch.object(SETUP, "verify_installation"), \
                patch.object(SETUP, "initialize_connection"), \
                patch.object(SETUP, "ensure_desktop_shortcut"), \
                patch.object(SETUP, "run_command") as run:
            SETUP.install(self.root)
            run.side_effect = SETUP.SetupError("connection lost")
            with self.assertRaises(SETUP.SetupError):
                SETUP.install(self.root, repair=True)
            self.assertFalse((self.root / ".ally-tools/setup-receipt.json").exists())
            run.side_effect = None
            SETUP.install(self.root)
            self.assertTrue((self.root / ".ally-tools/setup-receipt.json").is_file())

    def test_existing_incompatible_environment_is_never_deleted(self):
        (self.root / ".venv").mkdir()
        sentinel = self.root / ".venv/user-file"
        sentinel.write_text("keep")
        with self.assertRaises(SETUP.SetupError):
            SETUP.ensure_venv(self.root, self.root / "uv", {})
        self.assertEqual(sentinel.read_text(), "keep")

    def test_commands_keep_unicode_paths_as_single_arguments_and_fail_loudly(self):
        command = [str(self.root / "python"), "-c", "print('中文')"]
        with patch.object(SETUP.subprocess, "run", side_effect=subprocess.CalledProcessError(1, command)) as run:
            with self.assertRaises(SETUP.SetupError):
                SETUP.run_command(command, self.root, {})
        self.assertEqual(run.call_args.args[0], command)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_existing_promptflow_connection_is_not_replaced(self):
        with patch.object(SETUP.subprocess, "run") as run:
            run.return_value.returncode = 0
            SETUP.initialize_connection(self.root, Path("python"), {})
        self.assertEqual(run.call_count, 1)
        self.assertIn("show", run.call_args.args[0])

    def test_missing_connection_is_initialized_without_printing_its_payload(self):
        with patch.object(SETUP.subprocess, "run") as run:
            run.side_effect = [subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]
            SETUP.initialize_connection(self.root, Path("python"), {})
        self.assertIn("create", run.call_args_list[1].args[0])
        self.assertTrue(all(c.kwargs.get("capture_output") for c in run.call_args_list))

    def test_node_install_and_reuse_from_a_real_archive(self):
        manifest = SETUP.load_manifest(self.root)
        spec = manifest["platforms"][SETUP.platform_key()]["node"]
        archive = self.root / ".ally-tools/downloads" / spec["url"].rsplit("/", 1)[-1]
        archive.parent.mkdir(parents=True)
        if os.name == "nt":
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("node-release/node.exe", "node")
                handle.writestr("node-release/node_modules/npm/bin/npm-cli.js", "npm")
        else:
            with tarfile.open(archive, "w:gz") as handle:
                for name in ("bin/node", "lib/node_modules/npm/bin/npm-cli.js"):
                    member = tarfile.TarInfo("node-release/" + name)
                    member.size = 4
                    member.mode = 0o755
                    handle.addfile(member, io.BytesIO(b"test"))
        with patch.object(SETUP, "download_verified"), patch.object(SETUP.subprocess, "run") as run:
            node = SETUP.ensure_node(self.root, manifest, {})
            self.assertTrue(node.is_file())
            run.return_value = subprocess.CompletedProcess([], 0, manifest["node_version"] + "\n")
            self.assertEqual(SETUP.ensure_node(self.root, manifest, {}), node)
            run.return_value = subprocess.CompletedProcess([], 0, "v0.0.0")
            self.assertEqual(SETUP.ensure_node(self.root, manifest, {}), node)
        self.assertFalse(list((self.root / ".ally-tools").glob("node-stage-*")))

    def test_python_creation_and_existing_environment_probe(self):
        with patch.object(SETUP, "run_command") as run:
            python = SETUP.ensure_venv(self.root, self.root / "uv", {})
            self.assertIn("venv", run.call_args.args[0])
        python.parent.mkdir(parents=True)
        python.touch()
        with patch.object(SETUP.subprocess, "run") as run:
            run.return_value.returncode = 0
            self.assertEqual(SETUP.ensure_venv(self.root, self.root / "uv", {}), python)
            run.return_value.returncode = 1
            with self.assertRaises(SETUP.SetupError):
                SETUP.ensure_venv(self.root, self.root / "uv", {})
        self.assertTrue(python.exists())

    def test_installation_validation_and_read_only_check(self):
        with patch.object(SETUP, "check_dependencies"):
            with self.assertRaises(SETUP.SetupError):
                SETUP.verify_installation(self.root, {})
            (self.root / "dist").mkdir()
            for name in ("taskpane.html", "configpane.html"):
                (self.root / "dist" / name).touch()
            SETUP.verify_installation(self.root, {})
        with patch.object(SETUP, "verify_installation"), \
                patch.object(SETUP, "install") as install, \
                patch.object(SETUP.Path, "resolve", return_value=ROOT / "scripts/setup_ally.py"), \
                patch.object(sys, "argv", ["setup_ally", "--check"]):
            self.assertEqual(SETUP.main(), 0)
            install.assert_not_called()

    def test_locks_reject_concurrent_setup_and_release_without_manual_cleanup(self):
        with SETUP.installation_lock(self.root):
            with self.assertRaises(SETUP.SetupError):
                with SETUP.installation_lock(self.root):
                    self.fail("Concurrent installer was allowed")
        with SETUP.installation_lock(self.root):
            self.assertTrue((self.root / ".ally-tools/setup.lock").is_file())

    @unittest.skipIf(os.name == "nt", "Windows closes processes without SIGHUP")
    def test_closing_a_mac_installation_window_releases_the_lock(self):
        code = (
            f"import sys,time;sys.path.insert(0,{str(ROOT / 'scripts')!r});"
            "import setup_ally as s;from pathlib import Path;s.register_interrupts();"
            f"root=Path({str(self.root)!r})\n"
            "try:\n with s.installation_lock(root):\n  print('ready',flush=True);time.sleep(30)\n"
            "except KeyboardInterrupt: pass\n"
        )
        child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(child.stdout.readline().strip(), b"ready")
            child.send_signal(signal.SIGHUP)
            child.communicate(timeout=10)
            with SETUP.installation_lock(self.root):
                pass
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()

    @unittest.skipUnless(sys.platform == "darwin", "Mac bootstrap uses native plutil")
    def test_mac_bootstrap_reuses_uv_with_build_metadata_without_network(self):
        shutil.copy2(ROOT / "Setup-Ally.command", self.root / "Setup-Ally.command")
        uv = self.root / ".ally-tools/uv/uv"
        uv.parent.mkdir(parents=True)
        uv.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
                      ' echo "uv 0.13.4 (build-metadata 2026-10-20)"\n'
                      'else\n echo "reused-installed-uv"\nfi\n')
        uv.chmod(0o755)
        binaries = self.root / "fake-bin"
        binaries.mkdir()
        for name, script in {
            "uname": '#!/bin/sh\nif [ "$1" = "-s" ]; then echo Darwin; else echo arm64; fi\n',
            "curl": '#!/bin/sh\necho "Unexpected network request" >&2\nexit 9\n',
        }.items():
            command = binaries / name
            command.write_text(script)
            command.chmod(0o755)
        result = subprocess.run(["/bin/bash", str(self.root / "Setup-Ally.command"), "--no-shortcut"],
                                env={**os.environ, "PATH": str(binaries) + ":/usr/bin:/bin"},
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reused-installed-uv", result.stdout)


if __name__ == "__main__":
    unittest.main()

"""Prepare project-local runtimes and dependencies without changing user settings."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile

from start_ally import LaunchError, check_dependencies, ensure_desktop_shortcut


SCHEMA = 1


class SetupError(Exception):
    """Installation cannot proceed; keep existing configuration intact."""


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    system = sys.platform if system is None else system
    machine = platform.machine().lower() if machine is None else machine.lower()
    if system == "darwin" and machine in ("arm64", "aarch64"):
        return "mac-arm64"
    if system == "darwin" and machine in ("x86_64", "amd64"):
        return "mac-x64"
    if system == "win32" and machine in ("amd64", "x86_64"):
        return "windows-x64"
    raise SetupError("支持 Windows Intel/AMD 64 位及 Mac Intel/Apple Silicon。")


def load_manifest(root: Path) -> dict:
    return json.loads((root / "scripts/runtime-downloads.json").read_text(encoding="utf-8"))


def setup_environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT",
                 "npm_config_prefix", "npm_config_global", "NPM_CONFIG_PREFIX", "NPM_CONFIG_GLOBAL",
                 "npm_package_json", "npm_package_scripts_dev_server", "npm_package_scripts_packager"):
        env.pop(name, None)
    tools = root / ".ally-tools"
    env.update({
        "UV_PYTHON_INSTALL_DIR": str(tools / "python"),
        "UV_PYTHON_BIN_DIR": str(tools / "python-bin"),
        "UV_CACHE_DIR": str(tools / "cache"),
        "UV_PYTHON_INSTALL_REGISTRY": "0",
        "UV_PYTHON_INSTALL_BIN": "0",
        "UV_NO_MODIFY_PATH": "1",
        "UV_NO_CONFIG": "1",
        "PF_HOME_DIRECTORY": str(tools / "promptflow"),
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
        "NODE_ENV": "development",
    })
    node_dir = tools / "node" if os.name == "nt" else tools / "node/bin"
    env["PATH"] = str(node_dir) + os.pathsep + env.get("PATH", "")
    return env


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_verified(url: str, expected: str, target: Path) -> None:
    if target.is_file() and sha256(target) == expected:
        return
    if not url.startswith("https://"):
        raise SetupError("运行组件必须通过 HTTPS 下载。")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as handle:
            temporary = Path(handle.name)
            request = urllib.request.Request(url, headers={"User-Agent": "Ally-Legal-Flex-Setup/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response:
                shutil.copyfileobj(response, handle)
        if sha256(temporary) != expected:
            raise SetupError("下载的 SHA256 校验失败，请重新运行 Setup。")
        temporary.replace(target)
    except (OSError, urllib.error.URLError) as error:
        raise SetupError("运行组件下载失败，请检查网络后重新运行 Setup。") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe_member(name: str, destination: Path) -> None:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
        raise SetupError("运行组件压缩包包含不安全的路径。")
    if not (destination / name).resolve().is_relative_to(destination.resolve()):
        raise SetupError("运行组件压缩包包含越界路径。")


def extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as handle:
                for zip_member in handle.infolist():
                    safe_member(zip_member.filename, destination)
                    if (zip_member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise SetupError("ZIP 运行组件不应包含符号链接。")
                handle.extractall(destination)
        else:
            with tarfile.open(archive, "r:gz") as handle:
                for tar_member in handle.getmembers():
                    safe_member(tar_member.name, destination)
                    # data_filter also rejects links outside the extraction directory.
                    tarfile.data_filter(tar_member, str(destination))
                handle.extractall(destination, filter="data")
    except (tarfile.TarError, zipfile.BadZipFile, OSError, ValueError) as error:
        raise SetupError("无法安全解压运行组件，请重新运行 Setup。") from error


def run_command(command: list[str], root: Path, env: dict[str, str]) -> None:
    try:
        subprocess.run(command, cwd=root, env=env, check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise SetupError("安装步骤未完成，请检查上方提示及网络后重新运行 Setup。") from error


def ensure_node(root: Path, manifest: dict, env: dict[str, str]) -> Path:
    tools = root / ".ally-tools"
    tools.mkdir(parents=True, exist_ok=True)
    node = tools / ("node/node.exe" if os.name == "nt" else "node/bin/node")
    npm_relative = "node_modules/npm/bin/npm-cli.js" if os.name == "nt" else "lib/node_modules/npm/bin/npm-cli.js"
    if node.is_file() and (tools / "node" / npm_relative).is_file():
        try:
            probe = subprocess.run([str(node), "--version"], env=env, capture_output=True, text=True, timeout=20)
            if probe.returncode == 0 and probe.stdout.strip() == manifest["node_version"]:
                return node
        except (OSError, subprocess.TimeoutExpired):
            pass
    spec = manifest["platforms"][platform_key()]["node"]
    archive = tools / "downloads" / spec["url"].rsplit("/", 1)[-1]
    print("正在准备 Node.js……", flush=True)
    download_verified(spec["url"], spec["sha256"], archive)
    with tempfile.TemporaryDirectory(prefix="node-stage-", dir=tools) as folder:
        stage = Path(folder)
        extract_archive(archive, stage)
        directories = list(stage.iterdir())
        if len(directories) != 1 or not directories[0].is_dir():
            raise SetupError("Node.js 压缩包结构不完整。")
        source = directories[0]
        if not (source / ("node.exe" if os.name == "nt" else "bin/node")).is_file():
            raise SetupError("Node.js 压缩包缺少程序。")
        destination = tools / "node"
        backup = stage / "previous-node"
        if destination.exists():
            destination.rename(backup)
        try:
            source.rename(destination)
        except OSError:
            if backup.exists():
                backup.rename(destination)
            raise
    return node


def ensure_venv(root: Path, uv: Path, env: dict[str, str]) -> Path:
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if environment.exists():
        if not python.is_file():
            raise SetupError("已有 .venv 环境不完整，已保留。请先移走该环境，再运行 Setup。")
        result = subprocess.run(
            [str(python), "-c", "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"],
            env=env, capture_output=True, timeout=30,
        )
        if result.returncode:
            raise SetupError("已有 .venv Python 版本不适用，已保留。请移走后重新安装。")
        return python
    print("正在创建项目 Python 环境……", flush=True)
    run_command([str(uv), "venv", "--python", sys.executable, str(environment)], root, env)
    return python


def initialize_connection(root: Path, python: Path, env: dict[str, str]) -> None:
    command = [str(python), "-m", "promptflow._cli.pf", "connection"]
    try:
        result = subprocess.run(command + ["show", "--name", "ally"], cwd=root, env=env,
                                capture_output=True, timeout=60)
        if result.returncode == 0:
            return
        result = subprocess.run(command + ["create", "--file", str(
            root / "backend/PromptFlow/legal-main-flow/connection.local.yaml"
        )], cwd=root, env=env, capture_output=True, timeout=300)
        if result.returncode:
            raise SetupError("本地分析连接初始化失败。请允许系统保存本地凭据后重试 Setup。")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError("无法初始化本地分析连接。如有系统钥匙串提示，请自行允许后重试 Setup。") from error


def prepare_flow_profile(root: Path) -> None:
    profile = root / ".ally-tools/promptflow"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        # Avoid waiting for optional telemetry uploads during local installation.
        with (profile / "pf.yaml").open("x", encoding="utf-8") as handle:
            handle.write("telemetry:\n  enabled: false\n")
    except FileExistsError:
        pass


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256(str(SCHEMA).encode())
    for name in ("package.json", "package-lock.json", "scripts/runtime-downloads.json",
                 "backend/PromptFlow/legal-main-flow/requirements.txt"):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def verify_installation(root: Path, env: dict[str, str]) -> None:
    try:
        check_dependencies(root, env)
    except LaunchError as error:
        raise SetupError(f"安装检查未通过：{error} 请重新运行 Setup 修复。") from error
    if not (root / "dist/taskpane.html").is_file() or not (root / "dist/configpane.html").is_file():
        raise SetupError("插件页面尚未生成，请重新运行 Setup 修复。")


def install(root: Path, *, repair: bool = False, no_shortcut: bool = False) -> None:
    root = root.resolve()
    manifest = load_manifest(root)
    env = setup_environment(root)
    tools = root / ".ally-tools"
    tools.mkdir(parents=True, exist_ok=True)
    uv = tools / ("uv/uv.exe" if os.name == "nt" else "uv/uv")
    receipt = tools / "setup-receipt.json"
    expected = fingerprint(root)
    node = ensure_node(root, manifest, env)
    python = ensure_venv(root, uv, env)
    try:
        saved = json.loads(receipt.read_text()).get("fingerprint")
    except (OSError, ValueError, AttributeError):
        saved = None
    ready = saved == expected and not repair
    if ready:
        try:
            verify_installation(root, env)
        except SetupError:
            ready = False
    if not ready:
        receipt.unlink(missing_ok=True)
        print("正在安装合同分析组件……", flush=True)
        run_command([str(uv), "pip", "install", "--python", str(python), "-r", str(
            root / "backend/PromptFlow/legal-main-flow/requirements.txt")], root, env)
        npm = tools / "node" / ("node_modules/npm/bin/npm-cli.js" if os.name == "nt"
                                 else "lib/node_modules/npm/bin/npm-cli.js")
        print("正在安装插件页面组件……", flush=True)
        run_command([str(node), str(npm), "ci", "--include=dev", "--no-audit", "--no-fund"], root, env)
        print("正在生成插件页面……", flush=True)
        run_command([str(node), str(npm), "run", "build"], root, env)
        verify_installation(root, env)
    if not ready or not (tools / "promptflow/pf.sqlite").is_file():
        print("正在初始化本地分析连接……", flush=True)
        print("如出现系统钥匙串/凭据保存提示，请在系统窗口自行确认。", flush=True)
        prepare_flow_profile(root)
        initialize_connection(root, python, env)
    temporary = receipt.with_suffix(".tmp")
    temporary.write_text(json.dumps({"fingerprint": expected, "schema": SCHEMA}), encoding="utf-8")
    temporary.replace(receipt)
    if not no_shortcut:
        ensure_desktop_shortcut(root)
    print("\n安装完成。请双击 Start-Ally 或桌面入口启动 Word 插件。", flush=True)
    print("在 Config 中配置 Company Policies、Model Settings 和 Prompt Settings。", flush=True)


@contextmanager
def installation_lock(root: Path):
    lock = root / ".ally-tools/setup.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    # Keep the file in place: deleting it could let two owners lock different inodes.
    handle = lock.open("a+b")
    acquired = False
    try:
        if sys.platform == "win32":
            import msvcrt
            if lock.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    except OSError as error:
        if not acquired:
            raise SetupError("已有安装正在运行，或安装锁不可写。请关闭其他安装窗口后重试。") from error
        raise
    finally:
        try:
            if acquired:
                if sys.platform == "win32":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def register_interrupts() -> None:
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupted)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ally Legal Flex 项目环境安装")
    parser.add_argument("--repair", action="store_true", help="重新安装依赖，保留用户配置")
    parser.add_argument("--no-shortcut", action="store_true", help="不创建桌面入口")
    parser.add_argument("--check", action="store_true", help="只检查安装，不下载或启动服务")
    args = parser.parse_args()
    register_interrupts()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.check:
            verify_installation(root, setup_environment(root))
            print("安装检查通过。")
        else:
            with installation_lock(root):
                install(root, repair=args.repair, no_shortcut=args.no_shortcut)
        return 0
    except (SetupError, OSError, ValueError, KeyError) as error:
        print(f"\n安装未完成：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消安装。可重新双击 Setup 继续。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

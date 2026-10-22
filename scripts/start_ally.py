"""Start locally installed Ally services; stop only the process trees we start."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import datetime
import errno
import http.client
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
from typing import TextIO


PORTS = (3000, 8083, 8084, 8085)
NODE_ENTRIES = {
    "webpack": "node_modules/webpack/bin/webpack.js",
    "certs": "node_modules/office-addin-dev-certs/cli.js",
    "office": "node_modules/office-addin-debugging/cli.js",
}

# Local services in start order, with the port each one owns.
SERVICE_PORTS = {"flow": 8083, "policy": 8084, "model-settings": 8085, "web": 3000}
SERVICE_LABELS = {
    "flow": "合同分析服务",
    "policy": "Policy Set 服务",
    "model-settings": "模型配置服务",
    "web": "插件前端服务",
}

# User-facing stage names for the one-shot CLI steps the launcher runs.
INTERACTIVE_STAGES = {
    "certificates": "本地证书安装",
    "certificate-check": "本地证书校验",
    "word": "Word 插件加载",
}

# What each service exposes to prove it is really usable, not merely listening.
SERVICE_PROBES = {
    "flow": ("/health", "status", "Healthy"),
    "policy": ("/policy-sets", "policySets", None),
    "model-settings": ("/api/config", "ok", True),
    "web": ("/taskpane.html", "", None),
}

# Paths are supplied through the environment, never interpolated into PowerShell.
WINDOWS_SHORTCUT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
if ([string]::IsNullOrWhiteSpace($desktop) -or !(Test-Path -LiteralPath $desktop -PathType Container)) {
    throw 'Desktop folder not found'
}
$destination = Join-Path $desktop 'Ally Legal Flex.lnk'
if (Test-Path -LiteralPath $destination) {
    Write-Output 'existing'
    exit 0
}
$target = Join-Path $env:ALLY_SHORTCUT_PROJECT_ROOT 'Start-Ally.cmd'
if (!(Test-Path -LiteralPath $target -PathType Leaf)) {
    throw 'Project launcher not found'
}
$temporary = Join-Path $desktop ('.Ally-Legal-Flex-' + [guid]::NewGuid().ToString() + '.lnk')
try {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($temporary)
    $shortcut.TargetPath = $target
    $shortcut.WorkingDirectory = $env:ALLY_SHORTCUT_PROJECT_ROOT
    $shortcut.Description = 'Start Ally Legal Flex'
    $shortcut.Save()
    # File.Move does not overwrite a destination created by another process.
    try {
        [IO.File]::Move($temporary, $destination)
        Write-Output 'created'
    } catch {
        if (Test-Path -LiteralPath $destination) {
            Write-Output 'existing'
        } else {
            throw
        }
    }
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Force
    }
}
"""


class LaunchError(Exception):
    """An actionable setup or startup problem."""


def acquire_launcher_lock(root: Path):
    """Hold a project-wide lock so a second window cannot fight over the same ports."""
    lock_path = root / ".ally-run" / "launcher.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if lock_path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def release_launcher_lock(handle) -> None:
    if handle is None:
        return
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()



def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def find_python(root: Path, *, windows: bool | None = None) -> Path:
    windows = os.name == "nt" if windows is None else windows
    candidates = [root / ".venv" / ("Scripts/python.exe" if windows else "bin/python")]
    if not windows:
        candidates.append(root / ".venv-mac/bin/python")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise LaunchError("未找到项目的 Python 环境。请先完成使用手册中的 Python 环境和依赖安装。")


def launcher_environment(root: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for name in ("npm_package_json", "npm_package_scripts_dev_server", "npm_package_scripts_packager"):
        env.pop(name, None)
    if sys.platform == "darwin":
        env["PATH"] = env.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"
    root = project_root() if root is None else root
    node_dir = root / (".ally-tools/node" if os.name == "nt" else ".ally-tools/node/bin")
    if node_dir.is_dir():
        env["PATH"] = str(node_dir) + os.pathsep + env.get("PATH", "")
    profile = root / ".ally-tools/promptflow"
    if profile.is_dir():
        env["PF_HOME_DIRECTORY"] = str(profile)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    env["npm_package_config_dev_server_port"] = "3000"
    return env


def check_project_files(root: Path) -> None:
    if any(not (root / name).is_file() for name in NODE_ENTRIES.values()):
        raise LaunchError("插件页面组件不完整。请先按手册在项目文件夹执行 npm install。")
    for relative in ("manifest.xml", "index_server.py", "model_config_server.py",
                     "backend/PromptFlow/legal-main-flow/flow.dag.yaml"):
        if not (root / relative).is_file():
            raise LaunchError(f"项目文件缺少 {relative}，请重新解压完整项目。")


def check_dependencies(root: Path, env: dict[str, str]) -> tuple[Path, str]:
    python = find_python(root)
    node = shutil.which("node", path=env.get("PATH"))
    if not node:
        raise LaunchError("未找到 Node.js。请先按手册安装，关闭此窗口后重新双击启动。")
    check_project_files(root)
    probe = (
        "import importlib.util,sys; "
        "sys.exit(0 if sys.version_info >= (3,10) and "
        "all(importlib.util.find_spec(m) for m in ('promptflow','openai')) else 1)"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", probe], cwd=root, env=env, capture_output=True, timeout=20,
        )
        node_result = subprocess.run(
            [node, "--version"], cwd=root, env=env, capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LaunchError("Python 或 Node.js 无法运行，请按手册检查安装。") from error
    if result.returncode:
        raise LaunchError("项目 Python 环境缺少 PromptFlow / OpenAI SDK，或版本过旧。请完成手册的依赖安装。")
    if node_result.returncode:
        raise LaunchError("Node.js 无法正常运行，请按手册检查安装。")
    return python, node


def create_desktop_shortcut(root: Path, *, platform: str | None = None) -> str:
    """Create a desktop entry once, without replacing any existing user file."""
    platform = sys.platform if platform is None else platform
    root = root.resolve()
    if platform == "win32":
        env = os.environ.copy()
        env["ALLY_SHORTCUT_PROJECT_ROOT"] = str(root)
        encoded = base64.b64encode(WINDOWS_SHORTCUT_SCRIPT.encode("utf-16le")).decode("ascii")
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15, check=True,
        )
        status = result.stdout.strip()
        if status not in ("created", "existing"):
            raise OSError("无法确认桌面入口已创建")
        return status
    if platform != "darwin":
        return "unsupported"
    shortcut = Path.home() / "Desktop" / "Ally Legal Flex.command"
    target = root / "Start-Ally.command"
    try:
        handle = shortcut.open("x", encoding="utf-8")
    except FileExistsError:
        return "existing"
    try:
        with handle:
            if not target.is_file():
                raise OSError("未找到项目启动文件")
            handle.write(f'#!/bin/bash\nexec /bin/bash {shlex.quote(str(target))} "$@"\n')
            os.fchmod(handle.fileno(), 0o755)
    except OSError:
        shortcut.unlink(missing_ok=True)
        raise
    return "created"


def ensure_desktop_shortcut(root: Path) -> None:
    """A missing or unwritable desktop must not prevent normal startup."""
    try:
        status = create_desktop_shortcut(root)
    except (OSError, subprocess.SubprocessError):
        print("未能创建桌面启动入口；仍可从项目文件夹双击 Start-Ally 启动文件。")
        return
    if status == "created":
        name = "Ally Legal Flex.command" if sys.platform == "darwin" else "Ally Legal Flex"
        print(f"已创建桌面启动入口：{name}。以后可从桌面双击启动，请保持项目文件夹位置不变。")
    elif status == "existing":
        print("桌面已有同名启动入口，已保留。")


def port_owner(port: int):
    """Best-effort owner of a listening loopback port: (pid, name, command)."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        for connection in psutil.net_connections(kind="inet"):
            address = getattr(connection, "laddr", None)
            if not address or address.port != port or connection.status != psutil.CONN_LISTEN:
                continue
            if not connection.pid:
                return (None, "未知进程", "")
            try:
                process = psutil.Process(connection.pid)
                return (connection.pid, process.name(), " ".join(process.cmdline())[:400])
            except (psutil.Error, OSError):
                return (None, "未知进程", "")
    except (psutil.Error, OSError):
        return None
    return None


def port_served_by_project(port: int, root: Path) -> bool:
    """True when the listener on this port is one of this project's services."""
    owner = port_owner(port)
    if not owner:
        return False
    _pid, _name, command = owner
    lowered = command.casefold()
    if str(Path(root).resolve()).casefold() not in lowered:
        return False
    markers = {
        3000: ("webpack", "serve"),
        8083: ("promptflow", "serve"),
        8084: ("index_server.py",),
        8085: ("model_config_server.py",),
    }.get(port, ())
    return bool(markers) and all(marker in lowered for marker in markers)


def describe_port_conflict(port: int) -> str:
    owner = port_owner(port)
    if not owner:
        return f"端口 {port} 已被其他程序占用（无法读取进程信息）。"
    pid, name, command = owner
    lines = [f"端口 {port} 已被其他程序占用："]
    lines.append(f"  进程：{name}" + (f"（PID {pid}）" if pid else ""))
    if command:
        lines.append(f"  命令：{command}")
    return "\n".join(lines)


def ensure_ports_available(
    ports: tuple[int, ...] | list[int] = PORTS, root: Path | None = None
) -> set[int]:
    """Bind checks also detect an occupied port not yet accepting requests.

    Returns the ports already served by this project so they can be reused;
    anything else raises before a single process is stopped or started.
    """
    occupied = []
    reusable: set[int] = set()
    for port in ports:
        busy = False
        for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as probe:
                    if os.name == "nt":
                        probe.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE"), 1)
                    probe.bind((address, port))
            except OSError as error:
                if family == socket.AF_INET6 and error.errno in (
                    errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL, errno.EPROTONOSUPPORT,
                ):
                    continue
                busy = True
                break
        if not busy:
            continue
        if root is not None and port_served_by_project(port, root):
            reusable.add(port)
        else:
            occupied.append(port)
    if occupied:
        details = "\n".join(describe_port_conflict(port) for port in occupied)
        raise LaunchError(
            details + "\n请关闭上述程序，或先在旧的启动窗口按 Enter 结束本次启动的服务，再重试。"
            "\n本脚本不会结束其他程序的进程。"
        )
    return reusable


def process_group_options() -> dict:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP")}
    return {"start_new_session": True}


def stop_process_tree(process: subprocess.Popen, *, windows: bool | None = None) -> None:
    windows = os.name == "nt" if windows is None else windows
    if windows:
        if process.poll() is None:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=10,
            )
            if result.returncode and process.poll() is None:
                raise OSError(f"无法结束进程 {process.pid}")
        process.wait(timeout=5)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    # A group may still contain children after its parent exits.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=3)


@dataclass
class Service:
    name: str
    process: subprocess.Popen | None
    log: TextIO | None
    reused: bool = False


def tail_text(path: Path, limit: int = 1200) -> str:
    """Last lines of a service log, for an actionable failure message."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""
    text = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    if not text:
        return ""
    return text[-limit:]


class ProcessOwner:
    def __init__(self, root: Path, env: dict[str, str]):
        self.root = root
        self.env = env
        self.services: list[Service] = []
        self.log_dir = root / ".ally-run" / (
            datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
        )

    def start_service(self, name: str, command: list[str], port: int | None = None) -> None:
        # A service we already started (or one left over from an earlier session)
        # is reused instead of started twice on the same port.
        if port is not None and port_served_by_project(port, self.root):
            print(f"复用已在运行的服务：{SERVICE_LABELS.get(name, name)}（端口 {port}）。")
            self.services.append(Service(name, None, None, reused=True))
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = (self.log_dir / f"{name}.log").open("w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command, cwd=self.root, env=self.env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, **process_group_options(),
            )
        except BaseException:
            log.close()
            raise
        self.services.append(Service(name, process, log))

    def check_running(self) -> None:
        for service in self.services:
            if service.reused or service.process is None:
                continue
            if service.process.poll() is not None:
                raise LaunchError(self.failure_message(service))

    def failure_message(self, service: Service) -> str:
        log_path = self.log_dir / f"{service.name}.log"
        label = SERVICE_LABELS.get(service.name, service.name)
        code = None if service.process is None else service.process.returncode
        lines = [
            f"启动失败：{label}（{service.name}）在启动阶段退出。",
            f"  退出码：{code}",
            f"  日志：{log_path}",
        ]
        tail = tail_text(log_path)
        if tail:
            lines.append("  日志末尾：")
            lines.extend("    " + line for line in tail.splitlines()[-12:])
        if service.name == "flow":
            lines.append(
                "  常见原因：首次启动前未完成本地连接初始化，或 .venv 依赖不完整。"
                "请重新运行 Setup-Ally 后再试。"
            )
        return "\n".join(lines)

    def close(self) -> None:
        # A second Ctrl+C must not interrupt cleanup halfway through.
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            self._close_services()
        finally:
            signal.signal(signal.SIGINT, previous)

    def _close_services(self) -> None:
        for service in reversed(self.services):
            if service.reused or service.process is None or service.log is None:
                continue
            try:
                stop_process_tree(service.process)
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f"未能完全停止 {service.name}（进程 {service.process.pid}）：{error}")
            finally:
                service.log.close()
        self.services.clear()

    def interactive(self, name: str, command: list[str], timeout: int = 300) -> str:
        """Show prompts and capture output: some official CLIs exit 0 on error."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        output: list[str] = []
        with (self.log_dir / f"{name}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command, cwd=self.root, env=self.env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                **process_group_options(),
            )
            output_stream = process.stdout
            assert output_stream is not None

            def relay() -> None:
                for char in iter(lambda: output_stream.read(1), ""):
                    print(char, end="", flush=True)
                    log.write(char)
                    output.append(char)

            reader = threading.Thread(target=relay, daemon=True)
            reader.start()
            try:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    self.check_running()
                    if time.monotonic() >= deadline:
                        raise LaunchError(
                            f"启动失败：{INTERACTIVE_STAGES.get(name, name)}（{name}）等待超时。"
                            f"\n  日志：{self.log_dir / (name + '.log')}"
                            "\n  请按窗口中的系统提示完成操作后重新启动。"
                        )
                    time.sleep(0.2)
                reader.join(timeout=5)
                if process.returncode:
                    log_path = self.log_dir / f"{name}.log"
                    tail = tail_text(log_path)
                    message = [
                        f"启动失败：{INTERACTIVE_STAGES.get(name, name)}（{name}）未能完成。",
                        f"  退出码：{process.returncode}",
                        f"  日志：{log_path}",
                    ]
                    if tail:
                        message.append("  日志末尾：")
                        message.extend("    " + line for line in tail.splitlines()[-10:])
                    raise LaunchError("\n".join(message))
                return "".join(output)
            finally:
                try:
                    if process.poll() is None:
                        stop_process_tree(process)
                finally:
                    reader.join(timeout=5)
                    output_stream.close()


WEB_COMPILE_ERRORS = re.compile(
    r"compiled with errors|Module not found|ERROR in |Failed to compile", re.IGNORECASE
)


def web_compile_failure(log_dir: Path) -> str:
    """Real webpack error text, so a build failure is never reported as a Word problem."""
    text = tail_text(log_dir / "web.log", 4000)
    if not text:
        return ""
    lines = [line for line in text.splitlines() if WEB_COMPILE_ERRORS.search(line)]
    return "\n".join(lines[-8:])


def probe_service(name: str, port: int) -> tuple[bool, str]:
    """Verify a service through the route it actually exposes, not just its port."""
    if name == "web":
        # Only this loopback probe bypasses Python's CA store. Office trust is
        # verified separately before any service is started.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection("127.0.0.1", port, timeout=2, context=context)
    else:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    path, key, expected = SERVICE_PROBES.get(name, ("/", "", None))
    try:
        connection.request("GET", path, headers={"Host": f"localhost:{port}"})
        response = connection.getresponse()
        raw = response.read(256 * 1024)
        if response.status != 200:
            # A 404 at "/" says nothing; only the documented route is meaningful.
            return False, f"{path} 返回 HTTP {response.status}"
        if name == "web":
            body = raw.decode("utf-8", "replace")
            if "taskpane" not in body.casefold():
                return False, f"{path} 返回的不是插件页面"
            return True, "插件页面可访问"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return False, f"{path} 返回了非对象 JSON"
        value = payload.get(key)
        if expected is None:
            ok = isinstance(value, list)
        else:
            ok = value == expected
        return (True, f"{path} 可用") if ok else (False, f"{path} 返回内容不符合预期")
    except (OSError, http.client.HTTPException, ValueError) as error:
        return False, type(error).__name__
    finally:
        connection.close()


def wait_for_services(owner: ProcessOwner, timeout: int = 180) -> None:
    """Wait until every service answers on its own route; fail with the real reason."""
    deadline = time.monotonic() + timeout
    pending: list[str] = list(SERVICE_PORTS)
    details: dict[str, str] = {}
    while time.monotonic() < deadline:
        owner.check_running()
        pending = []
        for name, port in SERVICE_PORTS.items():
            ok, detail = probe_service(name, port)
            if ok:
                details.pop(name, None)
                continue
            pending.append(name)
            details[name] = detail
        if not pending:
            return
        if "web" in pending:
            compile_error = web_compile_failure(owner.log_dir)
            if compile_error:
                raise LaunchError(
                    "启动失败：插件前端编译报错（服务进程可能仍在运行）。\n"
                    + "\n".join("  " + line for line in compile_error.splitlines())
                    + f"\n  完整日志：{owner.log_dir / 'web.log'}"
                )
        time.sleep(0.75)
    lines = [f"启动失败：本地服务在 {timeout} 秒内未全部就绪。"]
    for name in pending:
        lines.append(
            f"  - {SERVICE_LABELS.get(name, name)}（端口 {SERVICE_PORTS[name]}）：{details.get(name, '无响应')}"
        )
    for name in SERVICE_PORTS:
        if name not in pending:
            lines.append(f"  - {SERVICE_LABELS.get(name, name)}（端口 {SERVICE_PORTS[name]}）：已就绪")
    lines.append(f"  日志目录：{owner.log_dir}")
    raise LaunchError("\n".join(lines))



def office_started(output: str) -> bool:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    relevant = office_essential_output(plain)
    return bool(re.search(r"(?m)^Started\.\s*$", relevant)) and not re.search(
        r"Unable to |Failed to |\bError:", relevant, re.IGNORECASE,
    )


# office-addin-debugging reports this warning and then sideloads successfully anyway.
# It only needs an elevated shell once, so a non-admin run must not be treated as a failure.
LOOPBACK_WARNING = re.compile(
    r"Failed to add loopback exemption\.|Will try to sideload the Office Add-in",
    re.IGNORECASE,
)

LOOPBACK_EXEMPTION_NAME = "1_https___localhost_3000_04ACA5EC-D79A-43EA-AB47-E50E47DD96FC"


def office_essential_output(plain: str) -> str:
    """Drop warnings that do not change whether the add-in was sideloaded."""
    return "\n".join(line for line in plain.splitlines() if not LOOPBACK_WARNING.search(line))


def office_needs_loopback_exemption(output: str) -> bool:
    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return bool(LOOPBACK_WARNING.search(plain))


def warn_missing_loopback_exemption() -> None:
    print("\n提示：本次未能自动添加 WebView2 的 localhost 回环豁免（该步骤需要管理员权限）。")
    print("      插件已经载入，但侧边栏可能空白或提示无法连接。请二选一修复后重新启动：")
    print("      1) 关闭窗口，右键 Start-Ally.cmd，选择“以管理员身份运行”一次；")
    print("      2) 用管理员身份打开 PowerShell，执行：")
    print(f"         CheckNetIsolation.exe LoopbackExempt -a -n=\"{LOOPBACK_EXEMPTION_NAME}\"")


def run_launcher(root: Path, *, check_only: bool = False) -> int:
    print("Ally Legal Flex 本地启动器")
    print("正在检查已安装环境和本地端口……")
    env = launcher_environment()
    python, node = check_dependencies(root, env)
    ensure_ports_available()
    if check_only:
        print("检查通过：已找到所需环境，3000、8083、8084、8085 端口可用。")
        print("本次未启动服务或 Word；未验证证书、连接初始化和模型配置。")
        return 0
    ensure_desktop_shortcut(root)
    lock = acquire_launcher_lock(root)
    if lock is None:
        raise LaunchError(
            "已有另一个 Ally Legal Flex 启动器窗口在运行。\n"
            "  请回到那个窗口继续使用；或先在它的窗口按 Enter 结束，再重新启动。\n"
            "  两个窗口同时启动会争用同一批端口，导致插件无法打开。"
        )
    owner = ProcessOwner(root, env)
    try:
        print("正在检查本地证书；首次运行时，请按系统提示允许安装并输入电脑密码。")
        owner.interactive("certificates", [node, str(root / NODE_ENTRIES["certs"]), "install"])
        verify = (
            "try { process.exit(require('office-addin-dev-certs').verifyCertificates() ? 0 : 1); } "
            "catch (_) { process.exit(1); }"
        )
        owner.interactive("certificate-check", [node, "-e", verify], timeout=30)
        ensure_ports_available(root=root)
        print("正在启动分析、规则、模型设置和插件页面服务，请稍候……")
        owner.start_service("flow", [
            str(python), "-m", "promptflow._cli.pf", "flow", "serve", "--source",
            str(root / "backend/PromptFlow/legal-main-flow"), "--port", "8083",
            "--host", "127.0.0.1", "--skip-open-browser",
        ], port=SERVICE_PORTS["flow"])
        owner.start_service("policy", [str(python), str(root / "index_server.py")],
                            port=SERVICE_PORTS["policy"])
        owner.start_service("model-settings", [str(python), str(root / "model_config_server.py")],
                            port=SERVICE_PORTS["model-settings"])
        owner.start_service("web", [
            node, str(root / NODE_ENTRIES["webpack"]), "serve", "--mode", "development",
            "--port", "3000", "--host", "127.0.0.1",
        ], port=SERVICE_PORTS["web"])
        print("正在等待四个本地服务就绪（逐个检查实际接口，不只看端口）……")
        wait_for_services(owner)
        print("本地服务已就绪：8083 合同分析、8084 策略、8085 模型配置、3000 插件页面。")
        print("正在打开 Word 并载入插件；如出现本机访问许可提示，请按提示确认。")
        output = owner.interactive("word", [
            node, str(root / NODE_ENTRIES["office"]), "start", str(root / "manifest.xml"),
            "desktop", "--app", "word", "--dev-server-port", "3000",
            "--no-debug", "--no-live-reload",
        ])
        if not office_started(output):
            raise LaunchError(
                "本地服务已就绪，但 Word 插件未能确认载入。\n"
                f"  阶段：Word 插件加载\n  日志：{owner.log_dir / 'word.log'}\n"
                "  请确认已安装桌面版 Word；若 Word 已打开但侧边栏空白，请先按上面提示处理回环豁免。"
            )
        if office_needs_loopback_exemption(output):
            warn_missing_loopback_exemption()
        owner.check_running()
        print("\n启动完成。请在 Word 文档中点击：开始 → Ally Legal Flex。")
        print("请保留这个窗口。结束使用时，先保存文档并等待 AI 分析完成，再回到这里按 Enter。")
        print("按 Enter 将停止本次启动的服务，不会关闭 Word 或卸载插件。")
        print(f"本次日志：{owner.log_dir}")
        done = threading.Event()

        def wait_for_enter() -> None:
            sys.stdin.readline()
            done.set()

        threading.Thread(target=wait_for_enter, daemon=True).start()
        while not done.wait(0.5):
            owner.check_running()
        return 0
    finally:
        print("正在结束本次启动的服务……")
        owner.close()
        release_launcher_lock(lock)
        print("启动器已结束。Word 文档保持打开；下次使用时重新双击启动。")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ally Legal Flex 本地启动器")
    parser.add_argument("--check", action="store_true", help="只检查依赖和端口，不启动任何服务")
    args = parser.parse_args()

    def interrupted(_signum, _frame) -> None:
        raise KeyboardInterrupt

    for signal_name in ("SIGTERM", "SIGHUP", "SIGBREAK"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), interrupted)
    try:
        return run_launcher(project_root(), check_only=args.check)
    except KeyboardInterrupt:
        print("\n已取消启动或结束运行。")
        return 0
    except (LaunchError, OSError, subprocess.TimeoutExpired) as error:
        print(f"\n未能启动：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

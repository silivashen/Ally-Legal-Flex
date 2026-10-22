"""Build a clean source release package.

Only explicitly listed paths are copied, so runtime state (`.venv`, `node_modules`,
`.ally-run`), personal configuration (`model_config.json`) and logs can never end up
in a published archive. The archive is then re-opened and checked again.
"""
from __future__ import annotations

import argparse
from datetime import date
import fnmatch
import hashlib
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.0"

# Everything the source release contains. Add new top-level files here, otherwise
# they will silently be left out - that is the intended failure mode.
INCLUDE = [
    "assets",
    "backend",
    "docs",
    "files",
    "scripts",
    "src",
    "tests",
    ".eslintrc.json",
    ".gitattributes",
    ".gitignore",
    "LICENSE",
    "LICENSE.docx",
    "README.docx",
    "README.md",
    "SECURITY.md",
    "START_HERE.txt",
    "Setup-Ally.cmd",
    "Setup-Ally.command",
    "Start-Ally.cmd",
    "Start-Ally.command",
    "Start-Ally.ps1",
    "THIRD_PARTY_NOTICES.docx",
    "THIRD_PARTY_NOTICES.md",
    "USER_GUIDE.zh-CN.md",
    "babel.config.json",
    "index_server.py",
    "local_api_security.py",
    "manifest.xml",
    "model_config.example.json",
    "model_config_server.py",
    "package-lock.json",
    "package.json",
    "policy.json",
    "policy_excel.py",
    "policy_sets.json",
    "webpack.config.js",
    "使用手册.docx",
]

# Never published, even if a listed directory contains them.
EXCLUDED_DIRS = {
    ".venv", ".venv-mac", "node_modules", ".ally-tools", ".ally-run",
    "dist", "__pycache__", ".git", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".audit-tmp", ".ally-contract-index", ".ally-vector-cache",
}
EXCLUDED_FILES = [
    "model_config.json", "model_config.json.*", "prompt_settings.json",
    "prompt_settings_*.tmp", "contract_index.json", "policy_sets.local.json",
    "local_*_embeddings.json", "local_*_data.json", "local_bge_m3_policy.json",
    "*.log", "*.pyc", "*.pyo", "*.tmp", "*.bak*", "*.orig", "*.rej",
    ".DS_Store", "~$*", ".env", ".env.*", "launcher.lock",
]
MAX_FILE_BYTES = 8 * 1024 * 1024


def is_excluded(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDED_FILES)


def collect() -> list[Path]:
    files: list[Path] = []
    missing: list[str] = []
    for entry in INCLUDE:
        target = ROOT / entry
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(p for p in target.rglob("*") if p.is_file() and not is_excluded(p))
        else:
            missing.append(entry)
    if missing:
        raise SystemExit("发布清单中的条目不存在：" + "、".join(missing))
    return sorted(files)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(output: Path) -> tuple[Path, Path]:
    files = collect()
    oversized = [f for f in files if f.stat().st_size > MAX_FILE_BYTES]
    if oversized:
        raise SystemExit("以下文件超过 8 MB，请确认是否应随源码发布：" +
                         "、".join(str(p.relative_to(ROOT)) for p in oversized))

    name = f"Ally-Legal-Flex-{VERSION}"
    folder = output / name
    if folder.exists():
        shutil.rmtree(folder)
    for source in files:
        destination = folder / source.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    archive = output / f"{name}-source-{date.today():%Y%m%d}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        for source in sorted(folder.rglob("*")):
            if source.is_file():
                handle.write(source, source.relative_to(output).as_posix())
    return archive, folder


def verify(archive: Path) -> int:
    """Re-open the archive: nothing private may have slipped through."""
    with zipfile.ZipFile(archive) as handle:
        names = [n for n in handle.namelist() if not n.endswith("/")]
    leaked = [
        n for n in names
        if any(part in EXCLUDED_DIRS for part in n.split("/"))
        or any(fnmatch.fnmatch(n.rsplit("/", 1)[-1], pattern) for pattern in EXCLUDED_FILES)
    ]
    if leaked:
        raise SystemExit("发布包中出现了不该发布的文件：\n  " + "\n  ".join(leaked[:20]))
    return len(names)


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Ally Legal Flex 源码发布包")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "Ally-Legal-Flex-release")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    archive, folder = build(args.output)
    count = verify(archive)
    digest = sha256(archive)

    print(f"发布目录：{folder}")
    print(f"压缩包：  {archive}")
    print(f"文件数：  {count}")
    print(f"大小：    {archive.stat().st_size / 1e6:.2f} MB")
    print(f"SHA256：  {digest}")
    print(f"校验：    未发现运行时产物或私有配置（{count} 个条目）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

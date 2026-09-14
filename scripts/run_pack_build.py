#!/usr/bin/env python3
"""内容包自带构建脚本通用入口（E3 · 框架侧 · 通用）。

依据：``docs/游戏包扩展点_方案_E.md`` §三 E3（测试与构建脚本约定）。

约定：``content/<pack>/scripts/build.py`` 是包自带构建/校验管线的**入口**；框架只认这个
入口（不规定内部结构）。本脚本调用它，并**如实转发退出码与输出**。

用法::

    python scripts/run_pack_build.py --pack <名> [--content-root <目录>] [--check]

- ``--pack``：包目录名（``<content-root>/<名>``）；
- ``--content-root``：内容根目录（缺省 ``<仓库根>/content``；测试/换根用）；
- ``--check``：透传给 ``build.py --check``（只校验不写盘）；
- ``--`` 之后的参数**原样**透传给 ``build.py``。

调用约定（写入扩展作者文档）：
- 以包目录为工作目录（``cwd = content/<pack>``）执行，包内相对路径可自理；
- 环境里 ``PYTHONPATH`` 含仓库根，``build.py`` 可 import ``qbot_rpg.testing`` 等辅助；
- 退出码语义：``0`` = 成功；**非 0 原样返回**（如构建脚本 ``exit 3`` → 本入口 ``exit 3``）。

本脚本不认识任何包名，只认入口约定（换包零改动）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

__all__ = ["PackBuildResult", "main", "run_pack_build"]

#: 包构建入口（包目录相对路径；框架只认这一处）。
BUILD_ENTRY = "build.py"


def _repo_root() -> Path:
    """仓库根（本脚本在 ``<仓库根>/scripts/`` 下）。"""
    return Path(__file__).resolve().parents[1]


def _split_passthrough(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    """以 ``--`` 切分：前半是本脚本参数，后半原样透传 ``build.py``。"""
    args = list(argv)
    if "--" in args:
        idx = args.index("--")
        return args[:idx], args[idx + 1:]
    return args, []


@dataclass(frozen=True)
class PackBuildResult:
    """一次「跑包构建」的结果（退出码如实转发）。"""

    pack: str
    content_root: Path
    pack_dir: Optional[Path] = None
    build_entry: Optional[Path] = None
    exit_code: int = 1
    error: str = ""

    @property
    def ok(self) -> bool:
        """成功 = 未发生目录错误且退出码为 0。"""
        return not self.error and self.exit_code == 0


def run_pack_build(
    pack: str,
    *,
    content_root: Optional[Any] = None,
    check: bool = False,
    extra_args: Sequence[str] = (),
    repo_root: Optional[Any] = None,
    python: Optional[str] = None,
) -> PackBuildResult:
    """调用 ``<content_root>/<pack>/scripts/build.py``（输出/退出码如实转发）。

    入参 pack: 包名；content_root: 内容根（缺省 ``<仓库根>/content``）；check: 传
    ``--check``；extra_args: 透传；repo_root/python: 便于测试注入。
    出参 :class:`PackBuildResult`。目录缺失/入口缺失 → ``error`` + 退出码 1（人话，
    不抛栈）；否则退出码 = 构建脚本真实退出码。
    """
    repo = Path(repo_root) if repo_root is not None else _repo_root()
    root = Path(content_root) if content_root is not None else repo / "content"
    if not root.is_dir():
        return PackBuildResult(pack=pack, content_root=root, error=f"内容根目录不存在：{root}")
    pack_dir = root / str(pack)
    if not pack_dir.is_dir():
        return PackBuildResult(
            pack=pack, content_root=root,
            error=f"未找到内容包「{pack}」（内容根 {root} 下没有该目录）",
        )
    entry = pack_dir / "scripts" / BUILD_ENTRY
    if not entry.is_file():
        return PackBuildResult(
            pack=pack, content_root=root, pack_dir=pack_dir,
            error=(
                f"内容包「{pack}」没有构建入口 {pack_dir / 'scripts' / BUILD_ENTRY}"
                "（约定：content/<pack>/scripts/build.py，须支持 --check）"
            ),
        )

    exe = python or sys.executable
    cmd: List[str] = [exe, str(entry)]
    if check:
        cmd.append("--check")
    cmd += list(extra_args)

    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    prev = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(repo) + (os.pathsep + prev if prev else "")

    try:
        proc = subprocess.run(cmd, cwd=str(pack_dir), env=env)
    except OSError as exc:
        return PackBuildResult(
            pack=pack, content_root=root, pack_dir=pack_dir, build_entry=entry,
            error=f"无法启动构建脚本（{exe}）：{type(exc).__name__}: {exc}",
        )
    return PackBuildResult(
        pack=pack, content_root=root, pack_dir=pack_dir, build_entry=entry,
        exit_code=int(proc.returncode),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口：转发构建脚本退出码；目录/入口错误 → 1（人话）。"""
    own, passthrough = _split_passthrough(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="run_pack_build.py",
        description="调用内容包自带构建入口 content/<pack>/scripts/build.py（如实转发退出码/输出）",
    )
    parser.add_argument("--pack", required=True, help="内容包目录名（<content-root>/<名>）")
    parser.add_argument(
        "--content-root", default=None, help="内容根目录（缺省 <仓库根>/content）"
    )
    parser.add_argument(
        "--check", action="store_true", help="透传 build.py --check（只校验不写盘）"
    )
    args = parser.parse_args(own)

    print(f"[run_pack_build] 内容包：{args.pack}（模式={'check' if args.check else 'build'}）")
    result = run_pack_build(
        args.pack, content_root=args.content_root, check=args.check, extra_args=passthrough
    )
    if result.error:
        print(f"[run_pack_build] 错误：{result.error}", file=sys.stderr)
        return 1
    state = "✓ 成功" if result.ok else "✗ 失败"
    print(f"[run_pack_build] build.py 退出码 {result.exit_code}（{state}）")
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

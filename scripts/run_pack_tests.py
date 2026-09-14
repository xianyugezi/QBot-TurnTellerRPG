#!/usr/bin/env python3
"""内容包自带测试通用入口（E3 · 框架侧 · 通用）。

依据：``docs/游戏包扩展点_方案_E.md`` §三 E3（测试与构建脚本约定）。

约定：``content/<pack>/tests/`` 是包自带测试（pytest 风格）。本脚本以**该包为内容根**
跑它的 ``tests/``，**退出码 0/1 如实反映成败**，并给人话输出（收集数 + 失败摘要）。

用法::

    python scripts/run_pack_tests.py --pack <名> [--content-root <目录>] [-- -k 表达式]

- ``--pack``：包目录名（``<content-root>/<名>``）；
- ``--content-root``：内容根目录（缺省 ``<仓库根>/content``；测试/换根用）；
- ``--`` 之后的参数**原样**透传给 pytest（如 ``-- -k 某表达式``）。

隔离与纪律：
- 主套件（无参 ``pytest``）仍只跑仓库 ``tests/``（``pytest.ini`` 的 testpaths 不变），
  包测试**不会**被主套件自动收集；本脚本显式只收该包的 ``tests/``；
- 跑包测试**不写真实内容包 / 玩家库**：子进程设 ``PYTHONDONTWRITEBYTECODE=1``
  并关 pytest cacheprovider（不落 ``__pycache__`` / ``.pytest_cache``）；
- 本脚本不认识任何包名，只认目录约定（换包零改动）。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

__all__ = ["PackTestsResult", "main", "run_pack_tests"]

#: pytest 收集数（``N tests collected``）与失败行（``FAILED ...`` / ``ERROR ...``）。
_COLLECTED_RE = re.compile(r"(\d+)\s+tests?\s+collected", re.IGNORECASE)
_FAILED_RE = re.compile(r"^(FAILED|ERROR)\s+(.+)$", re.MULTILINE)

#: 失败摘要最多输出的行数（人话输出保持精炼）。
_MAX_FAIL_LINES = 20


def _repo_root() -> Path:
    """仓库根（本脚本在 ``<仓库根>/scripts/`` 下）。"""
    return Path(__file__).resolve().parents[1]


def _split_passthrough(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    """以 ``--`` 切分：前半是本脚本参数，后半原样透传 pytest。"""
    args = list(argv)
    if "--" in args:
        idx = args.index("--")
        return args[:idx], args[idx + 1:]
    return args, []


def _pytest_env(repo_root: Path) -> dict:
    """子进程环境：仓库根进 PYTHONPATH + 禁字节码/缓存写入；清 PYTEST_ADDOPTS 保确定性。"""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_ADDOPTS"] = ""
    prev = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + prev if prev else "")
    return env


def _pytest_cmd(
    exe: str,
    repo_root: Path,
    tests_dir: Path,
    pack_dir: Path,
    extra: Sequence[str],
    collect_only: bool,
) -> List[str]:
    """构造 pytest 命令：显式 rootdir/config + 插件 + 只收该包 tests/。"""
    cmd = [
        exe, "-m", "pytest", str(tests_dir),
        "-q", "--tb=short",
        "-p", "no:cacheprovider",
        "-p", "qbot_rpg.testing.pytest_plugin",
        "--rootdir", str(repo_root),
        "-o", "addopts=",
        "--pack-root", str(pack_dir),
    ]
    ini = repo_root / "pytest.ini"
    if ini.is_file():
        cmd += ["-c", str(ini)]
    else:  # 退化：无仓库 ini 时至少保证 async 用例可跑
        cmd += ["-o", "asyncio_mode=auto"]
    cmd.append("--collect-only" if collect_only else "-rf")
    cmd += list(extra)
    return cmd


def _parse_collected(output: str) -> int:
    """从收集输出里取收集数；解析不到时按「每行一个 nodeid」兜底计数。"""
    match = _COLLECTED_RE.search(output)
    if match:
        return int(match.group(1))
    if "no tests ran" in output:
        return 0
    return sum(1 for line in output.splitlines() if "::" in line and not line.startswith(" "))


def _failure_summary(output: str) -> str:
    """从 pytest 输出抽取失败/错误行（最多 :data:`_MAX_FAIL_LINES` 行）。"""
    lines = [f"{kind} {rest}".strip() for kind, rest in _FAILED_RE.findall(output)]
    if not lines:
        return ""
    if len(lines) > _MAX_FAIL_LINES:
        lines = lines[:_MAX_FAIL_LINES] + [f"…（另有 {len(lines) - _MAX_FAIL_LINES} 条省略）"]
    return "\n".join(lines)


@dataclass(frozen=True)
class PackTestsResult:
    """一次「跑包测试」的结果（人话输出与退出码都从这里出）。"""

    pack: str
    content_root: Path
    pack_dir: Optional[Path] = None
    tests_dir: Optional[Path] = None
    ok: bool = False
    exit_code: int = 1
    collected: int = 0
    output: str = ""
    failure_summary: str = ""
    error: str = ""

    @property
    def summary_line(self) -> str:
        """结果单行摘要（人话）。"""
        if self.error:
            return self.error
        return f"收集 {self.collected} 个测试；pytest 退出码 {self.exit_code}"


def run_pack_tests(
    pack: str,
    *,
    content_root: Optional[Any] = None,
    extra_args: Sequence[str] = (),
    repo_root: Optional[Any] = None,
    python: Optional[str] = None,
) -> PackTestsResult:
    """跑 ``<content_root>/<pack>/tests/``（显式只收该目录；退出码 0/1）。

    入参 pack: 包名；content_root: 内容根（缺省 ``<仓库根>/content``）；extra_args:
    透传 pytest 的参数；repo_root/python: 便于测试注入。出参 :class:`PackTestsResult`。
    核心逻辑：解析目录（不存在 → 人话 error）→ 收集一遍取收集数 → 真跑一遍取退出码与
    失败摘要 → ``ok = 退出码 == 0``。
    """
    repo = Path(repo_root) if repo_root is not None else _repo_root()
    root = Path(content_root) if content_root is not None else repo / "content"
    if not root.is_dir():
        return PackTestsResult(
            pack=pack, content_root=root, error=f"内容根目录不存在：{root}",
        )
    pack_dir = root / str(pack)
    if not pack_dir.is_dir():
        return PackTestsResult(
            pack=pack, content_root=root,
            error=f"未找到内容包「{pack}」（内容根 {root} 下没有该目录）",
        )
    tests_dir = pack_dir / "tests"
    if not tests_dir.is_dir():
        return PackTestsResult(
            pack=pack, content_root=root, pack_dir=pack_dir,
            error=f"内容包「{pack}」没有 tests/ 目录（约定：{pack_dir / 'tests'}）",
        )

    exe = python or sys.executable
    env = _pytest_env(repo)

    def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            list(cmd), cwd=str(repo), env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )

    try:
        collect = _run(_pytest_cmd(exe, repo, tests_dir, pack_dir, extra_args, True))
        collected = _parse_collected(collect.stdout + collect.stderr)
        proc = _run(_pytest_cmd(exe, repo, tests_dir, pack_dir, extra_args, False))
    except OSError as exc:
        return PackTestsResult(
            pack=pack, content_root=root, pack_dir=pack_dir, tests_dir=tests_dir,
            error=f"无法启动 pytest（{exe}）：{type(exc).__name__}: {exc}",
        )

    output = proc.stdout + proc.stderr
    return PackTestsResult(
        pack=pack, content_root=root, pack_dir=pack_dir, tests_dir=tests_dir,
        ok=proc.returncode == 0, exit_code=proc.returncode, collected=collected,
        output=output, failure_summary=_failure_summary(output),
    )


def _print_report(result: PackTestsResult, stream: Any = sys.stderr) -> None:
    """人话报告（错误走 stderr；正常输出在 main 里打印）。"""
    if result.error:
        print(f"[run_pack_tests] 错误：{result.error}", file=stream)
        if result.pack_dir is not None:
            hint = f"{result.pack_dir}/tests/test_*.py"
            print(f"[run_pack_tests] 提示：内容包应形如 {hint}", file=stream)
        return
    print(f"[run_pack_tests] 内容包：{result.pack}（{result.pack_dir}）")
    print(f"[run_pack_tests] 收集到 {result.collected} 个测试")
    if result.output.strip():
        print(result.output.rstrip())
    print(f"[run_pack_tests] 结果：pytest 退出码 {result.exit_code}（{result.summary_line}）")
    if not result.ok and result.failure_summary:
        print("[run_pack_tests] 失败摘要：")
        print("\n".join("  " + line for line in result.failure_summary.splitlines()))
    print(f"[run_pack_tests] {'✓ 通过' if result.ok else '✗ 失败'}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口：返回 0（通过）/ 1（失败或目录不合法）。"""
    own, passthrough = _split_passthrough(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="run_pack_tests.py",
        description="跑内容包自带测试 content/<pack>/tests/（退出码 0/1）",
    )
    parser.add_argument("--pack", required=True, help="内容包目录名（<content-root>/<名>）")
    parser.add_argument("--content-root", default=None, help="内容根目录（缺省 <仓库根>/content）")
    args = parser.parse_args(own)

    result = run_pack_tests(
        args.pack, content_root=args.content_root, extra_args=passthrough
    )
    _print_report(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

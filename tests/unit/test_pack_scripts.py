"""内容包自带测试/构建脚本约定（E3）单测。

覆盖（对照 docs/游戏包扩展点_方案_E.md §三 E3 与任务验收）：
- ``scripts/run_pack_tests.py``：探针包跑通（收集数 > 0、退出码 0）；故意失败包 → 退出码 1
  且输出含失败摘要；``--pack`` 不存在 → 人话报错（非堆栈）；tests/ 缺失 → 人话提示；
  ``--`` 之后的 pytest 参数原样透传；
- ``scripts/run_pack_build.py``：探针包 ``--check`` 跑通；构建脚本缺失 → 人话提示（不崩）；
  构建脚本失败 → 退出码与输出如实转发；
- **主套件隔离**：``pytest.ini`` 的 testpaths 仍是 tests；无参 ``pytest --collect-only``
  的收集集合不含 ``content/``；
- **通用性**：另一个最小包（tmp，同结构 tests/scripts）同样跑通（与包名无关）；
- **只读纪律**：跑包测试不写真实内容包（快照前后一致）；测试辅助用内存库；
- **红线**：新增框架件（qbot_rpg/testing/** 与两个入口脚本）不含包名/包专属业务词。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import qbot_rpg.testing as pkt

REPO = Path(__file__).resolve().parents[2]
RUN_TESTS = REPO / "scripts" / "run_pack_tests.py"
RUN_BUILD = REPO / "scripts" / "run_pack_build.py"
PROBE = REPO / "content" / "zz_probe_ext"

_FAIL_SRC = """\
def test_ok():
    assert True


def test_boom():
    assert 1 == 2, "MARK_FAIL_ZZ"
"""

_GENERIC_TEST_SRC = """\
import qbot_rpg.testing as pkt


def test_pack_root_fixture(pack_root):
    assert (pack_root / "manifest.json").is_file()


async def test_command_via_fixture(pack_deps):
    assert pack_deps.pack_ext_result.ok
    out = await pkt.send_command(pack_deps, "通用指令 甲")
    assert out.startswith("GEN:")


async def test_command_via_pack_app():
    async with pkt.pack_app(pkt.pack_root_from(__file__)) as deps:
        out = await pkt.send_command(deps, "gencmd 乙")
    assert "乙" in out
"""


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    """以当前解释器跑入口脚本（真实退出码/输出）。"""
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=str(REPO),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _write_failing_pack(root: Path, pack: str) -> Path:
    tests = root / pack / "tests"
    tests.mkdir(parents=True)
    (tests / "test_fail.py").write_text(_FAIL_SRC, encoding="utf-8")
    return root / pack


def _write_generic_pack(root: Path, pack: str) -> Path:
    """落一个与探针包同结构、但完全不同名的最小包（证明与包名无关）。"""
    pd = root / pack
    (pd / "ext").mkdir(parents=True)
    (pd / "tests").mkdir(parents=True)
    (pd / "manifest.json").write_text(
        json.dumps(
            {"name": "通用最小包", "version": "0.1.0", "schema_version": 1,
             "author": "unit-test", "modules": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pd / "commands.json").write_text(
        json.dumps(
            {"commands": [{"name": "通用指令", "aliases": ["gencmd"], "handler": "go"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pd / "ext" / "commands.py").write_text(
        "def go(ctx, parsed):\n"
        "    return 'GEN:' + ctx.pack_id + ':' + ctx.args_text\n",
        encoding="utf-8",
    )
    (pd / "tests" / "test_generic.py").write_text(_GENERIC_TEST_SRC, encoding="utf-8")
    return pd


def _snapshot(root: Path) -> dict:
    """文件树快照（相对路径 → 大小 + mtime）；用于只读纪律断言。"""
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


# =============================================================================
# run_pack_tests.py
# =============================================================================
def test_run_pack_tests_probe_passes() -> None:
    """探针包自带测试：收集数 > 0、退出码 0、人话摘要」。"""
    proc = _run(RUN_TESTS, "--pack", "zz_probe_ext")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    match = re.search(r"收集到 (\d+) 个测试", proc.stdout)
    assert match is not None, proc.stdout
    assert int(match.group(1)) > 0
    assert "✓ 通过" in proc.stdout


def test_run_pack_tests_passthrough_pytest_args() -> None:
    """``--`` 之后的 pytest 参数（-k）原样透传：命中 1 个、其余 deselected。"""
    proc = _run(RUN_TESTS, "--pack", "zz_probe_ext", "--", "-k", "render")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout
    assert "deselected" in proc.stdout
    match = re.search(r"收集到 (\d+) 个测试", proc.stdout)
    assert match is not None and int(match.group(1)) > 1, proc.stdout


def test_run_pack_tests_failing_pack_exit_one_and_summary(tmp_path: Path) -> None:
    """故意失败的临时包 → 退出码 1，输出含失败摘要（含断言原文）。"""
    _write_failing_pack(tmp_path, "zz_fail")
    proc = _run(RUN_TESTS, "--pack", "zz_fail", "--content-root", str(tmp_path))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "失败摘要" in combined
    assert "MARK_FAIL_ZZ" in combined


def test_run_pack_tests_missing_pack_is_human_error(tmp_path: Path) -> None:
    """包不存在 → 人话报错、退出码非 0、无堆栈。"""
    proc = _run(RUN_TESTS, "--pack", "no_such_pack_zz", "--content-root", str(tmp_path))
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "未找到内容包" in combined
    assert "Traceback" not in combined


def test_run_pack_tests_missing_tests_dir_is_human_error(tmp_path: Path) -> None:
    """包在但无 tests/ → 人话提示、不改契约。"""
    (tmp_path / "zz_empty").mkdir()
    proc = _run(RUN_TESTS, "--pack", "zz_empty", "--content-root", str(tmp_path))
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "没有 tests/ 目录" in combined
    assert "Traceback" not in combined


# =============================================================================
# run_pack_build.py
# =============================================================================
def test_run_pack_build_probe_check_passes() -> None:
    """探针包 ``build.py --check``：退出码 0、输出摘要、明确未写盘。"""
    proc = _run(RUN_BUILD, "--pack", "zz_probe_ext", "--check")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "校验通过" in proc.stdout
    assert "未写盘" in proc.stdout


def test_run_pack_build_missing_entry_is_human_error(tmp_path: Path) -> None:
    """构建入口缺失 → 人话提示（不崩）、退出码 1、无堆栈。"""
    (tmp_path / "zz_nobuild").mkdir()
    proc = _run(RUN_BUILD, "--pack", "zz_nobuild", "--content-root", str(tmp_path), "--check")
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "没有构建入口" in combined
    assert "Traceback" not in combined


def test_run_pack_build_forwards_exit_code_and_output(tmp_path: Path) -> None:
    """构建脚本失败 → 退出码与输出如实转发（此处 4）。"""
    scripts = tmp_path / "zz_badbuild" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "build.py").write_text(
        "import sys\nprint('BUILD_OUT_ZZ')\nsys.exit(4)\n", encoding="utf-8"
    )
    proc = _run(RUN_BUILD, "--pack", "zz_badbuild", "--content-root", str(tmp_path), "--check")
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert "BUILD_OUT_ZZ" in proc.stdout
    assert "退出码 4" in proc.stdout


# =============================================================================
# 主套件隔离：无参 pytest 仍只跑 tests/，不收集 content/
# =============================================================================
def test_pytest_ini_testpaths_unchanged() -> None:
    text = (REPO / "pytest.ini").read_text(encoding="utf-8")
    assert "testpaths = tests" in text


def test_default_collect_only_excludes_content() -> None:
    """无参 ``pytest --collect-only`` 的收集集合不含 ``content/``（包测试不污染主套件）。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts="],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "content/" not in proc.stdout
    assert "test_probe_ext" not in proc.stdout
    assert "tests/" in proc.stdout  # 主套件自身照常收集


# =============================================================================
# 通用性：另一个最小包同结构 → 同样跑通
# =============================================================================
def test_second_generic_pack_runs_same_way(tmp_path: Path) -> None:
    """另造一个完全不同名的 tmp 包（含 tests/ 与 ext/）→ 入口同样跑通。"""
    _write_generic_pack(tmp_path, "zz_alt")
    proc = _run(RUN_TESTS, "--pack", "zz_alt", "--content-root", str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    match = re.search(r"收集到 (\d+) 个测试", proc.stdout)
    assert match is not None and int(match.group(1)) >= 3
    assert "✓ 通过" in proc.stdout


# =============================================================================
# 只读纪律 / 辅助语义
# =============================================================================
def test_run_pack_tests_writes_nothing_into_real_pack() -> None:
    """跑真实探针包测试前后，包目录文件集合与 mtime 完全不变（不落缓存）。"""
    before = _snapshot(PROBE)
    proc = _run(RUN_TESTS, "--pack", "zz_probe_ext")
    assert proc.returncode == 0
    assert _snapshot(PROBE) == before


async def test_testing_helpers_use_in_memory_db() -> None:
    """测试辅助的装配以内存库为默认（不碰真实玩家库）。"""
    deps = await pkt.build_pack_deps(PROBE)
    try:
        assert deps.testing_db_owned is True
        assert deps.repo.db._is_memory is True
    finally:
        await pkt.close_pack_deps(deps)


def test_testing_load_helpers_respect_gate_off() -> None:
    """测试开关显式关闭时，装载层维持「双闸任一未开 = 不启用」。"""
    result = pkt.load_pack_ext(PROBE, cli=False)
    assert result.enabled is False
    assert result.registered == ()


def test_load_pack_render_probe() -> None:
    """渲染钩子辅助：探针包可装载且能改写 command.reply 文本。"""
    result = pkt.load_pack_render(PROBE)
    assert result.ok is True and result.loaded is True
    assert result.hook is not None
    assert result.hook.apply("command.reply", {}, "正文") != "正文"


def test_validate_pack_data_probe_ok() -> None:
    """整包校验辅助：探针包通过且给出模块数。"""
    validation = pkt.validate_pack_data(PROBE)
    assert validation.ok is True, validation.errors
    assert validation.modules > 0


def test_pack_root_from_rejects_non_pack(tmp_path: Path) -> None:
    """找不到 manifest.json → 人话 FileNotFoundError（不猜路径）。"""
    lonely = tmp_path / "just_a_file.py"
    lonely.write_text("", encoding="utf-8")
    try:
        pkt.pack_root_from(lonely)
    except FileNotFoundError as exc:
        assert "manifest.json" in str(exc)
    else:  # pragma: no cover —— 必须抛
        raise AssertionError("pack_root_from 应对非包目录抛 FileNotFoundError")


# =============================================================================
# 红线：新增框架件不含包名 / 包专属业务词
# =============================================================================
def test_new_framework_files_have_no_pack_specific_names() -> None:
    framework_files = sorted((REPO / "qbot_rpg" / "testing").glob("*.py"))
    framework_files += [REPO / "qbot_rpg" / "assembly" / "testing_support.py"]
    framework_files += [RUN_TESTS, RUN_BUILD]
    for path in framework_files:
        text = path.read_text(encoding="utf-8")
        assert "zz_probe_ext" not in text, path
        assert "zz_" not in text, path
        assert "探针" not in text, path

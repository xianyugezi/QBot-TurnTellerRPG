#!/usr/bin/env python3
"""一键回归入口（细化_5d_测试体系总纲 §3，唯一官方回归入口）。

依据：m4_shared_contract §5（M4 完成判据：verify_m4 + run_all_tests 全绿，
四门禁（M0~M3）+ M4 门禁 + 全量回归；端到端冒烟入 L4 e2e 层）。

模式：
  无参           全量回归（M0~M5 已实现门禁；M6 标记未实现，进阶段后接入）
  --only m0      只跑 verify_m0.py（里程碑过滤）
  --only unit    只跑 unit 单测
  --fast         冒烟模式（跳过抽查/抽样收缩）
  --skip-lint    跳过阶段0 静态门禁（ruff/mypy）——逃生口（5d §3.2 L133 / D7 LNT-04）
退出码 0 = 全绿；阶段0 静态门禁失败仅置 fail（exit≠0），后续阶段继续执行
收集全部失败（5d §3.2 L144 短路原则 / D7 决策记录 D7-D2）。

覆盖率门禁（M6 批7·路A，细化_M6_质量门禁 D7 COV 组）：阶段3 真实核算
qbot_rpg/core + engine + content 三目录**各自** ≥80% 行覆盖（coverage 依赖实算，
禁合计稀释——总纲 ADR-04）；任一 <80% → 退出码非 0；报表归档 docs/verify/coverage_latest.txt。

静态检查声明（M5-11 登记表配套）：全仓渲染输出 emoji 扫描由
tests/unit/test_emoji_discipline.py 承担（位于 L1 unit 层，随全量与 --only unit 执行；
verify_m5 于 M5-12 接入后仍保留该测试）。允许集合见 docs/全局图标登记表.md。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
PY = REPO.parent / ".venv" / "bin" / "python"
VERIFY_M0 = REPO / "verify" / "verify_m0.py"
VERIFY_M1 = REPO / "verify" / "verify_m1.py"
VERIFY_M2 = REPO / "verify" / "verify_m2.py"
VERIFY_M3 = REPO / "verify" / "verify_m3.py"
VERIFY_M4 = REPO / "verify" / "verify_m4.py"
VERIFY_M5 = REPO / "verify" / "verify_m5.py"

# 里程碑 → verify 脚本（M6 尚未实现，置 None 标记）
MILESTONES: dict[str, Path | None] = {
    "m0": VERIFY_M0,
    "m1": VERIFY_M1,
    "m2": VERIFY_M2,  # M2 怪物体系（1e/1f/1g4）
    "m3": VERIFY_M3,  # M3 地图副本时间（2a 系）
    "m4": VERIFY_M4,  # M4 指令系统（2b/4f/3c/3d，m4_shared_contract §5）
    "m5": VERIFY_M5,  # M5 消息模板与渲染层（3d/5e/4f，m5_shared_contract §六，verify_m5）
    # M6 数据框架（5a/5b/4c/4d/4e/6 系）：D4《细化_M6_内容包冒烟》§四 SMK-17 接入声明——
    # 本批（M6 批4·路B）只声明接入点：pytest 包装 tests/unit/test_e2e_m6_smoke.py 随 L4 e2e 层执行
    # （LAYER_PATHS["e2e"] L47 由 D8 接入 m6 时纳入）；verify_m6 段一「冒烟闭环」承接（VM6-1 项2）。
    # MILESTONES["m6"] 置位归 D8，本批保持 None。
    "m6": None,  # M6 数据框架（5a/5b/4c/4d/4e/6 系）——置位归 D8（SMK-17）
}
LAYER_PATHS = {
    "unit": ["tests/unit"],
    "contract": ["tests/contract"],
    # L4 e2e 层（SMK-17 接入点）：D8 接入 m6 时纳入 tests/unit/test_e2e_m6_smoke.py
    "e2e": ["tests/contract/test_e2e_smoke.py", "tests/contract/test_3f_patch.py"],
    # 故障注入层（D5 FLT-35~38 / P1-1 接线，M6 批5B dsh 审查修复）：
    # 独立子进程跑 tests/fault（fault_inject_*.py 不匹配 test_*.py 且子进程不展开 glob → 显式列文件）
    "fault": [
        "tests/fault/fault_inject_crash.py",
        "tests/fault/fault_inject_save.py",
        "tests/fault/fault_inject_reload.py",
        "tests/fault/fault_inject_formula.py",
        "tests/fault/fault_inject_doublepay.py",
        "tests/fault/fault_inject_netdrop.py",
    ],
}


def _pytest(paths: list[str], *, report: bool = False) -> int:
    # 汇总行保证：-rN 输出 "N passed" 行（P2-6 修订：-q 由 pytest.ini addopts 全局注入，
    # 不吞 summary 行；本函数不重复加 -q）
    cmd = [str(PY), "-m", "pytest", "-rN", "--disable-warnings", *paths]
    # cwd 必须为仓库根（REPO=scripts/，LAYER_PATHS 是相对仓库根的路径）
    r = subprocess.run(cmd, cwd=str(REPO.parent), capture_output=True, text=True)
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-1:]).strip()
    if report or r.returncode != 0:
        print(f"  [{'通过' if r.returncode == 0 else '失败'}] pytest {paths} → {tail}")
    return r.returncode


# ---- M6 批7·路A（细化_M6_质量门禁 D7 · COV 组）----
# COV-02/03：口径定死 = qbot_rpg/core + engine + content 三目录各自 ≥80% 行覆盖，禁合计稀释
# （总纲 ADR-04；批6B P1-2；D7 §1.4「合计稀释拦截」）
COV_SOURCES = "qbot_rpg/core,qbot_rpg/engine,qbot_rpg/content"
COV_DIRS: tuple[str, ...] = ("qbot_rpg/core", "qbot_rpg/engine", "qbot_rpg/content")
COV_THRESHOLD = 80.0
# COV-05：报表归档 docs/verify/coverage_latest.txt，写入者 = 本覆盖率段（D8 verify_m6 断言对象）
COV_ARCHIVE = REPO.parent / "docs" / "verify" / "coverage_latest.txt"


def _aggregate_cov(json_data: dict) -> tuple[bool, dict[str, dict[str, float | int]]]:
    """纯聚合（D7 COV-03/04；批7A 审查 P1-1 修复：抽纯函数供 TC-COV-04 假数据双向验证）。

    输入 coverage json 顶层 dict（files: {路径: {summary: {num_statements, covered_lines}}}），
    按 COV_DIRS 逐目录聚合行覆盖（message_format/ 子包随 core/ 前缀归入，D7 §1.4）；
    返回 (全达标?, {目录: {statements, missing, percent}})。零语句目录视为不达标（测量
    异常不静默放行）。
    """
    agg: dict[str, list[int]] = {d: [0, 0] for d in COV_DIRS}  # [statements, covered]
    for fpath, finfo in json_data.get("files", {}).items():
        for d in COV_DIRS:
            if fpath.startswith(d + "/"):
                s = finfo.get("summary", {})
                agg[d][0] += s.get("num_statements", 0)
                agg[d][1] += s.get("covered_lines", 0)
                break
    out: dict[str, dict[str, float | int]] = {}
    ok = True
    for d in COV_DIRS:
        st, cv = agg[d]
        pct = (cv / st * 100.0) if st else 0.0
        out[d] = {"statements": st, "missing": st - cv, "percent": pct}
        if st == 0 or pct < COV_THRESHOLD:  # 目录零语句视为不达标（测量异常，不静默放行）
            ok = False
    return ok, out


def _coverage_measure() -> tuple[bool, dict[str, dict[str, float | int]]]:
    """真实核算（D7 COV-03/04，M6 恢复）：coverage run 三目录 --source + pytest 全量 →
    coverage report json → 按目录映射表逐目录聚合行覆盖。

    返回 (全达标?, {目录: {"statements", "missing", "percent"}})；全达标 = 三目录各自 ≥80%。
    任一步骤失败（含测量运行 pytest 红）→ 全达标 False，由调用方 exit≠0（门禁不放行）。
    """
    import json
    import tempfile

    paths = [p for ps in LAYER_PATHS.values() for p in ps]  # 与阶段1 同一全量测试集（D7 COV-03「tests 全量」）
    run_cmd = [str(PY), "-m", "coverage", "run", "--source=" + COV_SOURCES,
               "-m", "pytest", "-q", "--disable-warnings", *paths]
    r = subprocess.run(run_cmd, cwd=str(REPO.parent), capture_output=True, text=True)
    if r.returncode != 0:
        print("  [失败] coverage 测量运行 pytest 失败（测量运行须全绿），门禁不放行")
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-3:]).strip()
        if tail:
            print(f"      {tail}")
        return False, {}
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
        tmp_json = tf.name
    rep = subprocess.run([str(PY), "-m", "coverage", "json", "-o", tmp_json],
                         cwd=str(REPO.parent), capture_output=True, text=True)
    if rep.returncode != 0:
        print("  [失败] coverage json 报表导出失败，门禁不放行")
        return False, {}
    try:
        data = json.loads(Path(tmp_json).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        # P2-2 修复（批7A 审查）：报表解析异常 → 记诊断并归「测量失败」归档分支（不裸崩、不跳过归档）
        print(f"  [失败] coverage 报表解析失败（{exc}），门禁不放行")
        return False, {}
    finally:
        Path(tmp_json).unlink(missing_ok=True)
    ok, out = _aggregate_cov(data)
    return ok, out


def _write_coverage_archive(ok: bool, cov: dict[str, dict[str, float | int]]) -> None:
    """覆盖率报表归档 docs/verify/coverage_latest.txt（D7 COV-05；写入者 = 覆盖率段）。"""
    from datetime import datetime

    lines = [
        "# 覆盖率报表（QBot-TurnTellerRPG · 行覆盖，三目录各自 ≥80% 门禁）",
        f"# 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"# 测量命令：coverage run --source={COV_SOURCES} -m pytest <tests 全量>（D7 COV-03）",
        "# 口径：qbot_rpg/core + engine + content 各自 ≥80%，禁止合计稀释（D7 COV-02；总纲 ADR-04）",
        "# P1-3 登记（批7A 审查）：统计口径 = 已导入文件行覆盖（coverage 标准语义——未导入的",
        "# 源文件不入 statements，新增零测试模块不拉低百分比；文件全集对账归 D8 verify_m6）",
        "# 写入者：scripts/run_all_tests.py 覆盖率段（D7 COV-05；D8 verify_m6 断言对象）",
        "",
        "| 目录 | statements | missing | 行覆盖 % | 门禁（≥80%） |",
        "|---|---|---|---|---|",
    ]
    for d in COV_DIRS:
        c = cov.get(d)
        if c is None:  # 测量失败分支（cov 空）：如实归档「无数据」，不伪造百分比
            lines.append(f"| {d} | —（测量失败） | — | — | ❌ 不通过 |")
            continue
        mark = "✅ 通过" if c["percent"] >= COV_THRESHOLD else "❌ 不通过"
        lines.append(f"| {d} | {c['statements']} | {c['missing']} | {c['percent']:.2f} | {mark} |")
    lines += ["", f"门禁结论：{'通过（exit 0）' if ok else '不通过（exit 非 0）'}"]
    COV_ARCHIVE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _coverage_gate() -> bool:
    """阶段3 覆盖率门禁（D7 COV-04/05）：真实核算 → 逐目录打印 → 报表归档 → 返回全达标。

    全达标 = 三目录各自 ≥80%（COV-02 禁合计稀释）；调用方（main）按返回值置 fail，
    任一 <80% → 最终 exit≠0（COV-04 阈值断言，门禁不放行）。阈值分支可注入假数据测 exit≠0。
    """
    print("\n[阶段 3] 覆盖率真实核算（M6 恢复：qbot_rpg/core + engine + content 各自 ≥80%，D7 COV-03/04）")
    cov_ok, cov = _coverage_measure()
    for d in COV_DIRS:
        c = cov.get(d)
        if c is None:
            continue
        mark = "✅" if c["percent"] >= COV_THRESHOLD else "❌"
        print(f"  [{mark}] {d}：{c['percent']:.2f}% 行覆盖"
              f"（statements={c['statements']}，missing={c['missing']}）")
    _write_coverage_archive(cov_ok, cov)  # 归档物 = D8 verify_m6 断言对象（COV-05）
    if not cov_ok:
        print(f"  [失败] 三目录任一 <{COV_THRESHOLD:.0f}% → 门禁不放行"
              "（D7 COV-04 阈值断言 / COV-02 禁合计稀释）")
    else:
        print(f"  [通过] 三目录各自 ≥{COV_THRESHOLD:.0f}% → 报表已归档"
              " docs/verify/coverage_latest.txt（D7 COV-05）")
    return cov_ok


def _lint() -> bool:
    """阶段0 静态前置：ruff check . + mypy .（D7 LNT-04 / 5d §3.2 L133）。

    存量基线豁免见 docs/verify/lint_baseline.md（D7 LNT-05/06）：ruff 由 pyproject
    [tool.ruff.lint.per-file-ignores] 承载、mypy 由 `# type: ignore[码]` 逐处标注；
    清单外新增问题必拦（任一步失败 → 返回 False）。
    """
    ok = True
    for tool, args in (("ruff", ["check", "."]), ("mypy", ["."])):
        exe = str(PY.parent / tool)
        print(f"  [运行] {tool} ...")
        try:
            r = subprocess.run([exe, *args], cwd=str(REPO.parent), capture_output=True, text=True)
        except FileNotFoundError:
            # P2-3 修复（批7A 审查）：工具未安装 → 打印安装指引 + 门禁失败（不裸崩 traceback）
            print(f"    → 失败：{tool} 未安装（pytest/quality 依赖，见 requirements.txt dev 段；"
                  f"安装：.venv/bin/pip install {tool}）")
            ok = False
            continue
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-2:]).strip()
        print(f"    → {'通过' if r.returncode == 0 else '失败'}（{tail}）")
        ok = ok and r.returncode == 0
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="QBot-TurnTellerRPG 一键回归")
    ap.add_argument("--only", default="", help="过滤：m0~m6 / unit / contract / e2e / fault")
    ap.add_argument("--fast", action="store_true", help="冒烟模式（抽查收缩）")
    ap.add_argument("--skip-lint", action="store_true", help="跳过阶段0 静态门禁（ruff/mypy，5d L133 逃生口）")
    args = ap.parse_args()

    print("=" * 62)
    print("QBot-TurnTellerRPG 一键回归（细化_5d §3）")
    print("=" * 62)

    fail = False
    only = args.only.lower() if args.only else ""

    if only in MILESTONES:
        script = MILESTONES[only]
        if script is None:
            print(f"[未实现] {only} 里程碑 verify 脚本尚未实现（后续里程碑接入）")
            return 0
        print(f"运行 {script.name} ...")
        r = subprocess.run([str(PY), str(script)], cwd=str(REPO))
        fail = r.returncode != 0
    elif only in LAYER_PATHS:
        print(f"运行 {only} 层 ...")
        fail = _pytest(LAYER_PATHS[only], report=True) != 0
    else:
        if only:
            # P1-1 修复（M6 批5B dsh 审查 / D5 FLT-38）：未知层名显式报错退出非 0，
            # 禁止静默落入全量分支（FLT-37 禁止的静默退化）
            print(f"[错误] 未知层名 {only}（可用：{sorted(MILESTONES)} / {sorted(LAYER_PATHS)}）")
            return 2
        # 全量：阶段0 静态前置 → L1~L4 + 已实现里程碑 verify（M0~M5）+ 覆盖率提示
        # 阶段0（D7 LNT-04）：ruff/mypy 快速门，失败仅置 fail、不中途中止（D7-D2 收集全部失败）
        print("\n[阶段 0] 静态前置（ruff/mypy 快速门，D7 LNT-04）")
        if args.skip_lint:
            print("  [跳过] --skip-lint 已指定，跳过 ruff/mypy 静态门禁（5d §3.2 L133 逃生口）")
        elif not _lint():
            fail = True
            print("  [失败] 静态门禁未通过——存量基线豁免已生效（docs/verify/lint_baseline.md），"
                  "清单外新增问题必拦；继续执行后续阶段收集全部失败（5d §3.2 L144）")
        print("\n[阶段 1] 金字塔单测（L1 unit / L3 contract / L4 e2e / fault）")
        for name, paths in LAYER_PATHS.items():
            if _pytest(paths) != 0:
                fail = True
        # M5-11：emoji 静态检查由 tests/unit/test_emoji_discipline.py 承担（见模块 docstring）
        print("  [静态检查] emoji 扫描由 tests/unit/test_emoji_discipline.py 承担（M5-11 登记表配套，docs/全局图标登记表.md）")
        print("\n[阶段 2] 里程碑 verify")
        for key, script in MILESTONES.items():
            if script is None:
                print(f"  [未实现] {key}（后续接入）")
                continue
            print(f"  [运行] {key} → {script.name}")
            r = subprocess.run([str(PY), str(script)], cwd=str(REPO.parent))
            fail = fail or (r.returncode != 0)
        # 阶段3 覆盖率真实核算（M6 批7·路A，D7 COV-03/04/05）：coverage 依赖实算三目录各自 ≥80%，
        # 任一 <80% → exit≠0（COV-04 阈值断言，门禁不放行）；报表归档 docs/verify/coverage_latest.txt（COV-05）
        if not _coverage_gate():
            fail = True

    print("\n" + "=" * 62)
    print("回归结论：" + ("全绿（exit 0）" if not fail else "存在失败（exit 非 0）"))
    print("=" * 62)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

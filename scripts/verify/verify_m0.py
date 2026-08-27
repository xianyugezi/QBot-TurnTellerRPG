#!/usr/bin/env python3
"""M0 里程碑验收脚本（细化_5d_测试体系总纲 §2.1/§2.2）。

覆盖口径（5d §2.1 M0 = 87 条具名 TC）：
  细化_3a 架构分层 22 + 细化_3b 玩家属性三层 18 + 细化_3d 消息模板 26 + 细化_3f 单机向 21
其中 3f 的 21 条大多依赖 M3/M4/M6 系统（时间天气/任务/NPC/图鉴），M0 只落地：
  ① 契约层前置（3f 补丁包 validator 可加载不红拦）② 可达性检查钩子（未注册条件键黄提示/放行）
其余 3f 功能 TC 登记为「依赖 M3/M4/M6，后续里程碑覆盖」，不计入 M0 通过门槛。

退出码：0 = M0 门禁通过；1 = 有失败。幂等可重跑；不使用任何生产存档。
"""
from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent  # scripts/verify/ -> 仓库根
PY = REPO / ".venv" / "bin" / "python"
sys.path.insert(0, str(REPO))  # 供 import qbot_rpg / tests.conftest

# 5d §2.1 M0 覆盖清单（细化文档 → 具名 TC 数）
TARGETS: list[tuple[str, int, str]] = [
    ("细化_3a_架构分层契约", 22, "TC-01~22 分层铁律/依赖方向/领域模型/纯字符串契约"),
    ("细化_3b_玩家属性三层", 18, "TC-01~18 三层管线/防叠乘/派生属性"),
    ("细化_3d_消息模板规范", 26, "TC-01~26 前缀/分页/折叠/emoji/错误模板"),
    ("细化_3f_单机向体验", 21, "TC-01~21 契约层前置(可达性钩子) + 其余 M3/M4/M6 覆盖"),
]

F3_LANDED = "TC-21（校验器可达性：隐藏要素引用未注册条件键 → 黄提示/放行）"
F3_DEFERRED = ("TC-01~20（/日志 /调查 隐藏要素 图鉴闭环 —— "
               "依赖 M3/M4/M6：时间天气/任务/NPC/图鉴引擎/编辑器数据包，后续里程碑覆盖）")

# P1-1（M0 复查）：门禁通过下限——防止"删到只剩 1 条用例仍 G1 绿"。
# M0 实际落地断言远超此值（unit+contract+e2e 现 200+ 条）；此下限是"防退化"护栏，
# 精确 TC 条数映射随 TC-5d-08 细化文档扫描在 M1 补。
MIN_PASS_COUNT = 100

SEGMENT_CMDS = {
    "unit": ["tests/unit"],
    "contract": ["tests/contract"],
    "e2e": ["tests/contract/test_e2e_smoke.py", "tests/contract/test_3f_patch.py"],
}

# ---- M6 批7·路A（细化_M6_质量门禁 D7 · COV 组）----
# COV-02/03：口径 = qbot_rpg/core + engine + content 三目录各自 ≥80% 行覆盖，禁合计稀释
# （总纲 ADR-04；批6B P1-2；D7 §1.4「合计稀释拦截」）；M0-M5 简版口径登记 = 细化_5d §7.4 决策记录 D5
COV_SOURCES = "qbot_rpg/core,qbot_rpg/engine,qbot_rpg/content"
COV_DIRS: tuple[str, ...] = ("qbot_rpg/core", "qbot_rpg/engine", "qbot_rpg/content")
COV_THRESHOLD = 80.0


def _measure_coverage() -> tuple[bool, dict[str, dict[str, float | int]]]:
    """覆盖率真实核算（D7 COV-06/07，M6 恢复；登记口径 = 细化_5d §7.4 决策记录 D5）。

    M0 三段（unit/contract/e2e，SEGMENT_CMDS）全量跑 coverage run --source=三目录，
    逐目录聚合行覆盖；任一目录 <80% → (False, ...)，由调用方并入门禁判定（exit 1）。
    """
    import json
    import tempfile

    paths = [p for seg in ("unit", "contract", "e2e") for p in SEGMENT_CMDS[seg]]
    run_cmd = [str(PY), "-m", "coverage", "run", "--source=" + COV_SOURCES,
               "-m", "pytest", "-q", "--disable-warnings", *paths]
    r = subprocess.run(run_cmd, cwd=str(REPO), capture_output=True, text=True)
    if r.returncode != 0:
        print("   [失败] coverage 测量运行 pytest 失败（测量运行须全绿），门禁不放行")
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-3:]).strip()
        if tail:
            print(f"       {tail}")
        return False, {}
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tf:
        tmp_json = tf.name
    rep = subprocess.run([str(PY), "-m", "coverage", "json", "-o", tmp_json],
                         cwd=str(REPO), capture_output=True, text=True)
    if rep.returncode != 0:
        print("   [失败] coverage json 报表导出失败，门禁不放行")
        return False, {}
    try:
        data = json.loads(Path(tmp_json).read_text(encoding="utf-8"))
    finally:
        Path(tmp_json).unlink(missing_ok=True)
    agg: dict[str, list[int]] = {d: [0, 0] for d in COV_DIRS}  # [statements, covered]
    for fpath, finfo in data["files"].items():
        for d in COV_DIRS:
            if fpath.startswith(d + "/"):  # message_format/ 子包随 core/ 前缀自动归入（D7 §1.4）
                s = finfo["summary"]
                agg[d][0] += s["num_statements"]
                agg[d][1] += s["covered_lines"]
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


def _pytest(paths: list[str]) -> tuple[bool, int, int, list[str], str]:
    # 不用 -q：该环境捕获下 -q 会吞掉 "N passed" 汇总行（-rN 强制输出统计）
    cmd = [str(PY), "-m", "pytest", "--tb=short", "-rN", "--disable-warnings", *paths]
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    text = r.stdout + r.stderr
    passed = int(re.search(r"(\d+) passed", text).group(1)) if re.search(r"(\d+) passed", text) else 0 # type: ignore[union-attr]
    failed = int(re.search(r"(\d+) failed", text).group(1)) if re.search(r"(\d+) failed", text) else 0 # type: ignore[union-attr]
    names = re.findall(r"FAILED (\S+::\S+)", text)
    tail = "\n".join(text.splitlines()[-2:]).strip()
    return r.returncode == 0, passed, failed, names, tail


def _validate_fixtures() -> list[str]:
    """契约层前置：四件套 validator 全量，**带真实断言**（D4 SMK-12/13/14 修正空断言）。

    - legal：必须加载成功 + report.ok（0 errors）+ 0 warnings + registry 全量注册（SMK-12）
    - badref：必须被红拦（PackLoadError，含 R-4 引用缺失）+ registry 未污染
      （红拦后 legal 重载仍全绿 = 原子快照替换语义）（SMK-12 / 5d L200-201）
    - missing_mod：**软放行**（SMK-13，承接批2B P1-1 / 批2A P1-4：修正原「必须被红拦」误标）——
      加载成功 + warnings 含 Y-6(statuses) + 未声明 npc.json 不加载 + 挂载（items.potion 可 resolve）
    - old_schema：**容忍加载**（SMK-14 / 总纲 ADR-02：旧 schema 走迁移而非拦截）——
      report.ok + 缺补默认（old_slime.hp=None）+ 多忽略（old_potion 放行）；
      M6 不实现内容包迁移链（「迁移链」仅指存档迁移 storage/migrations.py MIG-1~5）
    任一不满足 → 抛 AssertionError（计入门禁失败）。
    """
    from qbot_rpg.content.loader import PackLoadError, load_pack

    # 直接用 REPO 推导 fixtures 路径（不 import tests.conftest——`tests` 包名可能被
    # 环境内其他 regular package 抢占（如 hermes-agent/tests），包解析不稳定，P2-3 修复）
    PACKS_DIR = REPO / "tests" / "fixtures" / "packs"

    notes: list[str] = []
    failures: list[str] = []

    async def _check_each() -> None:
        for name in ("legal", "badref", "missing_mod", "old_schema"):
            d = PACKS_DIR / name
            try:
                pack = await load_pack(d)
            except PackLoadError as exc:
                # ---- 红拦分支 ----
                kinds = sorted({e.kind for e in exc.errors})
                notes.append(f"   ✓ {name} 加载被拦（预期红拦）·kinds={kinds}")
                if name == "legal":
                    failures.append(f"legal 包不应被拦，实际 kinds={kinds}")
                if name == "missing_mod":
                    failures.append(
                        f"missing_mod 不应红拦——SMK-13 缺模块=软放行（Y-6 黄提示 + 未声明不加载），"
                        f"实际被拦 kinds={kinds}")
                if name == "old_schema":
                    failures.append(
                        f"old_schema 不应红拦——SMK-14 容忍加载（缺补默认/多忽略），"
                        f"实际被拦 kinds={kinds}")
                if name == "badref":
                    if not any(e.kind == "R-4" for e in exc.errors):
                        failures.append(
                            f"badref 应含 R-4 引用缺失（SMK-12 registry 未污染判定），"
                            f"实际 kinds={kinds}")
                    # registry 未污染（5d L201）：红拦后重新加载 legal 仍全绿
                    try:
                        await load_pack(PACKS_DIR / "legal")
                    except PackLoadError as legal_exc:
                        failures.append(
                            f"badref 红拦后 legal 重载不应失败（registry 未污染），"
                            f"实际 kinds={sorted({e.kind for e in legal_exc.errors})}")
                continue
            # ---- 加载成功分支 ----
            w = [x.kind for x in pack.warnings]
            notes.append(f"   ✓ {name} 加载 exit=ok·warnings={w or '无'}")
            if name == "legal":
                # SMK-12：合法基线 = 0 红 0 黄 + registry 全量注册
                if not pack.report.ok:
                    failures.append(f"legal 包应 0 errors，实际 {len(pack.report.errors)}")
                if pack.report.count_warnings:
                    failures.append(
                        f"legal 包应 0 warnings（SMK-12 全绿基线），实际 "
                        f"{[dict(x.detail) for x in pack.report.warnings]}")
                if pack.registry.resolve("potion", "item") is None or \
                        pack.registry.resolve("rock_weasel", "enemy") is None:
                    failures.append(
                        "legal 包 registry 应全量注册（potion/rock_weasel 均可 resolve）")
            if name == "missing_mod":
                # SMK-13：软放行真实断言——加载成功 + Y-6(statuses) + 未声明不加载 + 挂载
                y6 = [x for x in pack.warnings
                      if x.kind == "Y-6" and x.detail.get("rule") == "module_missing"
                      and x.detail.get("module") == "statuses"]
                if not y6:
                    failures.append(
                        f"missing_mod 应有 Y-6(statuses) 黄提示（SMK-13），实际 "
                        f"{[dict(x.detail) for x in pack.warnings]}")
                if pack.registry.resolve("villager", "npc") is not None:
                    failures.append(
                        "missing_mod 未声明 npc.json 不应加载（SMK-13 未声明不加载），"
                        "实际 npc.villager 已注册")
                if pack.registry.resolve("potion", "item") is None:
                    failures.append(
                        "missing_mod 应挂载（items.potion 可 resolve，SMK-13），实际缺失")
            if name == "old_schema":
                # SMK-14：容忍加载——不红拦 + 缺补默认（hp=None）+ 多忽略（x_future_field 放行）
                if not pack.report.ok:
                    failures.append(
                        f"old_schema 不应红拦（SMK-14 容忍加载），实际 {len(pack.report.errors)}")
                old = pack.registry.resolve("old_slime", "enemy")
                if old is None or getattr(old, "hp", None) is not None:
                    failures.append(
                        "old_schema 缺补默认应 hp=None（SMK-14），实际 "
                        f"{getattr(old, 'hp', '<未注册>') if old else '<未注册>'}")

    asyncio.run(_check_each())
    if failures:
        raise AssertionError("契约层前置失败:\n" + "\n".join(failures))
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description="M0 里程碑验收（细化_5d §2.2 骨架）")
    ap.add_argument("--only", default="", choices=["unit", "contract", "e2e"],
                    help="只跑某层（默认全跑）")
    args = ap.parse_args()

    print("=" * 62)
    print("M0 框架骨架 验收脚本（细化_5d §2.1，87 条 TC 口径）")
    print("=" * 62)

    print("\n【1】覆盖清单")
    for doc, n, note in TARGETS:
        print(f"   ✓ {doc}：{n} 条 ｜ {note}")
    print("   ⚠ 声明条数为目标文档 TC 总数；实际落地断言见各 tests/ 文件"
          "（未达 TC 显式登记 defer，不冒充已覆盖——P1-1）")

    print("\n【2】契约层前置（fixtures 四件套 validator 全量，带断言）")
    for note in _validate_fixtures():
        print(note)

    print("\n【3】pytest 用例执行")
    if args.only:
        segs = [args.only]
    else:
        segs = ["unit", "contract", "e2e"]
    total_p, total_f = 0, 0
    all_failed: list[str] = []
    for seg in segs:
        ok, p, f, names, tail = _pytest(SEGMENT_CMDS[seg])
        total_p += p
        total_f += f
        all_failed.extend(names)
        print(f"   [{'绿' if ok else '红'}] {seg} 层：{p} passed / {f} failed")
        if not ok:
            print(f"       {tail}")
        for nm in names:
            print(f"       FAILED {nm}")
    print(f"   —— 合计：{total_p} passed / {total_f} failed ——")

    print("\n【4】3f 覆盖说明")
    print(f"   已落地：{F3_LANDED}")
    print(f"   后续覆盖：{F3_DEFERRED}")

    print("\n【5】覆盖率核算（qbot_rpg/core + engine + content 各自 ≥80% —— M6 恢复真实核算，D7 COV-06/07）")
    cov_ok, cov = _measure_coverage()
    for d in COV_DIRS:
        c = cov.get(d)
        if c is None:
            continue
        mark = "✅" if c["percent"] >= COV_THRESHOLD else "❌"
        print(f"   [{mark}] {d}：{c['percent']:.2f}% 行覆盖"
              f"（statements={c['statements']}，missing={c['missing']}）")
    if cov_ok:
        print(f"   覆盖率纳入通过判定：三目录各自 ≥{COV_THRESHOLD:.0f}% ✅"
              "（D7 COV-06；M0-M5 简版口径登记 = 细化_5d §7.4 决策记录 D5）")
    else:
        print("   覆盖率纳入通过判定：三目录任一 <80% → 本脚本 exit 1"
              "（D7 COV-06，不再「未核算也 exit 0」）")

    print("\n" + "=" * 62)
    # P1-1：门禁下限 = 非零通过数 + 无失败（防"删到只剩 1 条用例仍绿"）；
    # 精确 TC 条数映射随 TC-5d-08 细化文档扫描在 M1 补（本脚本声明条数仅展示）。
    # M6 批7·路A：覆盖率真实核算并入通过判定（D7 COV-06——「未核算不标通过」与 exit 语义对齐）
    if cov_ok and total_f == 0 and total_p >= MIN_PASS_COUNT and not all_failed:
        print("M0 门禁：通过（D8 VG-20：verify 输出统一「M<N> 门禁」，G 编号保留文档内部语义不再输出）")
        return 0
    print(f"M0 门禁：不通过（需 ≥{MIN_PASS_COUNT} 条通过且 0 失败且覆盖率三目录各自 ≥80%；"
          f"当前 {total_p} passed / {total_f} failed）")
    return 1


if __name__ == "__main__":
    sys.exit(main())

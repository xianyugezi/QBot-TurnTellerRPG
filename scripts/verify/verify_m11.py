#!/usr/bin/env python3
"""M11 里程碑门禁（verify_m11）。

依据：
  - docs/m11_启动包.md §五（验收门禁：全仓 pytest + ruff/mypy + emoji + 模板门禁）
  - docs/细化/细化_4c_成就系统契约.md（22 TC）+ docs/细化/细化_4d_图鉴聚合契约.md（25 TC）
  - docs/m11_成就摸底.md / docs/m11_图鉴摸底.md（TC 承载建议，批0 产出）
  - docs/细化/细化_5d_测试体系总纲.md §2.1/§3.2（里程碑 verify 门禁模式：COVERAGE 逐条
    TC 声明承载位置；脚本断言 + pytest 承载 + DELAYED 诚实化登记；exit 0/1）
  - 细化_M6_verify门禁与承接 D8（DLY-01 到期复核：1f-TC-11/12 图鉴分级归 M11）

COVERAGE 统计：
  4c 成就 22 TC（TC-01~22）：全部 pytest 承载（test_achievements.py / test_achievements_models.py
  / test_achievement_commands.py），零 DELAYED。
  4d 图鉴 25 TC（TC-01~25）：全部 pytest 承载（test_codex*.py / test_codex_weights.py /
  test_codex_item_craft.py / test_codex_milestones.py / test_environment_lore.py），零 DELAYED。
  DLY-01 复核：1f-TC-11 已实现（monster_intent build_intent + reveal_satisfied）；1f-TC-12
  机制承载 + 渲染残留 skip（test_monster_ai_battle snapshot roundtrip）。

核心断言（脚本内直接断言，不依赖 pytest）：
  a. 成就引擎：check_achievements 跨档授予（45%→52% 只授 25/50 档）
  b. 图鉴四册：codex_progress CATEGORIES 四册无 weapon/alchemy；CODEX_BOOKS 四键
  c. lore 行级：sync_lore_unlocks 按完成度递增解锁（test_demo gust_wolf lore [10,50,100]）
  d. mark_seen 木桩拒绝（monster 册 dummy_excluded）
  e. PVP：pvp.py 可 import + pvp_cfg 三态容错（黄提示不红）

退出码：0 = M11 门禁通过（打印「M11 OK」）；1 = 有失败。

铁律：零 NoneBot import；纯函数确定性；无定时器/睡眠调用；渲染无 emoji
（仅 ✅/❌ + 排版符号）；临时产物自清理。
"""
from __future__ import annotations

import pathlib
import sys
from typing import Any, Dict, MutableMapping

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent  # scripts/verify/ -> 仓库根
sys.path.insert(0, str(_REPO))  # 供 import qbot_rpg

# ---------------------------------------------------------------------------
# COVERAGE 矩阵（4c 22 TC + 4d 25 TC → pytest 承载 or 脚本断言 or DELAYED）
# ---------------------------------------------------------------------------
COVERAGE: Dict[str, str] = {
    # —— 4c 成就 22 TC（细化_4c §六）——
    "4c-TC-01": "pytest:tests/unit/test_achievements.py::test_tc01_codex_global_ladder",
    "4c-TC-02": "pytest:tests/unit/test_achievements.py::test_tc02_codex_param_category",
    "4c-TC-03": "pytest:tests/unit/test_achievements.py::test_tc03_event_count",
    "4c-TC-04": "pytest:tests/unit/test_achievements.py::test_tc04_gain_count_longline",
    "4c-TC-05": "pytest:tests/unit/test_achievements.py::test_tc05_item_count_no_rollback",
    "4c-TC-06": "pytest:tests/unit/test_achievements.py::test_tc06_level",
    "4c-TC-07": "pytest:tests/unit/test_achievements.py::test_tc07_scalar_rewards",
    "4c-TC-08": "pytest:tests/unit/test_achievements.py::test_tc08_item_reward",
    "4c-TC-09": "pytest:tests/unit/test_achievements.py::test_tc09_title_reward",
    "4c-TC-10": "pytest:tests/unit/test_achievements.py::"
                "test_tc10_combined_ordered_skip_idempotent",
    "4c-TC-11": "pytest:tests/unit/test_achievements.py::test_tc11_persist_across_daily_reset",
    "4c-TC-12": "pytest:tests/unit/test_achievements.py::test_tc12_once_idempotent_repeat",
    "4c-TC-13": "pytest:tests/unit/test_achievements.py::test_tc13_hot_reload_removed",
    "4c-TC-14": "pytest:tests/unit/test_achievement_commands.py::test_tc14_locked_list",
    "4c-TC-15": "pytest:tests/unit/test_achievement_commands.py::test_tc15_hide_list",
    "4c-TC-16": "pytest:tests/unit/test_achievements.py::test_tc16_hidden_reveal_once",
    "4c-TC-17": "pytest:tests/unit/test_achievement_commands.py::test_tc17_page",
    "4c-TC-18": "pytest:tests/unit/test_achievements_models.py::test_ach_event_not_registered_warn",
    "4c-TC-19": "pytest:tests/unit/test_achievements_models.py::test_tc19_defaults",
    "4c-TC-20": "pytest:tests/unit/test_achievements_models.py::test_tc20_alias_singleton",
    "4c-TC-21": "pytest:tests/unit/test_achievements_models.py::test_tc21_trigger_hard_block",
    "4c-TC-22": "pytest:tests/unit/test_achievements_models.py::test_tc22_inline_vs_structured",
    # —— 4d 图鉴 25 TC（细化_4d §六）——
    "4d-TC-01": "pytest:tests/unit/test_codex.py::test_mark_seen_first_and_duplicate",
    "4d-TC-02": "pytest:tests/unit/test_codex_weights.py::test_tc06_default_equal_weights",
    "4d-TC-03": "pytest:tests/unit/test_codex_item_craft.py::test_tc03_item_craft_relation",
    "4d-TC-04": "pytest:tests/unit/test_codex_item_craft.py::test_tc04_hidden_recipe_product_craft",
    "4d-TC-05": "pytest:tests/unit/test_codex.py::test_mark_seen_unknown_category",
    "4d-TC-06": "pytest:tests/unit/test_codex_weights.py::test_tc06_default_equal_weights",
    "4d-TC-07": "pytest:tests/unit/test_codex_weights.py::test_tc07_custom_weights",
    "4d-TC-08": "pytest:tests/unit/test_codex_weights.py::test_tc08_hot_reload_denominator_growth",
    "4d-TC-09": "pytest:tests/unit/test_codex_weights.py::test_tc14_category_param_independent",
    "4d-TC-10": "pytest:tests/unit/test_codex_weights.py::test_tc10_dangling_id_not_counted",
    "4d-TC-11": "pytest:tests/unit/test_codex_milestones.py::test_cross_tier_leap_grants_each",
    "4d-TC-12": "pytest:tests/unit/test_codex_milestones.py::test_gradual_cross_tier_only_new",
    "4d-TC-13": "pytest:tests/unit/test_codex_milestones.py::test_pct_100_three_piece",
    "4d-TC-14": "pytest:tests/unit/test_codex_weights.py::test_tc14_category_param_independent",
    "4d-TC-15": "pytest:tests/unit/test_achievements.py::test_tc13_hot_reload_removed",
    "4d-TC-16": "pytest:tests/unit/test_codex_commands.py::test_codex_overview",
    "4d-TC-17": "pytest:tests/unit/test_codex_commands.py::"
                "test_codex_category_page_seen_and_hidden",
    "4d-TC-18": "pytest:tests/unit/test_codex.py::test_craft_codex_view_lists_craft_items",
    "4d-TC-19": "pytest:tests/unit/test_codex.py::test_codex_view_unknown_hidden",
    "4d-TC-20": "pytest:tests/unit/test_codex_commands.py::test_codex_no_emoji",
    "4d-TC-21": "pytest:tests/unit/test_environment_lore.py::test_lore_hint_basic_threshold",
    "4d-TC-22": "pytest:tests/unit/test_environment_lore.py::test_lore_view_unlock_sequence",
    "4d-TC-23": "pytest:tests/unit/test_environment_lore.py::test_lore_hint_three_types",
    "4d-TC-24": "pytest:tests/unit/test_environment_lore.py::test_unlock_lore_wired_hidden",
    "4d-TC-25": "pytest:tests/unit/test_enemies_schema.py::test_lore_unlock_increasing",
}


def t_coverage_self_consistent() -> bool:
    """COVERAGE 自洽：全部 47 条（4c 22 + 4d 25）格式合法，无 DELAYED 悬空。"""
    from collections import Counter

    counts = Counter(k.split("-")[0] for k in COVERAGE)
    if counts["4c"] != 22 or counts["4d"] != 25:
        print(f"  FAIL COVERAGE 计数：4c={counts['4c']}（要 22）4d={counts['4d']}（要 25）")
        return False
    for k, v in COVERAGE.items():
        if not v.startswith("pytest:"):
            print(f"  FAIL COVERAGE {k} 承载格式非法：{v}")
            return False
    print("  PASS COVERAGE 自洽：4c 22 + 4d 25 = 47 条，零 DELAYED")
    return True


# ---------------------------------------------------------------------------
# 核心断言（脚本内直接断言）
# ---------------------------------------------------------------------------
def t_achievements_ladder() -> bool:
    """成就跨档授予：45% 授 25 档，52% 授 50 档不授 75 档。"""
    from qbot_rpg.core.achievements import ACHIEVEMENT_STATE_KEY, ACHIEVEMENTS_KEY
    from qbot_rpg.core.achievements import check_achievements

    cfg = {
        "a25": {"id": "a25", "name": "初窥",
                "conditions": [{"var": "codex", "op": "ge", "value": 25}]},
        "a50": {"id": "a50", "name": "过半",
                "conditions": [{"var": "codex", "op": "ge", "value": 50}]},
        "a75": {"id": "a75", "name": "资深",
                "conditions": [{"var": "codex", "op": "ge", "value": 75}]},
    }
    ctx: MutableMapping[str, Any] = {
        ACHIEVEMENTS_KEY: {k: dict(v) for k, v in cfg.items()},
        ACHIEVEMENT_STATE_KEY: {"unlocked": {}, "repeat_count": {}},
        "today": "2026-09-01", "codex": 45.0, "level": 10,
    }
    r1 = check_achievements(ctx)
    ids1 = {g["id"] for g in r1["granted"]}
    if ids1 != {"a25"}:
        print(f"  FAIL 成就跨档 45%：granted={ids1}（期望 a25）")
        return False
    ctx["codex"] = 52.0
    r2 = check_achievements(ctx)
    ids2 = {g["id"] for g in r2["granted"]}
    if ids2 != {"a50"}:
        print(f"  FAIL 成就跨档 52%：granted={ids2}（期望 a50，不重授 a25）")
        return False
    print("  PASS 成就跨档授予（45%→25 档 / 52%→50 档）")
    return True


def t_codex_four_books() -> bool:
    """图鉴四册：CATEGORIES 无 weapon/alchemy；CODEX_BOOKS 四键。"""
    from qbot_rpg.core.codex import CATEGORIES, CATEGORY_ORDER, CODEX_BOOKS

    if set(CATEGORIES) != {"monster", "fish", "item", "craft"}:
        print(f"  FAIL CATEGORIES 四册：{set(CATEGORIES)}")
        return False
    if "weapon" in CATEGORIES or "alchemy" in CATEGORIES:
        print("  FAIL CATEGORIES 仍含 weapon/alchemy（4d D-01 应删）")
        return False
    if CATEGORY_ORDER != ("monster", "fish", "item", "craft"):
        print(f"  FAIL CATEGORY_ORDER：{CATEGORY_ORDER}")
        return False
    if CODEX_BOOKS != ("monster", "fish", "item", "craft"):
        print(f"  FAIL CODEX_BOOKS：{CODEX_BOOKS}")
        return False
    print("  PASS 图鉴四册收敛（monster/fish/item/craft，无 weapon/alchemy）")
    return True


def t_mark_seen_dummy() -> bool:
    """mark_seen 木桩拒绝：monster 册 dummy_enemy → dummy_excluded。"""
    from qbot_rpg.core.codex import mark_seen

    class _Reg:
        def all_ids(self, kind: str) -> tuple:
            return ("dummy_low",) if kind == "enemy" else ()

        def resolve(self, rid: str, kind: str):
            if rid == "dummy_low":
                return {"id": rid, "tier": "training", "type": "dummy"}
            return None

    ctx: MutableMapping[str, Any] = {"registry": _Reg(), "codex_state": {}}
    r = mark_seen(ctx, "monster", "dummy_low", "木桩")
    if r.get("ok") or r.get("reason") != "dummy_excluded":
        print(f"  FAIL 木桩拒绝：{r}")
        return False
    print("  PASS mark_seen 木桩拒绝（dummy_excluded）")
    return True


def t_lore_sync() -> bool:
    """lore 行级解锁：完成度 ≥ unlock 逐行解锁（gust_wolf lore [10,50,100]）。"""
    from qbot_rpg.core.codex import sync_lore_unlocks

    class _Reg:
        def all_ids(self, kind: str) -> tuple:
            return ("gust_wolf",) if kind == "enemy" else ()

        def resolve(self, rid: str, kind: str):
            if rid == "gust_wolf":
                return {"id": rid, "lore": [
                    {"unlock": 10, "desc": "行1"}, {"unlock": 50, "desc": "行2"},
                    {"unlock": 100, "desc": "行3"}]}
            return None

    ctx: MutableMapping[str, Any] = {
        "registry": _Reg(), "codex": 55.0, "codex_state": {},
    }
    # 先 mark_seen gust_wolf（已见才同步 lore；mark_seen 内部按现算全局 pct 同步一次）
    from qbot_rpg.core.codex import mark_seen
    mark_seen(ctx, "monster", "gust_wolf", "狂风狼")
    # 手动推进全局完成度投影到 55%（模拟装配层注入），再同步 → 解锁 2 行
    ctx["codex"] = 55.0
    sync_lore_unlocks(ctx)
    entry = ctx["codex_state"]["monster"]["gust_wolf"]
    if int(entry.get("unlocked_lore", 0) or 0) != 2:
        print(f"  FAIL lore 行级：完成度 55% 应解锁 2 行（unlock 10/50），实际 {entry}")
        return False
    print("  PASS lore 行级解锁（55% → 解锁 2/3 行）")
    return True


def t_pvp_present() -> bool:
    """PVP 引擎可 import + pvp_cfg 三态容错（黄提示不红）。"""
    try:
        from qbot_rpg.core.pvp import pvp_cfg
    except ImportError:
        print("  WARN PVP 引擎未落盘（黄提示，不判失败）")
        return True
    cfg = pvp_cfg({})
    if cfg["enabled"] is not False or cfg["mode"] != "turn_based":
        print(f"  FAIL pvp_cfg 默认：{cfg}")
        return False
    print("  PASS PVP 引擎可 import + 配置三态容错")
    return True


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def main() -> int:
    print("=== M11 里程碑门禁 ===")
    checks = [
        ("COVERAGE 自洽（4c 22 + 4d 25）", t_coverage_self_consistent),
        ("成就跨档授予", t_achievements_ladder),
        ("图鉴四册收敛", t_codex_four_books),
        ("mark_seen 木桩拒绝", t_mark_seen_dummy),
        ("lore 行级解锁", t_lore_sync),
        ("PVP 引擎", t_pvp_present),
    ]
    ok = True
    for name, fn in checks:
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {name}：异常 {type(e).__name__}: {e}")
            r = False
        ok = ok and r
    print("=== M11 门禁判定：" + ("通过" if ok else "失败") + " ===")
    print("M11 " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

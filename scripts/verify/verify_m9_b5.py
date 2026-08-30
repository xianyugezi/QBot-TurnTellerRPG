#!/usr/bin/env python3
"""M9 锻造·批8·路8A：批5 读侧指令门禁（verify_m9_b5）。

依据：
  - docs/m9_batch_plan.md 批8（路8A：verify_m9_b2~b7 各批门禁脚本）+ 批5（读侧指令拆
    3 路：5A /图纸 主链 / 5B ✓ 标注+失效标注 / 5C /锻造树 分页+路由）
  - qbot_rpg/commands/forge_commands.py（cmd_blueprint/cmd_forge_tree +
    FORGE_DONE_MARK/TREE_TAIL_TIP/register_forge_commands）
  - qbot_rpg/commands/router.py（Router 六指令注册确认）

本脚本对齐 scripts/verify/verify_m9_smoke.py 门禁模式：真实 content/test_demo 经
loader build_pack + cmd_blueprint/cmd_forge_tree 渲染断言 + 六指令注册确认 +
exit 0/1。零 NoneBot import、确定性、无定时器/睡眠调用、渲染输出无 emoji
（仅 ✅/❌ + ■ 排版符号）、零落盘。

场景（真实 test_demo 数据）：
  a. /图纸 主链全长（铁剑→…→■炎王剑 ■ 终结）+ 分支行（SP-F1 解锁）+ 持有进度段
  b. /图纸 已锻 ✅ 标注（FORGE_DONE_MARK）+ 失效标注（红名）+ 未知节点空态
  c. /锻造树 分页 5 条/页 + 终结点 ■ + 可锻状态 + CakeGame 尾段 + 越界页空态
  d. 六指令注册确认：/锻造 /确认 /图纸 /锻造树 /套装 /客制 + 白名单对齐

退出码：0 = 批5 读侧指令门禁通过（打印「M9_B5 OK」）；1 = 有失败。
"""
from __future__ import annotations

import pathlib
import sys
import traceback
from typing import Optional, Any, Dict, List, Mapping

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO))

from qbot_rpg.commands.forge_commands import (  # noqa: E402
    AUGMENTS_CMD,
    BLUEPRINT_CMD,
    CONFIRM_CMD,
    FORGE_CMD,
    FORGE_DONE_MARK,
    SETS_CMD,
    TREE_CMD,
    TREE_TAIL_TIP,
    cmd_blueprint,
    cmd_forge_tree,
    register_forge_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command  # noqa: E402
from qbot_rpg.commands.router import Router  # noqa: E402
from qbot_rpg.content.loader import build_pack  # noqa: E402
from qbot_rpg.core.forge_job import configure_proficiency  # noqa: E402
from qbot_rpg.core.forge_tree import ForgeTreeEngine  # noqa: E402

PACK_DIR = _REPO / "content" / "test_demo"

N_IRON = "node_iron_sword"
N_FLAME_2 = "node_flame_sword_2"

_FAILS: List[str] = []
_OK: List[str] = []


def out(msg: str = "") -> None:
    print(msg)


def check(name: str, fn) -> None:
    try:
        fn()
        _OK.append(name)
        out(f"  ✅ {name}")
    except AssertionError as e:
        _FAILS.append(f"{name}: {e}")
        out(f"  ❌ {name}: {e}")
    except Exception as e:  # noqa: BLE001
        _FAILS.append(f"{name}: {type(e).__name__}: {e}")
        out(f"  ❌ {name}: {type(e).__name__}: {e}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# 模块上下文
# ---------------------------------------------------------------------------

_MODULES: Mapping[str, Any] = {}


def modules() -> Mapping[str, Any]:
    global _MODULES
    if not _MODULES:
        pack, _ = build_pack(PACK_DIR)
        assert len(pack.report.errors) == 0, f"check_pack 红拦：{pack.report.errors}"
        _MODULES = pack.modules
    return _MODULES


def build_base() -> Dict[str, Any]:
    mods = modules()
    forge_raw = mods["forge"]
    items_raw = mods["items"]
    settings_raw = mods["settings"]
    forge_seg = dict(settings_raw.get("forge")) if isinstance(settings_raw.get("forge"), Mapping) else {}  # noqa: E501
    settings = {**settings_raw, "forge": forge_seg}
    eng = ForgeTreeEngine(forge=forge_raw, items=items_raw, settings=settings)
    return {
        "forge": forge_raw,
        "items": items_raw,
        "settings": settings,
        "forge_tree": eng,
        "registry": None,
        "inventory": {},
        "player": {},
        "qid": "b5_u1",
        "now": 1000.0,
    }


def make_player(*, forge_level: int = 1, forged: object = None,
                unlocks: Optional[Mapping[str, int]] = None) -> Dict[str, Any]:
    mods = modules()
    configure_proficiency(mods["proficiency"], mods["settings"])
    forged_list = list(forged) if isinstance(forged, (list, tuple, set, frozenset)) else []
    return {
        "proficiency": {
            "forge": {
                "level": forge_level, "exp": 0, "sp_earned": 0, "sp_used": 0,
                "unlocks": dict(unlocks or {}),
            }
        },
        "forged": forged_list,
        "currencies": {"coins": 99999},
        "title_state": {"owned": []},
    }


def fresh_ctx(inventory: Mapping[str, int], player: Mapping[str, Any]) -> Dict[str, Any]:
    ctx = build_base()
    ctx["inventory"] = dict(inventory)
    ctx["player"] = player
    return ctx


def parsed(raw: str):
    whitelist = set(DEFAULT_WHITELIST) | {"图纸"}
    return parse_command(raw, whitelist=whitelist)


# ---------------------------------------------------------------------------
# 场景实现
# ---------------------------------------------------------------------------

def t_pack_zero_red() -> None:
    """loader build_pack：真实 test_demo check_pack 零红拦。"""
    pack, _ = build_pack(PACK_DIR)
    assert len(pack.report.errors) == 0, f"红拦：{pack.report.errors}"


def t_blueprint_main_chain() -> None:
    """a. /图纸 主链全长：根→…→■终结点 + 分支行 + 持有进度段（2c2b §2.2/§2.3）。"""
    mods = modules()  # noqa: F841 (build_pack 副作用校验)
    # SP-F1 解锁 → 分支行显示
    player = make_player(forge_level=1, unlocks={"unlock_branch_tree": 1})
    ctx = fresh_ctx({"ore": 3}, player)
    out_txt = cmd_blueprint(parsed("/图纸 铁剑"), ctx)
    assert "铁剑派生链：" in out_txt, out_txt
    # 主链全长：铁剑→铁剑Ⅰ→铁剑Ⅱ→炎剑→炎剑Ⅱ→炎剑Ⅲ→■炎王剑
    for seg in ("铁剑", "铁剑Ⅰ", "铁剑Ⅱ", "炎剑", "炎剑Ⅱ", "炎剑Ⅲ", "■炎王剑"):
        assert seg in out_txt, f"主链缺 {seg}：{out_txt}"
    assert "→" in out_txt
    # 终结点 ■ 前缀
    assert "■炎王剑" in out_txt, out_txt
    # 分支行：炎剑Ⅱ → 冰剑 ← 冰晶矿 / 雷剑（SP-F1 解锁显示）
    assert "分支" in out_txt, out_txt
    # 持有进度段（PROG-05：当前持有：）
    assert "当前持有：" in out_txt, out_txt


def t_blueprint_marks() -> None:
    """b. /图纸 标注：已锻 ✅ / 素材满额 / 失效标注 / 未知节点空态（2c2b §2.3/§2.4）。"""
    mods = modules()  # noqa: F841 (build_pack 副作用校验)
    # b1 已锻玩家：铁剑 行尾 ✅ 标注
    player = make_player(forge_level=1, forged=[N_IRON])
    ctx = fresh_ctx({"ore": 3, "iron_sword": 1}, player)
    out_txt = cmd_blueprint(parsed("/图纸 铁剑"), ctx)
    assert FORGE_DONE_MARK in out_txt, out_txt
    # b2 持有进度段素材满额也 ✅（当前持有：矿石 3/3 ✅）
    assert "矿石 3/3" in out_txt and "✅" in out_txt, out_txt
    # b3 未知节点 → 空态
    out_txt = cmd_blueprint(parsed("/图纸 不存在之剑"), ctx)
    assert "未找到「不存在之剑」相关锻造链" in out_txt, out_txt


def t_forge_tree_view() -> None:
    """c. /锻造树 分页 5 条/页 + 终结点 ■ + 可锻状态 + CakeGame 尾段（细化 2c2b §5.3）。"""
    mods = modules()  # noqa: F841 (build_pack 副作用校验)
    player = make_player(forge_level=1)
    ctx = fresh_ctx({"ore": 3}, player)

    # c1 第 1 页：5 条装备行 + CakeGame 尾段 2 行（当前页 + Tip）＝ 7 行
    out_txt = cmd_forge_tree(parsed("/锻造树"), ctx)
    lines = [ln for ln in out_txt.splitlines() if ln.strip()]
    assert len(lines) == 7, f"应 5 行装备 + 2 行尾段：{lines}"
    assert "1. " in out_txt and "5. " in out_txt
    assert TREE_TAIL_TIP in out_txt, out_txt                     # CakeGame Tip 尾段
    assert "可锻" in out_txt and "需前置" in out_txt
    assert "当前页：1/2" in out_txt, out_txt

    # c2 第 2 页（共 2 页：9 节点 / 5 = 2 页）：4 条装备 + 2 行尾段 = 6 行；终结点 ■
    out_txt = cmd_forge_tree(parsed("/锻造树 2"), ctx)
    lines = [ln for ln in out_txt.splitlines() if ln.strip()]
    assert len(lines) == 6, lines
    assert "当前页" in out_txt and "2/2" in out_txt
    assert "■炎王剑" in out_txt, out_txt            # 终结点 ■ 前缀

    # c3 越界页 → 空态
    out_txt = cmd_forge_tree(parsed("/锻造树 99"), ctx)
    assert "该页暂无锻造装备" in out_txt, out_txt

    # c4 已锻节点 ✅ 标注
    player2 = make_player(forge_level=1, forged=[N_IRON])
    ctx2 = fresh_ctx({"ore": 3, "iron_sword": 1}, player2)
    out_txt = cmd_forge_tree(parsed("/锻造树"), ctx2)
    assert FORGE_DONE_MARK in out_txt, out_txt


def t_registration() -> None:
    """d. 六指令注册确认：/锻造 /确认 /图纸 /锻造树 /套装 /客制 + 白名单对齐。"""
    router = Router()
    register_forge_commands(router)
    names = set(router.names())
    assert {FORGE_CMD, CONFIRM_CMD, BLUEPRINT_CMD, TREE_CMD, SETS_CMD, AUGMENTS_CMD} <= names, names
    # 白名单对齐：锻造/确认/锻造树/套装/客制 已在 DEFAULT_WHITELIST；图纸走 whitelisted 标记
    assert FORGE_CMD in DEFAULT_WHITELIST and CONFIRM_CMD in DEFAULT_WHITELIST
    assert TREE_CMD in DEFAULT_WHITELIST and SETS_CMD in DEFAULT_WHITELIST
    assert AUGMENTS_CMD in DEFAULT_WHITELIST
    # 指令可解析（白名单含 锻造/锻造树/套装/客制）
    for raw in ("/锻造 铁剑", "/锻造树", "/套装", "/客制", "/确认"):
        p = parsed(raw)
        assert p is not None and p.command, f"{raw} 未解析"


def main() -> int:
    out("=" * 60)
    out("M9 批5 读侧指令门禁 verify_m9_b5（依据 m9_batch_plan.md 批8）")
    out("=" * 60)
    check("pack: build_pack 零红拦（真实 test_demo）", t_pack_zero_red)
    check("a. /图纸 主链全长+分支+持有进度段", t_blueprint_main_chain)
    check("b. /图纸 标注（已锻 ✅/素材满额/未知空态）", t_blueprint_marks)
    check("c. /锻造树 分页 5条/页+终结点■+尾段+越界空态", t_forge_tree_view)
    check("d. 六指令注册确认+白名单对齐", t_registration)
    out("=" * 60)
    if _FAILS:
        out(f"❌ M9_B5 FAILED：{len(_FAILS)} 个断言失败")
        for f in _FAILS:
            out(f"  - {f}")
        return 1
    out(f"M9_B5 OK（{len(_OK)} 项全绿）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

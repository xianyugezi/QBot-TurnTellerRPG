"""批62 · 装备淬炼独立指令壳 `/淬炼` · 验收（含真机端到端）。

依据：`docs/深度打造_决策记录.md` §二十二（批57 登记：引擎/状态/配置/校验齐备、
  `/淬炼` 独立指令壳未做 · D13）+ `/root/deliverables/淬炼与分解回收_实现口径.md`
  §2（上限 / 消耗 / 参数表）+ §5 D 组（`D2` 可重置不返还、`D6` 返还衰减）。

覆盖：
  A. 指令名**零冲突**全量扫描（白名单 / 注册名 / `CommandSpec.aliases` / 各包
     `settings.command_aliases` 四源）+ `check_consistency` 双向一致；
  B. 交互纯壳：查看上限/消耗、执行单项/多项、越限 / 精粹不足 / 未启用 / 未找到 /
     同名多件 / 无等级 / 未注册 / 战斗锁 —— 全部模板表人话（不崩、不静默）；
  C. 真机端到端（只读 `content/zz_craft_demo` 的**临时副本**）：查看 → 淬炼单项
     （前后数值 + 精粹扣减）→ 越限被拒 → 未启用提示；落档往返。

纪律：临时内容根 / 临时库；真实示例包**一个字节不写**；临时合成装备不写真实内容包。
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from qbot_rpg.assembly.router_setup import build_router, check_consistency
from qbot_rpg.commands.parsers import DEFAULT_FREE_ARG_COMMANDS, DEFAULT_WHITELIST
from qbot_rpg.commands.temper_commands import TEMPER_CMD, cmd_temper
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import Player, PlayerAttributes

REPO = Path(__file__).resolve().parents[2]
DEMO_PACK = REPO / "content" / "zz_craft_demo"


def _parsed(*args: str, targets: Optional[List[str]] = None) -> Any:
    return SimpleNamespace(args=list(args), targets=list(targets or []), error=None,
                           raw=None, command=TEMPER_CMD)


# ===========================================================================
# A) 指令名零冲突扫描（四源 + 一致性）
# ===========================================================================
def _router() -> Any:
    """最小装配出全量注册表（settings 空 → make_context/shortcuts 缺省，仅做名称扫描）。"""
    return build_router(SimpleNamespace(settings={}, shortcuts={}))


def _pack_alias_tokens() -> Dict[str, List[str]]:
    """全内容包 `settings.command_aliases` 的键与值 → {来源: [别名 token]}。"""
    out: Dict[str, List[str]] = {}
    content = REPO / "content"
    for settings_path in sorted(content.glob("*/settings.json")):
        try:
            doc = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        aliases = doc.get("command_aliases")
        if not isinstance(aliases, dict):
            continue
        tokens: List[str] = []
        for key, value in aliases.items():
            tokens.append(str(key))
            if isinstance(value, str):
                tokens.append(value)
            elif isinstance(value, dict):
                for k2 in ("alias", "command"):
                    if isinstance(value.get(k2), str):
                        tokens.append(value[k2])
        out[str(settings_path.parent.name)] = tokens
    return out


def test_command_name_zero_conflict_across_four_sources() -> None:
    """`淬炼` 四源零冲突：注册名唯一、无任何别名/白名单重复、包别名表不占用。"""
    router = _router()
    names = list(router.names())
    aliases = set(router.aliases.alias_names())
    pack_aliases = _pack_alias_tokens()

    # ① 注册名：恰好一次（Router.register 重名会抛 → 能构建即无重名）
    assert names.count(TEMPER_CMD) == 1, [n for n in names if n == TEMPER_CMD]
    # ② 白名单：已登记（缺 → S5 静默不响应）；frozenset 天然唯一
    assert TEMPER_CMD in DEFAULT_WHITELIST
    # ③ CommandSpec.aliases / 装配别名表：无同名别名（别名会与原指令混淆）
    assert TEMPER_CMD not in aliases, sorted(a for a in aliases if a == TEMPER_CMD)
    # ④ 各内容包 settings.command_aliases：键与值均不占用（含 veinborn 的 任务→领取任务）
    hitting = {pkg: [t for t in toks if t == TEMPER_CMD] for pkg, toks in pack_aliases.items()}
    assert all(not v for v in hitting.values()), hitting
    # 一致性：注册 ↔ 白名单双向无硬差异
    report = check_consistency(router)
    assert report["ok"] is True
    assert report["registered_not_whitelisted"] == []
    assert TEMPER_CMD not in report["whitelist_not_registered"]
    # 自由参数登记（`,` 列表 / 多位置参数豁免 S7 铁律 3）
    assert TEMPER_CMD in DEFAULT_FREE_ARG_COMMANDS


def test_command_routes_through_real_parser() -> None:
    """真解析器：`/淬炼 铁剑 atk*2` → args；逗号列表 → targets（既有 `*`/`,` 约定）。"""
    from qbot_rpg.commands.parsers import parse_command

    single = parse_command(f"/{TEMPER_CMD} 铁剑 atk*2", whitelist=DEFAULT_WHITELIST,
                           free_arg_commands=DEFAULT_FREE_ARG_COMMANDS)
    assert single.error is None
    assert single.args == ["铁剑", "atk*2"] and single.targets == []
    listed = parse_command(f"/{TEMPER_CMD} 铁剑 atk*2,hp*1", whitelist=DEFAULT_WHITELIST,
                           free_arg_commands=DEFAULT_FREE_ARG_COMMANDS)
    assert listed.error is None
    assert listed.targets == ["atk*2", "hp*1"]
    # 装配路径差异兜底：`targets` 未展开时按 `,` 拆 `args[1:]`（本壳两条路径都吃）
    from qbot_rpg.commands.temper_commands import _stat_tokens

    assert _stat_tokens(_parsed("铁剑", "atk*2,hp*1")) == ["atk*2", "hp*1"]
    assert _stat_tokens(listed) == ["atk*2", "hp*1"]


# ===========================================================================
# B) 交互纯壳（合成实例夹具，零真实内容包业务名）
# ===========================================================================
_ENH = {"temper": {"enabled": True, "cap_per_level": 6, "cost_per_point": {"essence": 100,
                                                                           "currency": 0},
                   "value_per_point": 1.0, "per_stat_cap_ratio": 0.5, "points_per_action": 1}}
_SETTINGS = {"currencies": [{"id": "essence", "name": "装备精粹"}]}


def _item(**over: Any) -> ItemInstance:
    base: Dict[str, Any] = {"item_id": "blade", "name": "试剑", "count": 1, "quality": "rare",
                            "bound": False, "stats_bonus": {"atk": 12.0}, "required_level": 5,
                            "temper_alloc": {}}
    base.update(over)
    return ItemInstance(**base)


def _ctx(items: Optional[List[Any]] = None, *, essence: int = 5000, enhance: Any = None,
         **over: Any) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "player": {"name": "试", "inventory": items if items is not None else [_item()],
                   "currencies": {"essence": essence}},
        "enhance": _ENH if enhance is None else enhance,
        "settings": _SETTINGS,
    }
    ctx.update(over)
    return ctx


def test_view_shows_cap_used_remaining_and_cost() -> None:
    out = cmd_temper(_parsed("试剑"), _ctx())
    assert "淬炼上限 0/30" in out and "剩余 30" in out
    assert "攻击 0/15" in out and "每点 100 装备精粹" in out
    assert "❌" not in out and "✅" not in out  # 禁 emoji（本批文案口径）


def test_execute_single_and_writes_back() -> None:
    ctx = _ctx()
    out = cmd_temper(_parsed("试剑", "atk*2"), ctx)
    row = ctx["player"]["inventory"][0]
    assert "淬炼成功" in out and "攻击 12→14" in out and "消耗 装备精粹 200" in out
    assert row.temper_alloc == {"atk": 2} and row.stats_bonus == {"atk": 14.0}
    assert ctx["player"]["currencies"]["essence"] == 4800
    # 幂等：重放同一操作 → 不双计分配（分配是唯一事实源）
    again = cmd_temper(_parsed("试剑", "atk*1"), ctx)
    assert "攻击 14→15" in again
    assert ctx["player"]["inventory"][0].temper_alloc == {"atk": 3}


def test_execute_comma_list_multi_stat() -> None:
    ctx = _ctx(items=[_item(stats_bonus={"atk": 12.0, "hp": 5.0})])
    out = cmd_temper(_parsed("试剑", targets=["atk*1", "hp*2"]), ctx)
    row = ctx["player"]["inventory"][0]
    assert row.temper_alloc == {"atk": 1, "hp": 2}
    assert row.stats_bonus == {"atk": 13.0, "hp": 7.0}
    assert ctx["player"]["currencies"]["essence"] == 5000 - 3 * 100
    assert "攻击 12→13" in out and "生命 5→7" in out


def test_over_per_stat_and_total_cap_rejected() -> None:
    ctx = _ctx()
    per = cmd_temper(_parsed("试剑", "atk*99"), ctx)
    assert "单项上限 15" in per
    assert ctx["player"]["inventory"][0].temper_alloc == {}  # 拒绝零写
    # 总上限：per_stat_cap_ratio=1.0 → 单项上限 == 总上限，故先过单项、卡在总值
    enh = {"temper": {"enabled": True, "cap_per_level": 6,
                      "cost_per_point": {"essence": 100, "currency": 0},
                      "value_per_point": 1.0, "per_stat_cap_ratio": 1.0}}
    total = cmd_temper(_parsed("试剑", "hp*5"), _ctx(
        enhance=enh, items=[_item(stats_bonus={"atk": 12.0, "hp": 5.0},
                                  temper_alloc={"atk": 10, "hp": 19})]))
    assert "超出总上限" in total and "总上限 30" in total and "已投 29" in total


def test_not_enough_essence_rejected() -> None:
    ctx = _ctx(essence=50)
    out = cmd_temper(_parsed("试剑", "atk*1"), ctx)
    assert "精粹不足" in out and "需要 100" in out and "持有 50" in out
    assert ctx["player"]["inventory"][0].temper_alloc == {}


def test_disabled_prompt_and_no_write() -> None:
    ctx = _ctx(enhance={"temper": {"enabled": False}})
    out = cmd_temper(_parsed("试剑", "atk*1"), ctx)
    assert out == "淬炼未启用"
    assert ctx["player"]["inventory"][0].temper_alloc == {}
    assert ctx["player"]["currencies"]["essence"] == 5000


def test_guard_prompts() -> None:
    # 未注册
    assert cmd_temper(_parsed("试剑"), {"enhance": _ENH}) == "请先注册角色"
    # 战斗锁
    assert cmd_temper(_parsed("试剑"), _ctx(in_battle=True)) == "战斗中不可淬炼"
    # 未找到 / 同名多件
    assert "未找到装备" in cmd_temper(_parsed("无此"), _ctx())
    amb = cmd_temper(_parsed("试剑"), _ctx(items=[_item(), _item(item_id="blade2")]))
    assert "候选多件装备" in amb and "请写完整名称" in amb
    # 无等级 → 无上限
    nolv = cmd_temper(_parsed("旧刀"), _ctx(items=[_item(name="旧刀", required_level=0)]))
    assert "该装备没有淬炼上限" in nolv
    # 属性非法 / 点数非法 / 缺属性
    assert "不可淬炼" in cmd_temper(_parsed("试剑", "foo*1"), _ctx())
    assert "点数须为正整数" in cmd_temper(_parsed("试剑", "atk*0"), _ctx())
    assert cmd_temper(_parsed("试剑"), _ctx())  # 无属性参数 = 查看（非错误）


def test_at_max_view_and_uid_target() -> None:
    full = _item(temper_alloc={"atk": 30})
    ctx = _ctx(items=[full])
    assert "已达总上限 30/30" in cmd_temper(_parsed("试剑"), ctx)
    # 按 uid 定位同样命中（32 位十六进制）
    assert "已达总上限 30/30" in cmd_temper(_parsed(full.uid), _ctx(items=[full]))


def test_stats_bonus_or_alloc_object_only_not_supported_negative() -> None:
    """无 uid 的旧档物品（不可精确淬炼）→ 未找到（不误伤、不崩）。"""
    row = _item()
    object.__setattr__(row, "uid", "")
    assert "未找到装备" in cmd_temper(_parsed("试剑"), _ctx(items=[row]))


# ===========================================================================
# C) 真机端到端（只读 `content/zz_craft_demo` 的临时副本）
# ===========================================================================
_QID = "62001"


def _player(essence: int = 5000) -> Player:
    return Player(
        qid=_QID, name="示例匠", job_id="warrior", level=35, hp=10, mp=999,
        currencies={"coins": 0, "gem": 0, "essence": essence},
        inventory=(ItemInstance(item_id="demo_blade", name="铁剑", count=1, quality="rare",
                                bound=False, stats_bonus={"atk": 12.0, "hp": 5.0},
                                required_level=5, temper_alloc={}),),
        attributes=PlayerAttributes(base={"hp": 100000.0, "mp": 100.0}),
        persistent_state={"proficiency": {"alchemy": {"level": 60, "exp": 0, "sp_earned": 0,
                                                      "sp_used": 0, "unlocks": {}}},
                          "learned_blueprints": {}},
    )


def _copy_pack(tmp_path: Path, *, temper_enabled: bool = True) -> Path:
    """`zz_craft_demo` 临时副本（只读真实包；开关淬炼仅在副本上改）。"""
    pack = Path(tempfile.mkdtemp(prefix="b62-pack-", dir=str(tmp_path))) / "zz_craft_demo"
    shutil.copytree(DEMO_PACK, pack)
    enh_path = pack / "enhance.json"
    doc = json.loads(enh_path.read_text(encoding="utf-8"))
    temper = dict(doc.get("temper") or {})
    temper["enabled"] = bool(temper_enabled)
    doc["temper"] = temper
    enh_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return pack


async def _run(commands: List[str], tmp_path: Path, *, temper_enabled: bool = True,
               essence: int = 5000) -> Dict[str, Any]:
    from qbot_rpg.assembly.testing_support import pack_app, send_command

    pack = _copy_pack(tmp_path, temper_enabled=temper_enabled)
    outputs: List[str] = []
    async with pack_app(pack) as deps:
        repo = deps.repo
        await repo.save_player(_player(essence))
        for msg in commands:
            outputs.append(await send_command(deps, msg, user_id=_QID))
        p = await repo.load_player(_QID)
    row = p.inventory[0]
    return {"outputs": outputs, "alloc": dict(row.temper_alloc),
            "bonus": dict(row.stats_bonus), "essence": int(dict(p.currencies).get("essence", 0))}


@pytest.mark.asyncio
async def test_e2e_view_temper_over_limit_and_persist(tmp_path: Path) -> None:
    """真机链路：查看 → 淬炼单项（前后数值 + 精粹扣减）→ 越限被拒（读档复核零写）。"""
    res = await _run([f"/{TEMPER_CMD} 铁剑", f"/{TEMPER_CMD} 铁剑 atk*2",
                      f"/{TEMPER_CMD} 铁剑", f"/{TEMPER_CMD} 铁剑 atk*999"],
                     tmp_path)
    view0, exec1, view1, over = res["outputs"]
    # 查看：初始上限 / 已投 / 每点消耗（内容包声明 1593）
    assert "淬炼上限 0/30" in view0 and "攻击 0/15" in view0 and "1593" in view0
    # 淬炼单项：atk 12→14，扣 3186 精粹（1593×2）
    assert "淬炼成功" in exec1 and "攻击 12→14" in exec1 and "3186" in exec1
    assert "生命 5→5" not in exec1  # 未投的属性不出现
    # 落档复核：分配 + 面板 + 精粹
    assert res["alloc"] == {"atk": 2} and res["bonus"]["atk"] == 14.0
    assert res["essence"] == 5000 - 3186
    # 查看反映已投
    assert "淬炼上限 2/30" in view1 and "攻击 2/15" in view1
    # 越限被拒（贴提示）+ 零写（读档仍为 2 点 / 1814）
    assert "单项上限 15" in over and "已投 2" in over
    assert res["alloc"] == {"atk": 2} and res["essence"] == 1814


@pytest.mark.asyncio
async def test_e2e_multi_stat_comma_list(tmp_path: Path) -> None:
    """真机链路：`,` 列表多项（atk*1,hp*2）→ 一次落账，两属性各改，精粹合并扣减。"""
    res = await _run([f"/{TEMPER_CMD} 铁剑 atk*1,hp*2"], tmp_path)
    out = res["outputs"][0]
    assert "攻击 12→13" in out and "生命 5→7" in out
    assert res["alloc"] == {"atk": 1, "hp": 2}
    assert res["bonus"] == {"atk": 13.0, "hp": 7.0}
    assert res["essence"] == 5000 - 3 * 1593


@pytest.mark.asyncio
async def test_e2e_not_enabled_prompt(tmp_path: Path) -> None:
    """真机链路：未启用淬炼 → 人话提示（不是崩、不是静默），零状态写。"""
    res = await _run([f"/{TEMPER_CMD} 铁剑", f"/{TEMPER_CMD} 铁剑 atk*1"],
                     tmp_path, temper_enabled=False)
    assert all("淬炼未启用" in line for line in res["outputs"]), res["outputs"]
    assert all("❌" not in line for line in res["outputs"])
    assert res["alloc"] == {} and res["essence"] == 5000

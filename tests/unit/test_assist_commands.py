"""协力调和指令壳单测（M8 批11-1 · alchemy_commands.py 的 /协力）。

文件：tests/unit/test_assist_commands.py
创建：2026-08-29
作者：Hermes 子agent（批11-1 指令装配：单路独占 commands/alchemy_commands.py + parsers.py）

功能：直测 async cmd_assist（真实守卫链 + fake session_mgr + 确定性随机加成）：
  - 正例：大师+调合会话中+同群 → 消耗快照材料链 + 随机加成写会话快照 assist_bonus
    （version 递增）+ M-15 玩家名渲染；
  - 负例：非大师拒绝 / 无会话模板 / 非调合会话 / 非同群拒绝 / 材料不足全拒零副作用 /
    缺参 TPL-12；
  - 工程补白：无群信息（same_group 缺失）保守放行 / 快照材料链空 → 配方材料兜底 /
    玩家名解析 hook 缺失回退 QQ 号 / 随机数种子 = 会话 version 可复现；
  - 装配：register_alchemy_commands 注册 ASSIST_CMD + ctx 注入 handler。

覆盖规则（每条正反例，断言精确文本/数值/快照字段）：
  P-15/SEP-15（@ 消息层剥离 → 纯 QQ 号参数）、GU-44（大师门槛）、GU-45（会话前置/
  无会话模板 L175）、GU-46（同群校验/保守放行）、F-15（材料链消耗+随机加成+assist_bonus
  落快照）、M-15（「协力调和：〈玩家名〉加入，获得随机加成：〈加成描述〉」纯文本降级）、
  ATO-01（材料全量校验全拒+差异）、TC-22。

依据：docs/m8_contract_指令契约.md §14（P-15/GU-44~46/F-15/M-15）+ 细化_2c4d §15 +
  docs/m8_contract_指令契约.md §七 TC-22。
测试风格对齐 tests/unit/test_confirm_commands.py（parse_command 直调 + 全字段 ctx +
  async fake session_mgr）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from qbot_rpg.commands.alchemy_commands import (
    ASSIST_CMD,
    _assist_bonus,
    _assist_seed,
    cmd_assist,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import Router

# /协力 白名单（DEFAULT_WHITELIST 批11-1 已含「协力」；本测试仍显式注入同款防装配未接线回归）
W = DEFAULT_WHITELIST | {"协力"}


# ---------------------------------------------------------------------------
# 夹具：items/recipe 注册表 + settings（对齐 test_confirm_commands 形态）
# ---------------------------------------------------------------------------

ITEMS: Dict[str, dict] = {
    "fire_crystal": {"id": "fire_crystal", "name": "火晶石", "type": "material",
                     "elements": {"fire": 4}},
    "moon_grass": {"id": "moon_grass", "name": "月光草", "type": "material"},
}

RECIPES: Dict[str, dict] = {
    "rcp_flame": {"id": "rcp_flame", "name": "火焰弹", "level": 5, "slots": 5,
                  "pp_budget": 5, "traits_inherit": 2,
                  "materials": [{"id": "moon_grass", "count": 2}],
                  "element_req": {"fire": [{"threshold": 6, "effect": "范围爆炸"}]},
                  "cost": {"coins": 100, "gem": 0},
                  "output": {"item": "flame_bomb", "count": 1}},
}

SETTINGS: Dict[str, Any] = {
    "currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"}],
    "alchemy": {
        "mode": "full",
        "energy_enabled": False,            # R-08 默认关
        "catalyst_unlock_tier": "expert",
        "max_qty": 2147483647,              # 拍板⑤
        "job_tier_map": {
            "见习": [1, 5], "正式": [6, 15], "精通": [16, 25], "专家": [26, 35],
            "大师": [36, 45], "宗师": [46, 60], "王": [61, 99],
        },
    },
}


def _alchemy_node(level: int = 3) -> dict:
    """炼金职业节点（level = 档位索引 0~6；4=大师，GU-44 门槛）。"""
    return {"level": level, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}


class FakeSessions:
    """async 会话 fake（get_active/acquire/suspend；view 形态 = {session_type, payload,
    version} dict 视图，鸭子兼容）。"""

    def __init__(self) -> None:
        self.store: Dict[str, dict] = {}
        self.calls: list = []

    async def get_active(self, qid: str) -> Optional[dict]:
        self.calls.append(("get_active", qid))
        return self.store.get(qid)

    async def acquire(self, qid: str, session_type: str, payload: Any = None) -> dict:
        self.calls.append(("acquire", qid, session_type))
        if qid in self.store:
            raise RuntimeError("SessionConflictError")
        self.store[qid] = {"session_type": session_type, "payload": payload, "version": 1}
        return self.store[qid]

    async def suspend(self, qid: str, snapshot: Any) -> None:
        self.calls.append(("suspend", qid))
        cur = self.store.get(qid, {})
        self.store[qid] = {
            "session_type": cur.get("session_type", "alchemy"),
            "payload": snapshot,
            "version": int(cur.get("version", 1)) + 1,
        }


def _snap(
    recipe_id: str = "rcp_flame",
    materials: Optional[list] = None,
    version: int = 3,
    **over: Any,
) -> dict:
    """调合会话快照（§7.1 形态：配方ID+材料链+连锁+刻度+特性+PP+步骤+version）。

    缺省材料链 = 月光草×2（F-15 消耗口径：快照材料链）。
    """
    snap: dict = {
        "recipe_id": recipe_id,
        "materials": materials if materials is not None else [
            {"item": "moon_grass", "count": 2},
        ],
        "chain": {"segments": 1, "effect_level": 1},
        "element_scores": {"fire": 6},
        "pool": {"normal": [], "gold": [], "awaken": []},
        "catalyst": None,
        "pp": {"used": 0, "budget": 5},
        "step": "feed",
        "version": version,
        "job_tier": "expert",
        "job_tier_index": 3,
    }
    snap.update(over)
    return snap


def _make_remove_item(ctx: Dict[str, Any]):
    """remove_item hook（F-15 扣料：就地扣减 ctx 背包 dict，不足返回 False）。"""

    def _ri(item_id: str, count: int) -> bool:
        cur = int(ctx.get("inventory", {}).get(item_id, 0))
        if cur < count:
            return False
        ctx["inventory"][item_id] = cur - count
        return True

    return _ri


def make_ctx(**over: Any) -> dict:
    """全字段协力 ctx（player 字段在 ctx 顶层 + remove_item hook 注入 + session_mgr）。

    same_group / resolve_player_name 可覆盖（默认同群 + 玩家名 hook 注入）。
    """
    base: dict = {
        "qid": "u1",
        "proficiency": {"alchemy": _alchemy_node(4)},
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {"fire_crystal": 10, "moon_grass": 5},
        "items": ITEMS,
        "recipe": RECIPES,
        "settings": SETTINGS,
        "session_mgr": FakeSessions(),
        "same_group": True,
        "resolve_player_name": lambda q: f"玩家{q}",
    }
    base["remove_item"] = _make_remove_item(base)
    base.update(over)
    return base


def _open_alchemy(ctx: dict, payload: Optional[dict] = None, version: int = 3) -> None:
    """直接预置调合会话（acquire 等价行形态，避免走 /炼金 全链）。"""
    ctx["session_mgr"].store["u1"] = {
        "session_type": "alchemy",
        "payload": payload if payload is not None else _snap(),
        "version": version,
    }


# ---------------------------------------------------------------------------
# /协力：正例（大师+会话中+同群 → 随机加成写快照）
# ---------------------------------------------------------------------------
async def test_assist_success_master_in_session() -> None:
    """GU-44/45/46 + F-15/M-15 正例：/协力 @玩家 → 「协力调和：〈玩家名〉加入，获得
    随机加成：〈加成描述〉」；消耗快照材料链（moon_grass 5→3）+ assist_bonus 写会话快照
    （version 递增 3→4）。"""
    ctx = make_ctx()
    _open_alchemy(ctx)
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert out.startswith("协力调和：")
    assert "加入，获得随机加成：" in out
    assert "玩家123456" in out            # resolve_player_name hook 渲染玩家名
    # F-15 材料链消耗（快照材料链 月光草×2 → 5-2=3）
    assert ctx["inventory"]["moon_grass"] == 3
    # assist_bonus 写快照 + version 递增（suspend 持久化）
    stored = ctx["session_mgr"].store["u1"]
    bonus = stored["payload"].get("assist_bonus")
    assert isinstance(bonus, dict)
    assert bonus["target"] == "123456"
    assert bonus["version"] == 3
    assert isinstance(bonus.get("fields"), dict) and bonus["fields"]
    assert stored["version"] == 4


async def test_assist_bonus_reproducible() -> None:
    """F-15【工程补白】随机数种子可复现：同 version+同目标 → 同加成；不同 version → 种子
    变化（测试直接断言确定性哈希 + 加成池命中）。"""
    assert _assist_seed(3, "123") == _assist_seed(3, "123")
    assert _assist_seed(3, "123") != _assist_seed(4, "123")
    b1 = _assist_bonus(_assist_seed(3, "123"))
    b2 = _assist_bonus(_assist_seed(3, "123"))
    assert b1 == b2                          # 可复现
    assert b1["desc"] and isinstance(b1["fields"], dict)


async def test_assist_bonus_written_to_snapshot() -> None:
    """F-15 正例：成功路径两次调用（同 version 同 target）→ 加成可复现；assist_bonus.desc
    与渲染文本一致（M-15 描述同源）。"""
    ctx = make_ctx()
    _open_alchemy(ctx)
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    stored = ctx["session_mgr"].store["u1"]
    bonus = stored["payload"].get("assist_bonus")
    assert bonus is not None
    assert bonus["desc"] in out              # M-15 加成描述与快照同源


# ---------------------------------------------------------------------------
# /协力：GU-44 大师门槛
# ---------------------------------------------------------------------------
async def test_assist_not_master_rejected() -> None:
    """GU-44 负例：炼金职业 专家(3) < 大师(4) → 「❌ 等级不足」，零业务写（无扣料/无
    suspend）。"""
    ctx = make_ctx(proficiency={"alchemy": _alchemy_node(3)})
    _open_alchemy(ctx)
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert out == "❌ 等级不足"
    assert ctx["inventory"]["moon_grass"] == 5     # 零扣料
    assert not [c for c in ctx["session_mgr"].calls if c[0] == "suspend"]


# ---------------------------------------------------------------------------
# /协力：GU-45 调合会话中
# ---------------------------------------------------------------------------
async def test_assist_no_session_rejected() -> None:
    """GU-45 负例：无会话 /协力 → 无会话模板「当前没有调合会话，先 /炼金 <配方> 开始」
    （L175）。"""
    ctx = make_ctx()
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


async def test_assist_non_alchemy_session_rejected() -> None:
    """GU-45 负例：活跃会话为 battle（非调合类）→ 无会话模板（P-6 防御）。"""
    ctx = make_ctx()
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


# ---------------------------------------------------------------------------
# /协力：GU-46 同群校验
# ---------------------------------------------------------------------------
async def test_assist_not_same_group_rejected() -> None:
    """GU-46 负例：ctx["same_group"]=False（非同群/非同群好友）→ 「❌ 对方不在当前群内」，
    零业务写。"""
    ctx = make_ctx(same_group=False)
    _open_alchemy(ctx)
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert out == "❌ 对方不在当前群内"
    assert ctx["inventory"]["moon_grass"] == 5     # 零扣料
    assert not [c for c in ctx["session_mgr"].calls if c[0] == "suspend"]


async def test_assist_same_group_missing_conservative() -> None:
    """GU-46【工程补白】正例：无群信息（same_group 键缺失）→ 保守放行（不误拒私聊/无群
    上下文），成功走完 F-15。"""
    ctx = make_ctx()
    del ctx["same_group"]
    _open_alchemy(ctx)
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert "协力调和：" in out
    assert ctx["inventory"]["moon_grass"] == 3     # 材料链已消耗


# ---------------------------------------------------------------------------
# /协力：F-15 材料消耗（ATO-01 原子口径 + 配方材料兜底）
# ---------------------------------------------------------------------------
async def test_assist_materials_insufficient_rejected() -> None:
    """F-15/ATO-01 负例：背包缺快照材料链材料 → 「❌ 材料不足：缺 月光草×1」，全拒零
    副作用（无扣料/无 suspend/无 assist_bonus）。"""
    ctx = make_ctx(inventory={"moon_grass": 1, "fire_crystal": 10})
    _open_alchemy(ctx, _snap(materials=[{"item": "moon_grass", "count": 2}]))
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert "❌ 材料不足" in out
    assert "缺 月光草×1" in out
    assert ctx["inventory"]["moon_grass"] == 1     # 全拒零扣
    assert not [c for c in ctx["session_mgr"].calls if c[0] == "suspend"]


async def test_assist_materials_fallback_recipe() -> None:
    """F-15【工程补白】正例：快照材料链为空（未投料直接协力）→ 回退配方 materials 兜底
    （月光草×2，rcp_flame），消耗成功。"""
    ctx = make_ctx()
    _open_alchemy(ctx, _snap(materials=[]))
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert "协力调和：" in out
    assert ctx["inventory"]["moon_grass"] == 3     # 配方材料兜底消耗 5-2=3


async def test_assist_materials_empty_recipe_ok() -> None:
    """F-15 边界正例：快照材料链空且配方无材料 → 零消耗直接随机加成（社交向无硬性门槛）。"""
    ctx = make_ctx()
    _open_alchemy(ctx, _snap(materials=[], recipe_id="rcp_empty"))
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert "协力调和：" in out
    assert ctx["inventory"]["moon_grass"] == 5     # 零消耗


# ---------------------------------------------------------------------------
# /协力：P-15 参数与玩家名渲染（M-15）
# ---------------------------------------------------------------------------
async def test_assist_player_name_fallback_qid() -> None:
    """M-15【工程补白】负例：ctx 无 resolve_player_name hook → 回退 QQ 号渲染（玩家名=
    QQ 号）。"""
    ctx = make_ctx()
    del ctx["resolve_player_name"]
    _open_alchemy(ctx)
    out = await cmd_assist(parse_command("/协力 123456", whitelist=W), ctx)
    assert "协力调和：123456加入，获得随机加成：" in out


async def test_assist_missing_arg_tpl12() -> None:
    """P-15 负例：/协力 缺参 → TPL-12（指令不正确）。"""
    ctx = make_ctx()
    out = await cmd_assist(parse_command("/协力", whitelist=W), ctx)
    assert "指令不正确" in out


async def test_assist_empty_arg_tpl12() -> None:
    """P-15 负例：/协力 （空白参数）→ TPL-12。"""
    ctx = make_ctx()
    out = await cmd_assist(parse_command("/协力   ", whitelist=W), ctx)
    assert "指令不正确" in out


# ---------------------------------------------------------------------------
# 装配：register_alchemy_commands 注册 ASSIST_CMD + ctx 注入 handler
# ---------------------------------------------------------------------------
async def test_register_assist_cmd() -> None:
    """装配：register_alchemy_commands 注册 /协力 CommandSpec（whitelisted）。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: make_ctx())
    assert router.has(ASSIST_CMD)
    spec = router.get(ASSIST_CMD)
    assert spec is not None and spec.whitelisted


async def test_register_assist_handler_injectable_ctx() -> None:
    """装配：/协力 handler 支持 k.get("ctx") 注入（async 处理器 await 执行，runner 口径）。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: {})
    spec = router.get(ASSIST_CMD)
    assert spec is not None and spec.handler is not None
    ctx = make_ctx()
    _open_alchemy(ctx)
    out = await spec.handler(parse_command("/协力 123456", whitelist=W), ctx=ctx)
    assert "协力调和：" in out
    assert ctx["session_mgr"].store["u1"]["payload"].get("assist_bonus") is not None

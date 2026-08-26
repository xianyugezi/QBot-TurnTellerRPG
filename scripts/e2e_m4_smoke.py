#!/usr/bin/env python3
"""M4 端到端集成冒烟（M4 批次7·路H1）：NPC→商店→任务→签到→快捷→翻页夹取 全链路，固定种子可重放。

依据：
  - m4_shared_contract.md §5（完成判据：端到端 NPC 对话 → 商店购买 → 任务接取/交付 → 签到
    全链路冒烟；固定种子可重放）+ §0（用户 8 项拍板：裁决① 战斗中裸数字=快捷表；裁决② 页码越界
    夹取最后一页 +「已到最后一页」/ 0·负数·非数字 → TPL-12；裁决③ 对话树深度可配；裁决⑤ 库存+
    个人限购同条目并存；裁决⑦ 补签只计不补发；裁决⑧ [签到:<表名>.<字段>] 三键）
  - docs/细化/细化_2b1_NPC数据与发牌员.md（/对话 列表·序号·名称；发牌员策略；一次一物 L83-92）
  - docs/细化/细化_2b2_对话会话状态机.md（七态十五迁移；菜单 ≤6 折叠；退出三词同义；恢复简报）
  - docs/细化/细化_2b3_商店引擎契约.md（/商店 列表·浏览·购买；6 步校验链；库存+个人限购并存裁决⑤；
    余额不足差额提示）
  - docs/细化/细化_2b4_任务引擎契约.md（/任务 接取 N / 交付 N / 信息 N；三原语条件；统一 reward 入账）
  - docs/细化/细化_2b5_签到引擎契约.md（/签到 结算·连签·补签；多表一次结算；裁决⑦ 只计不补发；
    裁决⑧ 三键取值）
  - docs/细化/细化_3c_指令解析契约.md + 细化_3d_消息模板规范.md（快捷表路由裁决①；列表 5 条/页；
    TPL-08 页脚；TPL-12 报错；页码夹取裁决②）

装配：真实模块（commands/shop_commands·quest_commands·checkin_commands·parsers·router、
core/shop·quest·checkin·dialog·npc·reward·dayroll）；npc/shop/quest/checkin/items 数据读取自
tests/fixtures/packs/legal/；注入固定 now（2026-08-01 12:00 UTC+8，dayroll today=2026-08-01）
与固定 rng 种子（20260801），保证确定性。零 NoneBot import。

【工程补白 · 显式标注】（定稿/契约未明示处，不冒充定稿）：
  1. 世界层地图过滤未接线：/对话 的 NPC 集合 = legal npc.json 全部可见 NPC（世界层按当前地图过滤
     属装配职责，冒烟直接注入 npc 列表驱动 DialogSession 状态机）。
  2. legal shop.json 无 per_player 限购条目：冒烟在 village_shop 追加一条「秘药」限购条目
     （per_player=1/period=day，裁决⑤ 库存+限购同条目并存），items 注册表同步补注册秘药。
  3. legal checkin.json 未开启补签：冒烟为 checkin_loop 补配 makeup{enabled, cost, max_per_month}
     （裁决⑦ 补签只计不补发验证用）。
  4. 签到引擎接口漂移桥接：core/checkin.py（路F2）暴露 checkin_do/checkin_state/checkin_makeup/
     resolve_checkin_table；commands/checkin_commands.py（路F3）按 checkin_today/checkin_status/
     checkin_makeup(table_id, ctx) 消费（F2 未收口时的契约签名）。冒烟经文档化注入点
     ctx["checkin_engine"] 挂薄适配器 CheckinAdapter 桥接两套接口（不改任何生产模块）。
  5. NPC 动作执行（dispatch_action）与已听集合持久化（heard 落玩家存档）/事件计数（longline_counters）
     /商店移交（current_shop_ref）属装配层职责：冒烟在状态机结果驱动处就地应用
     mark_heard/events/shop_refs（与 e2e_m3_smoke 的补白口径一致）。

铁律：零 NoneBot import；确定性（固定 now/种子，两次运行摘要逐字一致）；文件头标注依据。

用法：.venv/bin/python scripts/e2e_m4_smoke.py
退出码：0 = 全绿（打印「M4 端到端冒烟全绿（NPC→商店→任务→签到→快捷→翻页夹取）」）；1 = 有失败。
"""
from __future__ import annotations

import copy
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))  # 独立可运行：scripts/ 下直接执行也可见 qbot_rpg

from qbot_rpg.commands.shop_commands import cmd_shop, cmd_buy, cmd_sell
from qbot_rpg.commands.quest_commands import cmd_quest
from qbot_rpg.commands.checkin_commands import cmd_checkin
from qbot_rpg.commands.parsers import parse_command, parse_int
from qbot_rpg.commands.router import (
    CommandSpec,
    Router,
    ROUTE_COMMAND,
    ROUTE_IGNORED,
    ROUTE_SESSION,
    ROUTE_SHORTCUT,
    MODE_SHORTCUT,
    MODE_SESSION_DIGIT,
    check_shortcut_binding,
    check_shortcut_limit,
    route_and_expand,
    route_message,
)
from qbot_rpg.core import checkin as checkin_engine
from qbot_rpg.core import quest as quest_engine
from qbot_rpg.core.checkin import checkin_condition_ctx, checkin_value
from qbot_rpg.core.dayroll import today_of
from qbot_rpg.core.dialog import (
    DIALOG_ALREADY_HEARD_HINT,
    DialogSession,
    S_EXEC,
    S_IDLE,
    S_LIST,
    S_MENU,
    authored_node_depth,
    dialog_event_key,
    is_depth_blocked,
)
from qbot_rpg.core.message_format.list_render import resolve_page

# -------------------------------------------------------------------------------------
# 常量（固定 now / 种子 —— 确定性铁律）
# -------------------------------------------------------------------------------------
LEGAL_DIR = REPO / "tests" / "fixtures" / "packs" / "legal"
_TZ8 = timezone(timedelta(hours=8))
FIXED_NOW = int(datetime(2026, 8, 1, 12, 0, 0, tzinfo=_TZ8).timestamp())  # 2026-08-01 12:00 UTC+8
SEED = 20260801          # 固定 rng 种子（R8 确定性）
DAY = 86400              # 一天秒数（签到跨天推进用）
CONTENT_PACK = "legal"
GREEN_LINE = "M4 端到端冒烟全绿（NPC→商店→任务→签到→快捷→翻页夹取）"
# dayroll 固定 now → today（2026-08-01 12:00 > 05:00 重置时刻）
_TODAY = "2026-08-01"

# 签到表类型中文标注（镜像 core/checkin._TYPE_CN，适配器渲染用）
_TYPE_CN: dict = {"loop": "常驻循环", "monthly": "月度签到", "activity": "活动"}


# -------------------------------------------------------------------------------------
# 断言收集器
# -------------------------------------------------------------------------------------
class Smoke:
    """断言收集器：check/check_eq 计数；全部通过 → ok。"""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: List[str] = []

    def check(self, cond: bool, label: str) -> bool:
        if cond:
            self.passed += 1
            return True
        self.failed += 1
        self.failures.append(label)
        return False

    def check_eq(self, got: object, want: object, label: str) -> bool:
        if got == want:
            self.passed += 1
            return True
        self.failed += 1
        self.failures.append(f"{label}：期望 {want!r}，实际 {got!r}")
        return False


# -------------------------------------------------------------------------------------
# 签到引擎接口桥接适配器（工程补白 4）
# -------------------------------------------------------------------------------------
def _grant_label(grant: Mapping) -> str:
    """grant 记录 → 简短标签（镜像 core/checkin._grant_label 展示口径，供适配器渲染）。"""
    typ = grant.get("type")
    if typ == "item":
        return f"{grant.get('item')}×{grant.get('count')}"
    if typ == "currency":
        return f"{grant.get('amount')} {grant.get('currency')}"
    if typ == "exp":
        return f"exp{grant.get('amount')}"
    if typ == "rep":
        return f"声望{grant.get('amount')}"
    return str(grant)


class CheckinAdapter:
    """checkin 引擎接口桥接（工程补白 4）：把 core/checkin.py（路F2）接口适配为
    commands/checkin_commands.py（路F3）消费接口。挂 ctx['checkin_engine'] 注入点。"""

    def __init__(self, engine: Any) -> None:
        self._eng = engine

    def resolve_checkin_table(self, ctx: Mapping, arg: object) -> Optional[str]:
        """路F3 期望表 id（str）；路F2 引擎 resolve_checkin_table 仅按表 id 精确解析。

        【工程补白 4 延伸】路F2 引擎未实现「表名/序号/类型/缺省」解析（checkin_commands
        消费契约），本适配器按命令层契约补齐：缺省 → 主表 loop（裁决⑧）；表 id / 表名 /
        类型名 / 序号 1..N → 表 id；查无 → None。
        """
        tables = ctx.get("checkin_tables")
        if not isinstance(tables, Mapping) or not tables:
            return None
        if arg is None or str(arg).strip() == "":
            if "checkin_loop" in tables:
                return "checkin_loop"
            return next(iter(tables))
        s = str(arg).strip()
        if s in tables:
            return s
        for tid, t in tables.items():
            if isinstance(t, Mapping) and (str(t.get("name")) == s or str(t.get("type")) == s):
                return tid
        if s.isdigit():
            idx = int(s)
            keys = list(tables)
            if 1 <= idx <= len(keys):
                return keys[idx - 1]
        return None

    def _rows_of(self, t: Mapping) -> List[str]:
        rows: List[str] = []
        if t.get("already_signed"):
            rows.append("今天已签到（不重复发奖）")
        elif t.get("failed"):
            rows.append(t.get("message", "结算失败，已回滚"))
        else:
            daily = t.get("daily_granted") or []
            rows.append("今日奖励：" + ("、".join(_grant_label(g) for g in daily[:4]) if daily else "无"))
            for n in t.get("notes") or []:
                rows.append(str(n))
            for h in t.get("streak_hits") or []:
                labs = "、".join(_grant_label(g) for g in (h.get("granted") or [])[:4])
                rows.append(f"[连签里程碑达成] {labs}（连签 {h.get('days')} 天）")
            for h in t.get("month_hits") or []:
                labs = "、".join(_grant_label(g) for g in (h.get("granted") or [])[:4])
                rows.append(f"[月度累计达成] {labs}（本月签满 {h.get('days')} 天）")
        pc, pt = t.get("progress_current"), t.get("progress_total")
        rows.append(f"连签天数：{t.get('streak', 0)} 天 ｜ 进度 {pc}/{pt}")
        return rows

    def checkin_today(self, ctx: MutableMapping) -> dict:
        res = self._eng.checkin_do(ctx)
        if not res.get("ok"):
            return {"ok": False, "message": res.get("message") or "❌ 签到暂不可用"}
        tables = [t for t in res.get("tables") or [] if t.get("active", True)]
        # 幂等口径：仅看引擎 already_signed（今日已结算）；today_signed=1 在首次结算表上也成立，
        # 不能作为「重复指令」判据（D-02）
        all_already = bool(tables) and all(bool(t.get("already_signed")) for t in tables)
        msg = "今天已签到（重复指令，未重复发放）" if all_already else "✅ 今日签到完成"
        sections: List[dict] = []
        total = 0
        for t in tables:
            rows = self._rows_of(t)
            title = f"{t.get('name') or t.get('table_id')}（{_TYPE_CN.get(t.get('type'), t.get('type'))}）"
            sections.append({"title": title, "rows": rows})
            total += len(rows)
        return {"ok": True, "message": msg, "sections": sections, "total": total}

    def checkin_status(self, ctx: Mapping) -> dict:
        res = self._eng.checkin_state(ctx)
        if not res.get("ok"):
            return {"ok": False, "message": "❌ 签到暂不可用"}
        sections: List[dict] = []
        total = 0
        for t in res.get("tables") or []:
            if not t.get("active"):
                continue
            rows = [
                f"连签天数：{t.get('streak', 0)} 天",
                f"本月累计：{t.get('month_days', 0)} 天",
                f"今日已签：{'是' if t.get('today_signed') else '否'}",
            ]
            title = f"{t.get('name') or t.get('table_id')}（{_TYPE_CN.get(t.get('type'), t.get('type'))}）"
            sections.append({"title": title, "rows": rows})
            total += len(rows)
        return {"ok": True, "message": "✅ 签到状态", "sections": sections, "total": total}

    def checkin_makeup(self, table_id: object, ctx: MutableMapping) -> dict:
        """路F3 消费签名 checkin_makeup(table_id, ctx)；路F2 引擎签名 checkin_makeup(ctx, table_id)。"""
        return self._eng.checkin_makeup(ctx, table_id)


# -------------------------------------------------------------------------------------
# 装配：真实数据（tests/fixtures/packs/legal/）+ 固定 now/种子
# -------------------------------------------------------------------------------------
def _load(name: str) -> list:
    data = json.loads((LEGAL_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _by_id(rows: list) -> dict:
    return {r["id"]: dict(r) for r in rows if isinstance(r, Mapping) and r.get("id")}


def build_ctx(*, now: Optional[int] = None, **overrides) -> dict:
    """装配共享玩家上下文（真实 legal 数据 + 固定 now/种子；每场景新造避免互污染）。

    全链路字段契约对齐 core/shop·quest·checkin·dialog 工程补白 2 的 ctx 键空间。
    overrides 覆盖任意键（隔离子场景，如低保币值）。
    """
    items_raw = _by_id(_load("items"))
    shops_raw = _by_id(_load("shop"))
    quests_raw = _by_id(_load("quest"))
    checkin_raw = _by_id(_load("checkin"))
    npcs_raw = _load("npc")

    # 【补白 2】商店限购条目：legal shop.json 无 per_player → village_shop 追加「秘药」限购条目
    village = dict(shops_raw["village_shop"])
    village["items"] = [dict(e) for e in village["items"]]
    village["items"].append({"item": "magic_elixir", "price": 50, "stock": 0,
                             "per_player": 1, "period": "day"})
    shops_raw["village_shop"] = village
    items_raw["magic_elixir"] = {"id": "magic_elixir", "name": "秘药", "type": "consumable",
                                 "price": 50, "usable": True}

    # 【补白 3】补签开启：legal checkin.json 未开 → checkin_loop 补配 makeup（裁决⑦ 只计不补发）
    loop = dict(checkin_raw["checkin_loop"])
    loop["makeup"] = {"enabled": True, "card_item": "补签卡", "cost": {"coins": 50},
                      "max_per_month": 5}
    checkin_raw["checkin_loop"] = loop

    # 【补白 6】任务板口径：legal quest.json 的 q_potion_supply 是 zone 限定副本子任务
    # （quest_board 规则：zone 非 None → 不占板槽位，板为空）。冒烟按任务板口径改写为
    # NPC 支线（去 zone），驱动 /任务 接取→条件推进→交付→reward 全链路（结构/条件/奖励不变）。
    q = dict(quests_raw["q_potion_supply"])
    q.pop("zone", None)
    quests_raw["q_potion_supply"] = q

    # 背包 in-memory 单一事实源：add/remove/count hook 全部指向它（引擎回退同键）
    inv: Dict[str, int] = {}

    def _add_item(item_id: object, count: object, bound: bool = True) -> bool:
        key = str(item_id)
        inv[key] = inv.get(key, 0) + int(count)
        return True

    def _remove_item(item_id: object, count: object) -> bool:
        key = str(item_id)
        cur = inv.get(key, 0)
        if cur < int(count):
            return False
        inv[key] = cur - int(count)
        return True

    def _count_item(item_id: object) -> int:
        return int(inv.get(str(item_id), 0))

    ctx: dict = {
        "settings": {
            "currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"}],
            "buy_cap": 99,
            "sell_ratio": 0.3,
            "max_dialog_depth": 2,           # 裁决③：对话树深度默认 2
            "refresh_time": "05:00",         # A3 日界统一配置键（商店/任务/签到共用）
        },
        "items": items_raw,
        "shops": shops_raw,
        "quests": quests_raw,
        "checkin_tables": checkin_raw,
        "npcs": npcs_raw,                    # 【补白 1】世界层地图过滤未接线：全量可见 NPC
        "currencies": {"coins": 1000, "gem": 5},
        "inventory": inv,
        "add_item": _add_item,
        "remove_item": _remove_item,
        "count_item": _count_item,
        "exp": 0,
        "level": 5,
        "name": "阿伟",
        "reputation": 1,
        "reputation_state": {"global": 0},
        "quest_active": {},
        "quest_completed": set(),
        "quest_daily": {"key": "", "completed": 0, "accepted": 0, "decay": {}},
        "longline_counters": {},
        "event_counts": {},
        "checkin_state": {},
        "heard": set(),                      # 已听集合（一次一物落玩家存档）
        "codex_state": {},
        "current_shop_ref": None,
        "personal_buys": {},
        "world_stock": {},
        "world_sold_out": set(),
        "last_refresh": {},
        "blackmarket_goods": {},
        "rng": random.Random(SEED),
        "now": int(now) if now is not None else FIXED_NOW,
        "quest_engine": quest_engine,        # 指令层引擎注入（quest_commands 工程补白 1）
        "checkin_engine": CheckinAdapter(checkin_engine),  # 指令层引擎注入（工程补白 4）
    }
    ctx.update(overrides)  # 子场景覆盖（如 currencies 低保）
    return ctx


def _parse(raw: str):
    """parse_command 封装（默认白名单已含 商店/购买/出售/任务/签到，parsers.DEFAULT_WHITELIST）。"""
    return parse_command(raw)


def _apply_dialog_result(ctx: MutableMapping, r: dict) -> None:
    """装配层职责（工程补白 5）：应用状态机结果 mark_heard/events/shop_refs。"""
    for k in r.get("mark_heard") or []:
        heard = ctx.setdefault("heard", set())
        if isinstance(heard, set):
            heard.add(k)
    for ev in r.get("events") or []:
        llc = ctx.setdefault("longline_counters", {})
        llc[ev] = int(llc.get(ev, 0)) + 1
    refs = r.get("shop_refs") or []
    if refs:
        ctx["current_shop_ref"] = str(refs[0])


def _trace_append(trace: list, step: str, out: object = "") -> None:
    trace.append({"step": step, "out": out})


# -------------------------------------------------------------------------------------
# 路径一：NPC 对话（/对话 列表→选择 NPC→对话树→信息交付一次一物置灰）
# -------------------------------------------------------------------------------------
def npc_flow(smoke: Smoke, ctx: MutableMapping) -> dict:
    trace: List[dict] = []
    states: List[str] = []
    s = DialogSession()

    # ---- 路由器层：/对话 需前缀（接缝裁决，parsers.DEFAULT_PREFIX_REQUIRED）----
    routed = route_message("/对话", {"registry": _build_registry(), "shortcuts": {},
                                     "command_mode": "global_shortcut"})
    smoke.check_eq(routed.kind, ROUTE_COMMAND, "NPC：/对话 路由到指令白名单")
    smoke.check_eq(routed.command, "对话", "NPC：/对话 command=对话")
    bare = parse_command("对话")
    smoke.check_eq(bare.mode, "ignored", "NPC：裸「对话」忽略（/对话 需前缀，接缝裁决）")

    # ---- T01 列表 ----
    r = s.step(("dialog", {"mode": "list"}), ctx)
    smoke.check_eq(r["transition"], "T01", "NPC：/对话 无参 → T01 列表")
    smoke.check_eq(r["to_state"], S_LIST, "NPC：进入 S1 LIST")
    smoke.check(any("这里的人：" in o for o in r["output"]), "NPC：列表头「这里的人：」")
    smoke.check(any("铁匠·老周" in o for o in r["output"]), "NPC：列表含 铁匠·老周")
    states.append(S_LIST)
    _trace_append(trace, "T01 列表", r["output"][0] if r["output"] else "")

    # ---- T03 选 NPC（序号 1 = 铁匠·老周）→ T05 菜单 ----
    r = s.step(("digit", 1), ctx)
    smoke.check(r["transition"] in ("T03", "T05"), "NPC：选人 T03→T05")
    smoke.check_eq(r["to_state"], S_MENU, "NPC：进入 S3 MENU")
    smoke.check(any("铁匠·老周：" in o for o in r["output"]), "NPC：菜单头带 NPC 名")
    smoke.check(any("1.买东西" in o for o in r["output"]), "NPC：菜单选项 1.买东西（shop）")
    states.append(S_MENU)
    _trace_append(trace, "T03 选人→菜单", r["output"][-1] if r["output"] else "")

    # ---- T07 选 shop 动作 → S4 EXEC（功能类不产叙述，handoff shop）----
    r = s.step(("digit", 1), ctx)
    smoke.check_eq(r["transition"], "T07", "NPC：选选项 T07 → EXEC")
    smoke.check_eq(r["to_state"], S_EXEC, "NPC：进入 S4 EXEC")
    smoke.check_eq((r.get("action") or {}).get("action"), "shop", "NPC：执行动作 = shop")
    smoke.check_eq(r.get("handoff"), {"type": "shop", "shop_refs": ["village_shop"]},
                   "NPC：shop 动作 handoff 商店移交")
    states.append(S_EXEC)
    _trace_append(trace, "T07 shop 动作", "handoff=" + str(r.get("handoff")))

    # ---- exec_done 回执：T10 回菜单 + 商店移交上报 ----
    r = s.step(("exec_done", {"shop_refs": ["village_shop"]}), ctx)
    smoke.check_eq(r["transition"], "T10", "NPC：shop exec_done → T10 回菜单")
    smoke.check_eq(r["to_state"], S_MENU, "NPC：T10 回到 S3 MENU")
    smoke.check(any("已打开商店：village_shop" in o for o in r["output"]), "NPC：已打开商店提示")
    smoke.check_eq(r.get("shop_refs"), ["village_shop"], "NPC：商店移交 shop_refs 上报")
    _apply_dialog_result(ctx, r)  # 【补白 5】世界层：current_shop_ref = village_shop
    smoke.check_eq(ctx["current_shop_ref"], "village_shop", "NPC：玩家当前商店 = village_shop（移交）")
    states.append(S_MENU)
    _trace_append(trace, "T10 商店移交", r["output"][0] if r["output"] else "")

    # ---- 结束：T09→T15 单点收尾（事件计数 [事件:NPC对话:ID]）----
    r = s.step(("exit", None), ctx)
    smoke.check(r["ended"] in ("T09", "T15"), "NPC：结束词走 T09→T15")
    smoke.check_eq(r["to_state"], S_IDLE, "NPC：会话收尾回 S0 IDLE")
    smoke.check_eq(r["events"], [dialog_event_key("blacksmith_zhou")], "NPC：收尾事件计数键")
    _apply_dialog_result(ctx, r)
    smoke.check_eq(ctx["longline_counters"].get(dialog_event_key("blacksmith_zhou")), 1,
                   "NPC：事件计数落 longline_counters（装配层）")
    states.append(S_IDLE)
    _trace_append(trace, "T15 收尾", "events=" + str(r["events"]))

    # ---- 信息交付一次一物置灰（长者·阿墨 reply 信息类；T02 序号直进）----
    r = s.step(("dialog", {"mode": "index", "value": 4}), ctx)  # 4 = 长者·阿墨
    smoke.check_eq(r["to_state"], S_MENU, "NPC：序号直进（T02→T05）到菜单")
    smoke.check(any("长者·阿墨：" in o for o in r["output"]), "NPC：长者·阿墨 菜单")
    smoke.check(any("1.夜里落石机关" in o for o in r["output"]), "NPC：信息类选项 1.夜里落石机关")
    states.append(S_MENU)
    _trace_append(trace, "长者·阿墨 菜单", r["output"][-1] if r["output"] else "")

    # 深度守卫（裁决③）：reply 无嵌套 → 内容树深度 1 ≤ max_dialog_depth 2 → 不拦
    opt = (ctx["npcs"][3].get("interactions") or [{}])[0]
    smoke.check_eq(authored_node_depth(opt), 1, "NPC：信息选项内容树深度 1")
    smoke.check(not is_depth_blocked(authored_node_depth(opt), 2), "NPC：深度 1 ≤ 2 不软拦（裁决③）")

    r = s.step(("digit", 1), ctx)
    smoke.check_eq(r["transition"], "T07", "NPC：选信息选项 T07 → EXEC")
    smoke.check_eq(r["to_state"], S_EXEC, "NPC：信息交付进入 S4 EXEC")
    smoke.check(any("夜里落石" in o for o in r["output"]), "NPC：叙述第一段（信息内容）")
    states.append(S_EXEC)
    _trace_append(trace, "信息叙述", r["output"][0] if r["output"] else "")

    # continue → 末段/无叙述 → T10 回菜单 + mark_heard（一次一物 L88 落玩家存档）
    r = s.step(("continue", None), ctx)
    smoke.check_eq(r["transition"], "T10", "NPC：信息交付后 T10 回菜单")
    smoke.check_eq(r.get("mark_heard"), ["reply:1"], "NPC：信息类交付 mark_heard=[reply:1]（一次一物）")
    smoke.check(any("（已听）" in o for o in r["output"]), "NPC：菜单选项置灰「（已听）」")
    _apply_dialog_result(ctx, r)
    smoke.check("reply:1" in ctx["heard"], "NPC：已听集合落玩家存档")
    states.append(S_MENU)
    _trace_append(trace, "已听置灰", "heard=" + str(sorted(ctx["heard"])))

    # 重选同一信息选项 → 「你已经听过了」（L87 / TC-11）
    r = s.step(("digit", 1), ctx)
    smoke.check_eq(r["kind"], "already_heard", "NPC：重选已听选项 → already_heard")
    smoke.check(any(DIALOG_ALREADY_HEARD_HINT in o for o in r["output"]), "NPC：提示「你已经听过了」")
    smoke.check_eq(r["to_state"], S_MENU, "NPC：已听留在菜单不重复交付")
    _trace_append(trace, "已听拒绝", r["output"][0] if r["output"] else "")

    r = s.step(("exit", None), ctx)
    smoke.check_eq(r["to_state"], S_IDLE, "NPC：长者会话收尾 S0")
    _apply_dialog_result(ctx, r)
    states.append(S_IDLE)

    result = {"states": states, "trace": trace, "assertions": smoke.passed}
    smoke.passed = 0  # 快照后清零，供下一路径独立计数
    return result


# -------------------------------------------------------------------------------------
# 路径二：商店（/商店 列表→浏览→购买→库存/限购扣减→余额不足提示）
# -------------------------------------------------------------------------------------
def shop_flow(smoke: Smoke, ctx: MutableMapping) -> dict:
    trace: List[dict] = []

    # ---- /商店 列表：一览（legal 两店）----
    out = cmd_shop(_parse("/商店 列表"), ctx)
    smoke.check("可用商店一览" in out, "商店：列表一览标题")
    smoke.check("铁匠铺" in out and "补给站" in out, "商店：一览含两店")
    smoke.check(out.count("\n") <= 5, "商店：列表单页无页脚（2 店 ≤5 条）")
    _trace_append(trace, "/商店 列表", out)

    # ---- /商店：浏览当前商店（NPC 移交 village_shop）----
    out = cmd_shop(_parse("/商店"), ctx)
    smoke.check("铁匠铺" in out, "商店：浏览头=铁匠铺（当前店）")
    smoke.check("药水" in out and "100(金币)" in out, "商店：商品行 药水 100(金币)")
    smoke.check("高级药水" in out and "220(金币)" in out, "商店：商品行 高级药水 220(金币)")
    smoke.check("全服剩 10" in out, "商店：库存标记 全服剩 10（stock=10）")
    _trace_append(trace, "/商店 浏览", out)

    # ---- /购买 药水*2：扣款 + 库存扣减 + 入包 ----
    out = cmd_buy(_parse("/购买 药水*2"), ctx)
    smoke.check_eq(out, "✅ 购买成功：药水×2（-200 金币），剩余 800 金币", "商店：购买药水×2 成功文案")
    smoke.check_eq(ctx["currencies"]["coins"], 800, "商店：购买扣款 1000→800")
    smoke.check_eq(ctx["inventory"].get("potion"), 2, "商店：药水入包 0→2")
    smoke.check_eq(ctx["world_stock"].get("village_shop", {}).get("potion"), 8,
                   "商店：全局库存扣减 10→8")
    _trace_append(trace, "/购买 药水*2", out)

    # ---- /购买 高级药水：再次扣款 + 库存 ----
    out = cmd_buy(_parse("/购买 高级药水"), ctx)
    smoke.check("✅ 购买成功：高级药水×1（-220 金币），剩余 580 金币" in out,
                "商店：购买高级药水成功文案")
    smoke.check_eq(ctx["currencies"]["coins"], 580, "商店：购买扣款 800→580")
    smoke.check_eq(ctx["inventory"].get("hi_potion"), 1, "商店：高级药水入包")
    smoke.check_eq(ctx["world_stock"].get("village_shop", {}).get("hi_potion"), 9,
                   "商店：高级药水库存 10→9")
    _trace_append(trace, "/购买 高级药水", out)

    # ---- /购买 秘药（补白 2 限购条目）：限购扣减 ----
    out = cmd_buy(_parse("/购买 秘药"), ctx)
    smoke.check("✅ 购买成功：秘药×1" in out, "商店：限购条目首次购买成功")
    smoke.check_eq(ctx["currencies"]["coins"], 530, "商店：限购购买扣款 580→530")
    smoke.check_eq(ctx["inventory"].get("magic_elixir"), 1, "商店：秘药入包")
    node = ctx["personal_buys"].get("village_shop", {}).get("magic_elixir", {})
    smoke.check_eq(node.get("count"), 1, "商店：个人限购计数 +1（裁决⑤）")
    _trace_append(trace, "/购买 秘药", out)

    # ---- 限购拒绝：再买同条目 → 整单拒绝（裁决⑤）----
    out = cmd_buy(_parse("/购买 秘药"), ctx)
    smoke.check_eq(out, "❌ 今日限购 1 个，已买 1 个", "商店：限购满整单拒绝")
    smoke.check_eq(ctx["currencies"]["coins"], 530, "商店：限购拒绝不扣款")
    smoke.check_eq(ctx["inventory"].get("magic_elixir"), 1, "商店：限购拒绝不入包")
    _trace_append(trace, "限购拒绝", out)

    # ---- 余额不足提示差额（独立低保 ctx，隔离共享主链路的币值）----
    poor = build_ctx(currencies={"coins": 50, "gem": 5})
    out = cmd_buy(_parse("/购买 高级药水"), poor)
    smoke.check_eq(out, "❌ 金币不足：还差 170", "商店：余额不足提示差额（校验链⑤）")
    smoke.check_eq(poor["currencies"]["coins"], 50, "商店：余额不足不扣款")
    smoke.check_eq(poor["inventory"], {}, "商店：余额不足不入包")
    _trace_append(trace, "余额不足", out)

    result = {"trace": trace, "assertions": smoke.passed}
    smoke.passed = 0
    return result


# -------------------------------------------------------------------------------------
# 路径三：任务（/任务 接取→条件推进→交付→reward 入账）
# -------------------------------------------------------------------------------------
def quest_flow(smoke: Smoke, ctx: MutableMapping) -> dict:
    trace: List[dict] = []

    # ---- /任务：任务板（NPC 支线：药水补给）----
    out = cmd_quest(_parse("/任务"), ctx)
    smoke.check("━━ NPC 支线 ━━" in out, "任务：任务板含 NPC 支线段头")
    smoke.check("1. 药水补给" in out, "任务：任务板条目 1.药水补给")
    smoke.check("/任务 接取 <序号>" in out, "任务：操作指引行")
    _trace_append(trace, "/任务 板", out)

    # ---- /任务 接取 1 ----
    out = cmd_quest(_parse("/任务 接取 1"), ctx)
    smoke.check("✅ 已接取：药水补给" in out, "任务：接取成功文案")
    smoke.check("q_potion_supply" in ctx["quest_active"], "任务：quest_active 登记")
    _trace_append(trace, "/任务 接取 1", out)

    # ---- 条件推进（shop 已买 2 瓶药水 → item_count potion ≥ 2 满足）----
    prog = quest_engine.quest_progress("q_potion_supply", ctx)
    smoke.check(bool(prog.get("met")), "任务：条件满足（药水×2 ≥ 2）")
    c0 = prog["conditions"][0]
    smoke.check_eq(c0.get("current"), 2, "任务：三原语条件 current=2")
    smoke.check_eq(c0.get("target"), 2, "任务：三原语条件 target=2")
    _trace_append(trace, "条件推进", f"current={c0.get('current')}/target={c0.get('target')}")

    # ---- /任务 信息 1：进度渲染 ----
    out = cmd_quest(_parse("/任务 信息 1"), ctx)
    smoke.check("✅ 任务进度：药水补给" in out, "任务：信息头部")
    smoke.check("背包数量 ≥ 2（potion），当前 2" in out, "任务：三原语进度逐条显示")
    smoke.check("可交付" in out, "任务：条件已满足可交付提示")
    _trace_append(trace, "/任务 信息 1", out)

    # ---- /任务 交付 1：reward 入账 ----
    before = int(ctx["inventory"].get("potion", 0))
    out = cmd_quest(_parse("/任务 交付 1"), ctx)
    smoke.check("✅ 交付完成：药水补给" in out, "任务：交付完成文案")
    smoke.check("potion×2" in out, "任务：交付奖励展示（统一 reward 入账提示）")
    smoke.check_eq(ctx["inventory"].get("potion"), before + 2, "任务：reward 药水×2 实际入账")
    smoke.check("q_potion_supply" in ctx["quest_completed"], "任务：quest_completed 登记（完成即移出）")
    smoke.check("q_potion_supply" not in ctx["quest_active"], "任务：完成即移出 quest_active")
    smoke.check_eq(ctx["quest_daily"].get("completed"), 1, "任务：quest_daily 完成数 +1")
    _trace_append(trace, "/任务 交付 1", out)

    # ---- 交付后不可再接（非 repeatable）----
    out = cmd_quest(_parse("/任务 接取 1"), ctx)
    smoke.check("❌ 任务已完成" in out, "任务：已完成任务拒绝再接")

    result = {"trace": trace, "assertions": smoke.passed}
    smoke.passed = 0
    return result


# -------------------------------------------------------------------------------------
# 路径四：签到（/签到 结算→连签→幂等→补签只计不补发→三键）
# -------------------------------------------------------------------------------------
def checkin_flow(smoke: Smoke, ctx: MutableMapping) -> dict:
    trace: List[dict] = []
    d = DAY

    # dayroll 日界复核（A3）：固定 now → today = 2026-08-01
    t = today_of(None, ctx["now"], ctx["settings"])
    smoke.check_eq(t["today"], _TODAY, "签到：dayroll today=2026-08-01（重置时刻 05:00 之后）")

    # ---- 第 1 天：/签到 多表一次结算（loop + monthly；activity 未开门）----
    out = cmd_checkin(_parse("/签到"), ctx)
    smoke.check("✅ 今日签到完成" in out, "签到：首签结算文案")
    smoke.check("今日奖励：potion×1" in out, "签到：loop 今日奖励（day1 药水×1）")
    smoke.check("连签天数：1 天" in out, "签到：loop 连签 1 天")
    smoke.check("月度签到（月度签到）" in out, "签到：monthly 段头（render_summary 排版带空格）")
    smoke.check("活动" not in out, "签到：activity 未开门（2099 窗口）不结算")
    smoke.check_eq(ctx["inventory"].get("potion"), 4 + 2, "签到：首签入账 2 瓶药水（loop+monthly）")
    st = ctx["checkin_state"]["checkin_loop"]
    smoke.check_eq(st.get("streak"), 1, "签到：loop streak=1")
    smoke.check_eq(st.get("last_date"), "2026-08-01", "签到：last_date=2026-08-01")
    _trace_append(trace, "第1天 /签到", out)

    # ---- 同日幂等（D-02 不重复发奖）----
    before_potion = int(ctx["inventory"].get("potion", 0))
    out = cmd_checkin(_parse("/签到"), ctx)
    smoke.check("今天已签到（重复指令，未重复发放）" in out, "签到：同日重复 → 幂等文案")
    smoke.check_eq(int(ctx["inventory"].get("potion", 0)), before_potion, "签到：幂等不重复发奖")
    _trace_append(trace, "同日幂等", out)

    # ---- 第 2 天：跨天连签 +1 ----
    ctx["now"] = ctx["now"] + d
    out = cmd_checkin(_parse("/签到"), ctx)
    smoke.check("✅ 今日签到完成" in out, "签到：第 2 天结算")
    smoke.check_eq(ctx["currencies"]["coins"], 530 + 50, "签到：loop day2 金币 +50")
    smoke.check_eq(ctx["checkin_state"]["checkin_loop"].get("streak"), 2, "签到：loop streak=2（连签）")
    _trace_append(trace, "第2天 /签到", out)

    # ---- 第 3 天：跨天连签 +1（day3 药水×2 + exp20）----
    ctx["now"] = ctx["now"] + d
    before_potion = int(ctx["inventory"].get("potion", 0))
    before_exp = int(ctx["exp"])
    out = cmd_checkin(_parse("/签到"), ctx)
    smoke.check("✅ 今日签到完成" in out, "签到：第 3 天结算")
    smoke.check_eq(ctx["checkin_state"]["checkin_loop"].get("streak"), 3, "签到：loop streak=3")
    smoke.check_eq(int(ctx["inventory"].get("potion", 0)), before_potion + 3,
                   "签到：loop day3 药水×2 + monthly 兜底药水×1 入账")
    smoke.check_eq(int(ctx["exp"]), before_exp + 20, "签到：loop day3 exp +20")
    _trace_append(trace, "第3天 /签到", out)

    # ---- 三键投影（裁决⑧）：结算后 ctx["checkin"] 刷新 ----
    checkin_condition_ctx(ctx)
    proj = ctx.get("checkin") or {}
    smoke.check_eq(proj.get("loop", {}).get("streak"), 3, "签到：三键 loop.连续天数=3（裁决⑧）")
    smoke.check_eq(proj.get("loop", {}).get("month_days"), 3, "签到：三键 loop.本月天数=3")
    smoke.check_eq(proj.get("loop", {}).get("today_signed"), 1, "签到：三键 loop.今日已签=1")
    smoke.check_eq(checkin_value(ctx, "loop", "streak"), 3, "签到：checkin_value loop streak=3")
    _trace_append(trace, "三键投影", str(proj))

    # ---- 第 4 天：/签到 补签 loop（裁决⑦ 只计不补发）----
    ctx["now"] = ctx["now"] + d
    before_potion = int(ctx["inventory"].get("potion", 0))
    before_coins = int(ctx["currencies"]["coins"])
    out = cmd_checkin(_parse("/签到 补签 loop"), ctx)
    smoke.check("✅ 补签成功" in out, "签到：补签成功文案")
    smoke.check("只计不补发" in out, "签到：补签提示「只计不补发」（裁决⑦）")
    smoke.check_eq(int(ctx["inventory"].get("potion", 0)), before_potion,
                   "签到：补签不补发 daily 奖励（药水数不变）")
    smoke.check_eq(int(ctx["currencies"]["coins"]), before_coins - 50, "签到：补签货币通道扣 50 金币")
    st = ctx["checkin_state"]["checkin_loop"]
    smoke.check_eq(st.get("streak"), 4, "签到：补签只恢复 streak 连续性 3→4")
    smoke.check("2026-08-04" in st.get("signed_days", []), "签到：补签计 signed_days 含今日")
    smoke.check_eq(st.get("makeup_used"), 1, "签到：补签用量 +1")
    _trace_append(trace, "第4天 /签到 补签", out)

    # ---- 补签后 /签到 同日：loop 已签幂等；monthly 正常结算 ----
    before_potion = int(ctx["inventory"].get("potion", 0))
    out = cmd_checkin(_parse("/签到"), ctx)
    smoke.check("✅ 今日签到完成" in out, "签到：补签后同日 /签到 结算（monthly 仍结算）")
    smoke.check_eq(int(ctx["inventory"].get("potion", 0)), before_potion + 1,
                   "签到：同日 loop 不重复发奖（已补签），monthly 仍发 day4 兜底")
    smoke.check_eq(ctx["checkin_state"]["checkin_monthly"].get("streak"), 4,
                   "签到：monthly streak=4")
    _trace_append(trace, "补签后 /签到", out)

    result = {"trace": trace, "assertions": smoke.passed}
    smoke.passed = 0
    return result


# -------------------------------------------------------------------------------------
# 路径五：快捷指令（战斗中裸数字归快捷表 · 裁决①；GM 禁绑 C02；上限 E03）
# -------------------------------------------------------------------------------------
def shortcut_flow(smoke: Smoke, ctx: MutableMapping) -> dict:
    trace: List[dict] = []
    shortcuts = {"攻击": "/攻击 2", "2": "/攻击 2", "逃跑": "/逃跑"}

    # ---- 解析层（parsers.parse_command）：快捷展开 ----
    p = parse_command("攻击", shortcuts=shortcuts)
    smoke.check_eq(p.mode, MODE_SHORTCUT, "快捷：裸词命中快捷表 → mode=shortcut")
    smoke.check_eq(p.command, "攻击", "快捷：快捷展开 command=攻击")
    smoke.check_eq(p.args, ["2"], "快捷：快捷展开 args=[2]")

    # ---- 裁决①：战斗中裸数字 = 快捷表（不送会话）----
    p = parse_command("2", in_battle=True, session_active=False, shortcuts=shortcuts)
    smoke.check_eq(p.mode, MODE_SHORTCUT, "快捷：战斗中裸数字归快捷表（裁决①）")
    smoke.check_eq(p.command, "攻击", "快捷：战斗裸数字展开为 /攻击 2")

    # ---- 会话激活：纯数字送状态机（会话优先于快捷 R3）----
    p = parse_command("2", session_active=True, in_battle=False, shortcuts=shortcuts)
    smoke.check_eq(p.mode, MODE_SESSION_DIGIT, "快捷：对话激活中纯数字送状态机（R3）")
    smoke.check_eq(p.session_candidate, True, "快捷：会话子词候选标记")

    # ---- 路由层（router.route_message / route_and_expand）：战斗裸数字 → ROUTE_SHORTCUT ----
    rctx = {
        "registry": _build_registry(),
        "shortcuts": shortcuts,
        "command_mode": "global_shortcut",
        "dialog_active": False,
        "battle_active": True,
    }
    r = route_message("2", rctx)
    smoke.check_eq(r.kind, ROUTE_SHORTCUT, "快捷：路由层战斗中裸数字 → 快捷表（裁决①）")
    r = route_message("2", dict(rctx, dialog_active=True))
    smoke.check_eq(r.kind, ROUTE_SESSION, "快捷：路由层对话激活裸数字 → 会话状态机")
    r2 = route_and_expand("攻击", rctx)
    smoke.check_eq(r2.kind, ROUTE_COMMAND, "快捷：快捷展开后落指令白名单（expand_count=1）")
    smoke.check_eq(r2.mode, MODE_SHORTCUT, "快捷：展开结果保留 mode=shortcut（P03）")
    smoke.check_eq(r2.expand_count, 1, "快捷：展开深度 =1（S7 裁决）")
    smoke.check_eq(r2.command, "攻击", "快捷：展开目标 command=攻击")
    smoke.check_eq(r2.args_text, "2", "快捷：展开目标 args_text=2")
    _trace_append(trace, "战斗裸数字归快捷表", f"route2={r2.kind} mode={r2.mode} command={r2.command}")

    # ---- GM 禁绑（C02 防权限绕过）+ 上限（E03）----
    v = check_shortcut_binding("1", "/重载 商店", registry=_build_registry())
    smoke.check_eq(v.get("code"), "gm_forbidden", "快捷：GM 指令禁绑（C02）")
    v = check_shortcut_binding("a", "/攻击 2", registry=_build_registry())
    smoke.check_eq(v.get("code"), "ok", "快捷：普通指令可绑定")
    v = check_shortcut_limit(20)
    smoke.check_eq(v.get("code"), "shortcut_full", "快捷：快捷表满 20 条拒绝（E03）")
    v = check_shortcut_limit(5)
    smoke.check_eq(v.get("code"), "ok", "快捷：未满上限放行")
    _trace_append(trace, "GM 禁绑/上限", f"gm={v.get('code')}")

    result = {"trace": trace, "assertions": smoke.passed}
    smoke.passed = 0
    return result


def _build_registry() -> Router:
    """快捷/路由流程用的注册表：M4 指令 + 攻击 + 对话 + GM 重载（白名单匹配用，不挂 handler）。"""
    router = Router()
    for name in ("商店", "购买", "出售", "任务", "签到", "攻击", "对话", "查看", "背包"):
        router.register(CommandSpec(name))
    router.register(CommandSpec("重载", is_gm=True))
    return router


# -------------------------------------------------------------------------------------
# 路径六：翻页夹取（裁决②：超页夹取最后一页 +「已到最后一页」；0/负数/非数字 → TPL-12）
# -------------------------------------------------------------------------------------
def pageclamp_flow(smoke: Smoke, ctx: MutableMapping) -> dict:
    trace: List[dict] = []

    # ---- 纯函数 list_render.resolve_page（裁决② 全口径）----
    res = resolve_page(9, 3, 5)
    smoke.check(res.clamped and res.page == 1, "夹取：9 > 总页数1 → 夹取最后一页（clamped）")
    res = resolve_page(0, 3, 5)
    smoke.check(res.invalid, "夹取：页码 0 → invalid（TPL-12）")
    res = resolve_page(-1, 3, 5)
    smoke.check(res.invalid, "夹取：负数 → invalid（TPL-12）")
    res = resolve_page("abc", 3, 5)
    smoke.check(res.invalid, "夹取：非数字 → invalid（TPL-12）")
    res = resolve_page(2, 8, 5)
    smoke.check_eq((res.page, res.total_pages), (2, 2), "夹取：正常第 2 页")

    # ---- /商店 9：超页夹取（village_shop 3 商品 → 1 页）----
    out = cmd_shop(_parse("/商店 9"), ctx)
    smoke.check("（已到最后一页）" in out, "夹取：/商店 9 → 已到最后一页")
    smoke.check("铁匠铺" in out, "夹取：/商店 9 仍显示当前店")
    _trace_append(trace, "/商店 9 夹取", out)

    # ---- /商店 列表 9：一览夹取 ----
    out = cmd_shop(_parse("/商店 列表 9"), ctx)
    smoke.check("（已到最后一页）" in out, "夹取：/商店 列表 9 → 已到最后一页")
    _trace_append(trace, "/商店 列表 9 夹取", out)

    # ---- /商店 0 / -1 / abc → TPL-12 ----
    out = cmd_shop(_parse("/商店 0"), ctx)
    smoke.check("❌ 指令不正确" in out, "夹取：/商店 0 → TPL-12")
    out = cmd_shop(_parse("/商店 -1"), ctx)
    smoke.check("❌ 指令不正确" in out, "夹取：/商店 -1 → TPL-12")
    out = cmd_shop(_parse("/商店 abc"), ctx)
    smoke.check("❌ 指令不正确" in out, "夹取：/商店 abc → TPL-12")
    _trace_append(trace, "/商店 非法页码", "TPL-12×3")

    # ---- /商店 2：超页命中商店序号 → 切换补给站（TC-02，页码优先）----
    fresh = build_ctx()  # 独立 ctx：current_shop_ref=None → 全表序号解析
    out = cmd_shop(_parse("/商店 2"), fresh)
    smoke.check("补给站" in out, "夹取：/商店 2 超页切店 → 补给站（TC-02）")
    smoke.check("铁匠铺" not in out, "夹取：/商店 2 已切离铁匠铺")
    _trace_append(trace, "/商店 2 切店", out)

    # ---- /任务 9：任务板夹取（单任务 1 页）----
    out = cmd_quest(_parse("/任务 9"), ctx)
    smoke.check("（已到最后一页）" in out, "夹取：/任务 9 → 已到最后一页")
    out = cmd_quest(_parse("/任务 0"), ctx)
    smoke.check("❌ 指令不正确" in out, "夹取：/任务 0 → TPL-12")
    out = cmd_quest(_parse("/任务 -2"), ctx)
    smoke.check("❌ 指令不正确" in out, "夹取：/任务 -2 → TPL-12")
    _trace_append(trace, "/任务 页码", "clamp + TPL-12×2")

    # ---- /签到 9：结算夹取（2 表流水 → 1 页）----
    fresh2 = build_ctx()  # 独立 ctx：签到在隔离场景执行（不污染共享链路的签到状态）
    out = cmd_checkin(_parse("/签到 9"), fresh2)
    smoke.check("（已到最后一页）" in out, "夹取：/签到 9 → 已到最后一页")
    out = cmd_checkin(_parse("/签到 0"), fresh2)
    smoke.check("❌ 指令不正确" in out, "夹取：/签到 0 → TPL-12")
    # ---- /签到 状态 9：状态视图夹取（6 行 → 2 页）----
    out = cmd_checkin(_parse("/签到 状态 9"), fresh2)
    smoke.check("（已到最后一页）" in out, "夹取：/签到 状态 9 → 已到最后一页")
    smoke.check("第 2/2 页" in out, "夹取：/签到 状态 夹到第 2/2 页")
    _trace_append(trace, "/签到 页码", "clamp + TPL-12")

    result = {"trace": trace, "assertions": smoke.passed}
    smoke.passed = 0
    return result


# -------------------------------------------------------------------------------------
# 冒烟主流程（确定性重放：同 now 同种子两次运行摘要逐字一致）
# -------------------------------------------------------------------------------------
def run_paths(smoke: Smoke, ctx: dict) -> dict:
    return {
        "npc": npc_flow(smoke, ctx),
        "shop": shop_flow(smoke, ctx),
        "quest": quest_flow(smoke, ctx),
        "checkin": checkin_flow(smoke, ctx),
        "shortcut": shortcut_flow(smoke, ctx),
        "pageclamp": pageclamp_flow(smoke, ctx),
    }


def run_smoke(now: Optional[int] = None) -> dict:
    """执行完整冒烟：两次运行对比确定性（固定 now/种子）。"""
    now = FIXED_NOW if now is None else now
    smoke = Smoke()
    r1 = run_paths(smoke, build_ctx(now=now))

    # 确定性重放（验收标准：固定种子可重放——同参二次运行摘要逐字一致）
    smoke2 = Smoke()
    r2 = run_paths(smoke2, build_ctx(now=now))
    replay = (r1 == r2)
    smoke.check(replay, "确定性重放：两次运行摘要逐字一致（固定 now/种子）")

    return {
        "ok": smoke.failed == 0,
        "passed": smoke.passed,
        "failed": smoke.failed,
        "failures": smoke.failures,
        "replay_identical": replay,
        "runs": r1,
    }


# -------------------------------------------------------------------------------------
# 主入口（独立可运行）
# -------------------------------------------------------------------------------------
def _print_run(run: dict, title: str) -> None:
    print(f"\n◆ {title}")
    states = run.get("states")
    if states:
        print(f"  状态迁移：{' → '.join(states)}")
    for t in run["trace"]:
        out = str(t.get("out", ""))
        snippet = out.replace("\n", " ⏎ ") if out else ""
        if len(snippet) > 88:
            snippet = snippet[:88] + "…"
        print(f"  [{t['step']}] {snippet}")
    print(f"  路径断言：{run['assertions']}")


def main() -> int:
    print("=" * 68)
    print("M4 端到端集成冒烟（M4 批次7·路H1）：NPC→商店→任务→签到→快捷→翻页夹取 全链路")
    print(f"固定 now = {datetime.fromtimestamp(FIXED_NOW, _TZ8).strftime('%Y-%m-%d %H:%M:%S UTC+8')}"
          f" | rng 种子 = {SEED}")
    result = run_smoke()
    for key, title in (
        ("npc", "① NPC 对话（列表→选人→对话树→一次一物置灰）"),
        ("shop", "② 商店（列表→浏览→购买→库存/限购扣减→余额不足）"),
        ("quest", "③ 任务（接取→条件推进→交付→reward 入账）"),
        ("checkin", "④ 签到（结算→连签→幂等→补签只计不补发→三键）"),
        ("shortcut", "⑤ 快捷指令（战斗裸数字归快捷表）"),
        ("pageclamp", "⑥ 翻页夹取（裁决②）"),
    ):
        _print_run(result["runs"][key], title)
    print("-" * 68)
    for f in result["failures"]:
        print("  ✗", f)
    per = {k: int(v["assertions"]) for k, v in result["runs"].items()}
    a_total = sum(per.values()) + int(result["passed"])
    print(f"断言：{' + '.join(f'{k} {per[k]}' for k in per)} + 运行级 {result['passed']} = {a_total} 通过"
          f" / {result['failed']} 失败"
          + (" ｜ 确定性重放：一致 ✓" if result["replay_identical"] else " ｜ 确定性重放：不一致 ✗"))
    if result["ok"]:
        print(GREEN_LINE)
        return 0
    print("M4 端到端冒烟失败")
    return 1


if __name__ == "__main__":
    sys.exit(main())

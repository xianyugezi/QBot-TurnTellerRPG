"""签到引擎（M4 批次5·路F2 · qbot_rpg/core/checkin.py）——多表并存一次结算 + 连签独立计数 + 补签只计不补发 + [签到:*] 三键取值。

依据：
  - m4_shared_contract.md §3.4（E1-E4：多表 loop/monthly/activity 并存一次结算；连签独立计数（streak）；
    补签（默认关/两通道/月上限）；用户裁决⑦ 补签只计不补发、里程碑不重复；用户裁决⑧
    [签到:<表名>.<字段>] 三键：连续天数=指定表 streak / 本月天数=指定表当月 signed_days /
    今日已签=指定表今日已签，缺省表名=主表 loop）
  - docs/细化/细化_2b5_签到引擎契约.md（结算管线 ①~⑥ L62-73 / 连签独立计数 §三 / 补签两通道 §四 /
    幂等 §五 / 日界懒计算 §5.3 / D-01 day 编号 / D-02 幂等仍附进度 / D-03 补签幂等 / D-04 bonus 乘算 /
    D-05 发奖失败兜底 / D-06 monthly_total 跨月清零 / TC-01~TC-33）
  - docs/审查参考/签到系统设计定稿.md（结算管线 L62-73 / [签到:*] 三键 L86/L197/L223 / 统一周期键
    L106 / 多表并存 L75-79 / 奖励四通道 L51-58 / 补签默认关 L58 / 里程碑 L56-57）
  - 2026-08-27 M4 设计审查裁决⑦⑧（细化_2b5 尾部裁决注记 L444-448：⑦ 补签只恢复 signed_days 与
    streak 连续性、不补发所补日期 daily 奖励；里程碑奖励不重复；⑧ [签到:<表名>.<字段>] 三键加表名限定）

【工程补白 · 显式标注】（契约/定稿未显式定义处，按「只建议不限制」取点定型，命名可改）：
  1) 引擎零 IO、零 NoneBot import、纯函数（ctx dict 进出，就地改写可变子结构）；SQLite 事务由调用方
     存储层负责，本模块以「快照-回滚」保证单表结算无中间态（跨表互相独立，一表失败不影响其他表，D-05）。
  2) 状态落点（ctx 就地改写，持久化由调用方完成）：
       ctx["checkin_state"]    玩家签到存档 {表ID: {last_date, streak, month_total, signed_days[],
                                month_key, month_milestones[], makeup_month, makeup_used, longline}}
                                （对齐 细化 §3.1「checkin_state[<表ID>]」，按表 ID 键控 L252/L110）
       ctx["checkin_tables"]   checkin.json 表定义注册表 {id: 表}，或 ctx["resolve_checkin_table"]
                                解析器 + ctx["checkin_table_ids"]（对齐 quest.resolve_quest 双通道）
       ctx["checkin"]          condition_engine 消费投影 {表类型: {streak, month_days, today_signed}}
                                （由 checkin_condition_ctx 构建/刷新；_resolve_checkin L565-582 消费）
       ctx["currencies"]/["exp"]/["reputation_state"]/["inventory"]  reward 发放 / 扣费桶
                                （dispatch_reward 就地入账；补签卡/货币扣费也就地）
       ctx["longline_counters"] 框架长线计数（checkin_total 只增不减镜像，对齐定稿 L102）
       ctx["tx_id"]+ctx["ledger"]  幂等（A1 模式：整次 /签到 以基 tx 记 ledger 防重放；内部
                                dispatch_reward 以 {base}:{表ID}:{通道} 子 tx 记账，互不冲突，
                                部分失败重放亦不双发）
  3) day 编号（对齐 D-01）：loop 表 = 本期第 N 天（N=连签段内序号 streak）mod cycle_days（余 0 →
     cycle_days）——断签重来即新一轮、day 同步轮转（TC-13 口径）；monthly 表 = 自然月当日 1..当月天数；
     activity 表 = 与 period.start 日差 + 1（start 缺省/解析失败 → 1，防御）。cycle_days：loop 默认 7
     可配 / monthly 自动当月天数（28/29/30/31）/ activity 作进度分母（缺省 = start→end 日数）。
  4) 里程碑「每档每周期至多一次」口径（细化 §3.2 / 裁决⑦「里程碑奖励不重复」）：
     · streak 里程碑以 streak 恰好命中阈值 days 发放——streak 在单次连签段内单调递增，恰好命中每段
       至多一次（断签重来=新段重新计数，即「每周期」）；reset_on_break=false 则 streak 只增不减，
       每档至多一次（断签不重来）。
     · monthly_total 里程碑以当月累计天数达到阈值 days 发放，且每档每月至多一次
       （state.month_milestones 记录当月已发阈值，跨月清零，对齐 D-06）。
     · 补签（checkin_makeup）绝不触发任何里程碑发放（裁决⑦ 只计不补发）。
  5) 补签作用于当前归属日 today（/签到 补签 无日期参数，契约未定义历史日期补签通道）：恢复
     signed_days（追加 today）+ streak 连续性（streak+1、last_date=today，跨间隙不归 1 = 挽回断签
     口径，D-03）+ month_total +1；**不补发所补日期 daily 奖励、不触发任何里程碑**（裁决⑦）。同日已签
     （含已补）→ 幂等返回不重复扣费（D-03 / TC-24）。补签卡物品 ID 缺省常量「补签卡」，可经
     makeup.card_item / ctx["makeup_card_item"] 覆盖（schema 无显式卡 ID 字段，工程补白）。
  6) bonus（D-04）：倍率作用于本次实际发放条目 items.count/coins/gem/exp，int 向下取整；物品数量下限
     1（防倍率削 0），标量下限 0。bonus 形态：{mult:N}（内容层/校验器正典键，P1-3 对齐）/
     {multiplier:N} / {rate:N} / {倍率:N} / 裸数值 N（multiplier/rate/倍率 为兼容键保留）。
  7) 发奖失败兜底（D-05 / TC-27）：reward 单条失败（物品不存在等）黄字跳过、不吞整次签到；单表 batch
     级失败（ctx 非法 / reward 形态非法）→ 该表快照回滚（含发奖桶与 state），跨表继续。daily 漏配天数
     → 按第 1 天奖励兜底 + notes「第 X 天未配置，已按第 1 天奖励补全」（TC-10 / 定稿 L27）。
  8) 生效表启停（细化 §2.2 / 定稿 L78）：loop/monthly 恒生效；activity 由懒计算 is_window_open 判定，
     未开始/已过期 → 自动停用（不报错、不结算）。同类型多表时三键投影取首表（框架设计一类型一表）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；now 注入确定性；工程补白显式标注；文件头标注依据；
不 git commit。
"""

from __future__ import annotations

import calendar
import copy
from datetime import date
from typing import Any, List, Mapping, MutableMapping, MutableSet, Optional

from qbot_rpg.core.dayroll import WINDOW_OPEN, is_window_open, today_of
from qbot_rpg.core.reward import dispatch_reward

__all__ = [
    "DEFAULT_CYCLE_DAYS",
    "MAKEUP_CARD_ITEM",
    "CHECKIN_TYPES",
    "CHECKIN_FIELDS",
    "resolve_checkin_table",
    "table_active",
    "cycle_days_of",
    "day_index_of",
    "checkin_value",
    "checkin_condition_ctx",
    "checkin_state",
    "checkin_do",
    "checkin_makeup",
]

# -------------------------------------------------------------------------------------
# 常量与键空间
# -------------------------------------------------------------------------------------
DEFAULT_CYCLE_DAYS: int = 7            # loop 表缺省 cycle_days（定稿 L131 / TC-03）
MAKEUP_CARD_ITEM: str = "补签卡"        # 补签卡缺省物品 ID（工程补白 5）
CHECKIN_TYPES: tuple = ("loop", "monthly", "activity")

# 三键中文字段 → 内部字段（对齐 condition_engine.CHECKIN_FIELDS，裁决⑧）
CHECKIN_FIELDS: dict = {
    "连续天数": "streak",
    "本月天数": "month_days",
    "今日已签": "today_signed",
    "streak": "streak",
    "month_days": "month_days",
    "today_signed": "today_signed",
}

_TYPE_CN: dict = {"loop": "常驻循环", "monthly": "月度签到", "activity": "活动"}

# 快照-回滚覆盖的可变 ctx 子结构（工程补白 1/7）
_SNAP_KEYS: tuple = (
    "currencies", "exp", "reputation_state", "checkin_state",
    "longline_counters", "inventory", "checkin",
)


# -------------------------------------------------------------------------------------
# 基础工具（纯函数，对齐 quest.py / shop.py 口径）
# -------------------------------------------------------------------------------------
def _as_int(value: object, default: int = 0) -> int:
    """int 归一（bool 除外）；非 int/bool/可转数字串 → default。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else default
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _settings(ctx: Mapping[str, Any]) -> Mapping:
    settings = ctx.get("settings")
    return settings if isinstance(settings, Mapping) else {}


def _now(ctx: Mapping[str, Any]) -> Optional[int]:
    """UTC+8 秒级时间戳：ctx[\"now\"] 注入优先（确定性可测）；缺省 None → dayroll 取当前。"""
    now = ctx.get("now")
    return int(now) if now is not None else None


def _cfg(ctx: Mapping[str, Any]) -> Mapping:
    """dayroll 配置：统一配置键 refresh_time（默认 05:00，与商店/任务同刻对齐，定稿 L106）。"""
    return _settings(ctx)


def _parse_date(s: object) -> Optional[date]:
    """\"YYYY-MM-DD\" → date；None/非法串 → None（防御性回退，不崩溃）。"""
    if isinstance(s, str):
        try:
            return date.fromisoformat(s.strip()[:10])
        except ValueError:
            return None
    return None


def _days_between(a: object, b: object) -> int:
    """a 日期键 → b 日期键 的日界数；None/非法/未来 → 0（防御）。"""
    da, db = _parse_date(a), _parse_date(b)
    if da is None or db is None or db <= da:
        return 0
    return (db - da).days


def _month_key(today: object) -> str:
    """\"YYYY-MM-DD\" → \"YYYY-MM\"；非法 → \"\"。"""
    if isinstance(today, str) and len(today) >= 7:
        return today[:7]
    return ""


def _month_days_count(signed_days: object, today: object) -> int:
    """当月已签天数 = signed_days 中属于本月（YYYY-MM）的日期数（裁决⑧ 本月天数口径）。"""
    if not isinstance(signed_days, list):
        return 0
    mkey = _month_key(today)
    return sum(1 for d in signed_days if isinstance(d, str) and d.startswith(mkey))


def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(hook(item_id))
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        cur = int(inv.get(item_id, 0))
        if cur < count:
            return False
        inv[item_id] = cur - count
        return True
    return False


def _currency_shortage(ctx: Mapping[str, Any], cost: Mapping) -> dict:
    """补签货币通道余额校验：返回 {货币键: 差额}；不足/缺桶才非空。"""
    shortage: dict = {}
    currencies = ctx.get("currencies")
    if not isinstance(currencies, Mapping):
        return {str(k): v for k, v in cost.items() if _as_int(v) > 0}
    for k, v in cost.items():
        need = _as_int(v)
        if need <= 0:
            continue
        have = _as_int(currencies.get(k))
        if have < need:
            shortage[str(k)] = need - have
    return shortage


def _deduct_currency(ctx: MutableMapping[str, Any], cost: Mapping) -> bool:
    currencies = ctx.get("currencies")
    if not isinstance(currencies, MutableMapping):
        return False
    for k, v in cost.items():
        need = _as_int(v)
        if need <= 0:
            continue
        currencies[k] = _as_int(currencies.get(k)) - need
    return True


# -------------------------------------------------------------------------------------
# 签到表解析 / 生效判定 / 周期口径（D-01）
# -------------------------------------------------------------------------------------
def resolve_checkin_table(ctx: Mapping[str, Any], table_id: object) -> Optional[Mapping]:
    """签到表定义解析：ctx[\"checkin_tables\"] dict（id→表）或 ctx[\"resolve_checkin_table\"] 解析器；
    查无 → None。"""
    if not isinstance(table_id, str):
        return None
    tables = ctx.get("checkin_tables")
    if isinstance(tables, Mapping):
        hit = tables.get(table_id)
        if isinstance(hit, Mapping):
            return hit
    resolver = ctx.get("resolve_checkin_table")
    if callable(resolver):
        try:
            hit = resolver(table_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            return hit
    return None


def _all_checkin_tables(ctx: Mapping[str, Any]) -> List[tuple]:
    """全表 (id, 定义) 稳定序（dict 顺序或 resolve 通道缺省 id 列表）。"""
    tables = ctx.get("checkin_tables")
    if isinstance(tables, Mapping):
        out = []
        for tid, t in tables.items():
            if not isinstance(t, Mapping):
                continue
            out.append((str(tid), t))
        return out
    resolver = ctx.get("resolve_checkin_table")
    if callable(resolver):
        ids = ctx.get("checkin_table_ids")
        if isinstance(ids, (list, tuple)):
            out = []
            for tid in ids:
                if not isinstance(tid, str):
                    continue
                try:
                    t = resolver(tid)
                except Exception:
                    t = None
                if isinstance(t, Mapping):
                    out.append((tid, t))
            return out
    return []


def _table_id_for_type(ctx: Mapping[str, Any], typ: str) -> Optional[str]:
    """表类型（loop/monthly/activity）→ 表 ID（同类型多表取首表，工程补白 8）。"""
    for tid, table in _all_checkin_tables(ctx):
        if str(table.get("type", "loop")) == typ:
            return tid
    return None


def _table_id_for(ctx: Mapping[str, Any], table: str) -> Optional[str]:
    """表限定符 → 表 ID（裁决⑧ 双口径：生效 type 名 或 表 id 皆可解析——
    审查_M4实现_批次5_jspace.md P1-2 消费侧统一支持表 id，兑现内容层校验器「双口径」承诺）。"""
    tid = _table_id_for_type(ctx, table)
    if tid is not None:
        return tid
    hit = resolve_checkin_table(ctx, table)
    return table if isinstance(hit, Mapping) else None


def _primary_table_id(ctx: Mapping[str, Any]) -> Optional[str]:
    """主表 = 首个 loop 表；无 loop → 首表（裁决⑧ 缺省表名 = 主表 loop）。"""
    tables = _all_checkin_tables(ctx)
    for tid, table in tables:
        if table.get("type", "loop") == "loop":
            return tid
    return tables[0][0] if tables else None


def table_active(table: Mapping, now: Optional[int] = None) -> bool:
    """生效表判定（细化 §2.2 / 定稿 L78）：loop/monthly 恒生效；activity 由懒计算 is_window_open
    判定，未开始/已过期 → 自动停用（不报错、不结算）。"""
    if not isinstance(table, Mapping):
        return False
    if table.get("type", "loop") != "activity":
        return True
    period = table.get("period")
    if not isinstance(period, Mapping):
        return True  # 活动表缺 period → 视作常驻开放（防御，不崩溃）
    return is_window_open(period.get("start"), period.get("end"), now) == WINDOW_OPEN


def cycle_days_of(table: Mapping, today: object) -> int:
    """周期天数（§1.4）：loop 默认 7 可配；monthly 自动当月自然天数；activity 作进度分母。"""
    typ = table.get("type", "loop")
    period = table.get("period")
    if not isinstance(period, Mapping):
        period = {}
    if typ == "monthly":
        try:
            y, m = int(str(today)[:4]), int(str(today)[5:7])
            return calendar.monthrange(y, m)[1]
        except (ValueError, IndexError):
            return 31
    cd = _as_int(period.get("cycle_days"), DEFAULT_CYCLE_DAYS)
    if typ == "activity" and cd <= 0:
        s, e = _parse_date(period.get("start")), _parse_date(period.get("end"))
        if s is not None and e is not None and e >= s:
            return (e - s).days + 1
        return DEFAULT_CYCLE_DAYS
    return max(1, cd)


def day_index_of(table: Mapping, today: object, streak: int) -> int:
    """周期内第几天（D-01）：loop = ((streak-1) mod cycle_days)+1；monthly = 自然月当日；
    activity = 与 start 日差 + 1。"""
    typ = table.get("type", "loop")
    period = table.get("period")
    if not isinstance(period, Mapping):
        period = {}
    if typ == "monthly":
        try:
            return int(str(today)[8:10])
        except (ValueError, IndexError):
            return 1
    if typ == "activity":
        s = _parse_date(period.get("start"))
        t = _parse_date(today)
        if s is not None and t is not None and t >= s:
            return (t - s).days + 1
        return 1
    cd = cycle_days_of(table, today)
    return ((max(1, streak) - 1) % cd) + 1


# -------------------------------------------------------------------------------------
# 存档节点 / 跨月归一 / 奖励条目工具
# -------------------------------------------------------------------------------------
def _get_state(ctx: MutableMapping[str, Any], table_id: str) -> MutableMapping:
    """ctx[\"checkin_state\"][table_id] 可写节点（确保存在，按表 ID 键控，细化 §3.1 L252）。"""
    raw = ctx.get("checkin_state")
    if not isinstance(raw, MutableMapping):
        raw = {}
        ctx["checkin_state"] = raw
    node = raw.get(table_id)
    if not isinstance(node, MutableMapping):
        node = {}
        raw[table_id] = node
    return node


def _peek_state(ctx: Mapping[str, Any], table_id: str) -> Optional[MutableMapping]:
    """只读取存档节点（不存在 → None，不创建；补签失败守卫期不落档，工程补白 5）。"""
    raw = ctx.get("checkin_state")
    if not isinstance(raw, Mapping):
        return None
    node = raw.get(table_id)
    return node if isinstance(node, MutableMapping) else None


def _normalize_month(node: MutableMapping, today: object) -> None:
    """跨月归一（D-06 / TC-18）：自然月切换后 signed_days/month_total/month_milestones 归 0 重新
    累计；makeup_used 同月对齐。长线 longline 不受影响（只增不减）。"""
    mkey = _month_key(today)
    if node.get("month_key") != mkey:
        node["month_key"] = mkey
        node["signed_days"] = []
        node["month_total"] = 0
        node["month_milestones"] = []
    if node.get("makeup_month") != mkey:
        node["makeup_month"] = mkey
        node["makeup_used"] = 0


def _monthly_makeup_used(node: Optional[Mapping], today: object) -> int:
    """当月有效补签次数（审查_M4实现_批次5_jspace.md P1-1 跨月归一口径）：
    节点 makeup_month == 当前月 → 该月 makeup_used；跨月/缺失 → 0（新月份重新计数，
    不做 8 月旧 used 的误拦/错计）。守卫期与支付后应用期共用，确保月上限判定与写入同源。"""
    if not isinstance(node, Mapping):
        return 0
    if node.get("makeup_month") != _month_key(today):
        return 0
    return _as_int(node.get("makeup_used"))


def _channel_entries(entry: Mapping) -> List[dict]:
    """通道条目 {day/days, items[]{id,count}, coins, gem, exp, rep} → 单目的 reward 条目数组
    （wrapper 键剔除；items 逐条 {item,count,bound}；标量逐键 {key:value}），供 dispatch_reward。"""
    out: List[dict] = []
    if not isinstance(entry, Mapping):
        return out
    items = entry.get("items")
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, Mapping):
                continue
            iid = it.get("id", it.get("item"))
            cnt = _as_int(it.get("count"), 1)
            if isinstance(iid, str) and iid:
                out.append({"item": iid, "count": max(1, cnt), "bound": True})
    if "item" in entry or "id" in entry:
        iid = entry.get("item", entry.get("id"))
        cnt = _as_int(entry.get("count"), 1)
        if isinstance(iid, str) and iid:
            out.append({"item": iid, "count": max(1, cnt), "bound": True})
    for key in ("coins", "gem", "exp", "rep"):
        v = entry.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            out.append({key: v})
    return out


def _bonus_multiplier(table: Mapping) -> float:
    """bonus 倍率（D-04 / TC-33）：{mult|multiplier|rate|倍率:N} 或裸数值；无 → 1.0。
    mult 为内容层/校验器/编辑器正典键（审查_M4实现_批次5_jspace.md P1-3 键名分裂修复）；
    multiplier/rate/倍率 为兼容键保留。"""
    bonus = table.get("bonus")
    if isinstance(bonus, bool):
        return 1.0
    if isinstance(bonus, (int, float)):
        return float(bonus)
    if isinstance(bonus, Mapping):
        for k in ("mult", "multiplier", "rate", "倍率"):
            v = bonus.get(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)):
                return float(v)
    return 1.0


def _scale_entries(entries: List[dict], mult: float) -> List[dict]:
    """bonus 乘算（D-04）：items.count/coins/gem/exp int 向下取整；物品下限 1、标量下限 0。"""
    if mult == 1.0 or not entries:
        return entries
    out: List[dict] = []
    for e in entries:
        e = dict(e)
        if "item" in e or "id" in e:
            key = "item" if "item" in e else "id"
            e["count"] = max(1, int(e.get("count", 1) * mult))
        else:
            for k, v in list(e.items()):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    e[k] = max(0, int(v * mult))
        out.append(e)
    return out


def _daily_entry(table: Mapping, day: int) -> tuple:
    """rewards.daily[day] 条目；漏配 → (第 1 条, day) 兜底（TC-10）；无 daily → (None, None)。"""
    rewards = table.get("rewards")
    daily = rewards.get("daily") if isinstance(rewards, Mapping) else None
    if not isinstance(daily, list):
        return None, None
    for e in daily:
        if isinstance(e, Mapping) and _as_int(e.get("day")) == day:
            return e, None
    for e in daily:
        if isinstance(e, Mapping):
            return e, day  # 漏配 → 复制第 1 天兜底 + 补全提示
    return None, None


def _milestones(table: Mapping, channel: str) -> List[Mapping]:
    """rewards.streak / rewards.monthly_total 里程碑数组（仅 Mapping 元素）。"""
    rewards = table.get("rewards")
    lst = rewards.get(channel) if isinstance(rewards, Mapping) else None
    if not isinstance(lst, list):
        return []
    return [e for e in lst if isinstance(e, Mapping)]


# -------------------------------------------------------------------------------------
# 快照-回滚 / 幂等（对齐 quest.py D-04 单事务语义）
# -------------------------------------------------------------------------------------
def _snapshot(ctx: Mapping[str, Any]) -> dict:
    return {k: copy.deepcopy(ctx.get(k)) for k in _SNAP_KEYS}


def _restore(ctx: MutableMapping[str, Any], snap: dict) -> None:
    for k, v in snap.items():
        if v is None:
            ctx.pop(k, None)
        else:
            ctx[k] = v


class _Rollback(Exception):
    """单表结算失败标记（进程内回滚触发；跨进程由调用方 SQLite 事务兜底）。"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _idempotent_hit(ctx: Mapping[str, Any]) -> bool:
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    return bool(tx_id is not None and isinstance(ledger, MutableSet) and tx_id in ledger)


def _mark_idempotent(ctx: MutableMapping[str, Any]) -> None:
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    if tx_id is not None and isinstance(ledger, MutableSet):
        ledger.add(tx_id)


def _reward_ctx(ctx: MutableMapping[str, Any], table_id: str, channel: str) -> Mapping:
    """dispatch_reward 子上下文：以 {base}:checkin:{表ID}:{通道} 子 tx 记账（互不冲突，部分失败
    重放不双发，工程补白 2）；共享可变桶（currencies 等）原样引用。"""
    base = ctx.get("tx_id")
    if base is None:
        return ctx
    sub = dict(ctx)
    sub["tx_id"] = f"{base}:checkin:{table_id}:{channel}"
    return sub


# -------------------------------------------------------------------------------------
# [签到:<表名>.<字段>] 三键取值（裁决⑧，供 condition_engine 消费）
# -------------------------------------------------------------------------------------
def checkin_value(ctx: Mapping[str, Any], table: Optional[str] = None,
                  field: Optional[str] = None) -> int:
    """三键取值（裁决⑧）：连续天数=指定表 streak / 本月天数=指定表当月 signed_days / 今日已签=指定表
    今日已签；缺省表名 = 主表 loop。table 双口径（审查_M4实现_批次5_jspace.md P1-2）：生效 type 名
    （loop/monthly/activity）或 表 id 皆可；field 中文/英文皆可。
    查无表/字段/状态 → 0（对齐 condition_engine._resolve_checkin 缺省 0，未签/未满语义）。"""
    if table is None:
        table = "loop"
    if field is None:
        return 0
    internal = CHECKIN_FIELDS.get(str(field), str(field))
    if internal not in ("streak", "month_days", "today_signed"):
        return 0
    table_id = _table_id_for(ctx, str(table))
    if table_id is None:
        return 0
    node = ctx.get("checkin_state")
    node = node.get(table_id) if isinstance(node, Mapping) else None
    if not isinstance(node, Mapping):
        return 0
    t = today_of(None, _now(ctx), _cfg(ctx))
    today = t["today"]
    if internal == "streak":
        return _as_int(node.get("streak"))
    if internal == "month_days":
        return _month_days_count(node.get("signed_days"), today)
    return 1 if node.get("last_date") == today else 0


def checkin_condition_ctx(ctx: MutableMapping[str, Any]) -> dict:
    """构建/刷新 ctx[\"checkin\"] 投影 {表类型: {streak, month_days, today_signed}}——condition_engine
    _resolve_checkin（L565-582）按类型名读 ctx[\"checkin\"]，故三键消费前必须经此刷新。"""
    proj: dict = {}
    for typ in CHECKIN_TYPES:
        if _table_id_for_type(ctx, typ) is None:
            continue
        proj[typ] = {
            "streak": checkin_value(ctx, typ, "streak"),
            "month_days": checkin_value(ctx, typ, "month_days"),
            "today_signed": checkin_value(ctx, typ, "today_signed"),
        }
    ctx["checkin"] = proj
    return proj


# -------------------------------------------------------------------------------------
# 状态查询（纯读，不改存档）
# -------------------------------------------------------------------------------------
def checkin_state(ctx: Mapping[str, Any]) -> dict:
    """/状态 查询：各表当前连签 / 本月天数 / 今日已签 / 补签用量 / 进度（纯读不推进）。"""
    t = today_of(None, _now(ctx), _cfg(ctx))
    today = t["today"]
    state = ctx.get("checkin_state")
    rows: List[dict] = []
    for table_id, table in _all_checkin_tables(ctx):
        node = state.get(table_id) if isinstance(state, Mapping) else None
        if not isinstance(node, Mapping):
            node = {}
        typ = table.get("type", "loop")
        streak = _as_int(node.get("streak"))
        month_days = _month_days_count(node.get("signed_days"), today)
        today_signed = 1 if node.get("last_date") == today else 0
        day = day_index_of(table, today, max(1, streak))
        cd = cycle_days_of(table, today)
        makeup = table.get("makeup")
        makeup_cfg = makeup if isinstance(makeup, Mapping) else {}
        rows.append({
            "table_id": table_id,
            "name": table.get("name") or table_id,
            "type": typ,
            "active": table_active(table, _now(ctx)),
            "streak": streak,
            "day": day,
            "cycle_days": cd,
            "month_days": month_days,
            "month_total": _as_int(node.get("month_total")),
            "today_signed": today_signed,
            "makeup_enabled": makeup_cfg.get("enabled") is True,
            "makeup_used": _as_int(node.get("makeup_used")),
            "makeup_limit": _as_int(makeup_cfg.get("max_per_month"), 0),
            "longline": _as_int(node.get("longline")),
            "progress_current": month_days if typ == "monthly"
                                else (streak if typ == "loop" else day),
            "progress_total": cd,
        })
    return {"ok": True, "today": today, "tables": rows}


# -------------------------------------------------------------------------------------
# /签到 一次多表结算（结算管线 ①~⑥，写死不可重排，定稿 L62-73）
# -------------------------------------------------------------------------------------
def _settle_table(table: Mapping, today: str, ctx: MutableMapping[str, Any]) -> dict:
    """单表结算管线（定稿 L62-73 ①~⑥）：
    ① 懒计算跨天判定（同天幂等 / 跨天 streak+1，断签归 1）→ ② 领 daily[day] → ③ streak 里程碑 →
    ④ monthly_total 里程碑 → ⑤ 写存档 → ⑥ 汇总。bonus（D-04）对本次实际发放统一乘算；发奖单条失败
    黄字跳过不中断（D-05）；batch 级失败 → 该表快照回滚（跨表独立）。"""
    table_id = table["id"]
    name = table.get("name") or table_id
    typ = table.get("type", "loop")
    period = table.get("period")
    if not isinstance(period, Mapping):
        period = {}
    reset_on_break = True
    if isinstance(period.get("reset_on_break"), bool):
        reset_on_break = period["reset_on_break"]

    base: dict = {"table_id": table_id, "name": name, "type": typ,
                  "today": today, "active": True}
    node = _get_state(ctx, table_id)
    _normalize_month(node, today)

    last_date = node.get("last_date")
    if last_date == today:
        # ① 同天 → 今天已签到（幂等，不重复发奖，D-02 仍附进度）
        streak = _as_int(node.get("streak"))
        day = day_index_of(table, today, max(1, streak))
        cd = cycle_days_of(table, today)
        month_days = _month_days_count(node.get("signed_days"), today)
        base.update({
            "already_signed": True,
            "streak": streak, "day": day, "cycle_days": cd,
            "month_days": month_days, "today_signed": 1,
            "progress_current": month_days if typ == "monthly"
                                else (streak if typ == "loop" else day),
            "progress_total": cd,
            "granted": [], "skipped": [], "notes": [],
            "daily_granted": [], "daily_skipped": [],
            "streak_hits": [], "month_hits": [],
        })
        return base

    # ① 跨天 → 推进 streak（断签判定，定稿 L67）
    days_elapsed = _days_between(last_date, today) if last_date else 0
    if last_date is None:
        streak = 1                      # 首签
    elif days_elapsed <= 1:
        streak = _as_int(node.get("streak")) + 1
    else:                               # 断签（间隔 > 1 天）
        streak = _as_int(node.get("streak")) + 1 if not reset_on_break else 1

    day = day_index_of(table, today, streak)
    cd = cycle_days_of(table, today)
    month_days = _as_int(node.get("month_total")) + 1

    snap = _snapshot(ctx)
    daily_granted: List[dict] = []
    daily_skipped: List[dict] = []
    granted: List[dict] = []
    skipped: List[dict] = []
    notes: List[str] = []
    streak_hits: List[dict] = []
    month_hits: List[dict] = []
    try:
        # ② 领 daily[day]（漏配天数 = 复制第 1 天兜底 + 黄色提示，TC-10 / 定稿 L27）
        daily_entry, fallback = _daily_entry(table, day)
        if daily_entry is not None:
            rw = dispatch_reward(
                _scale_entries(_channel_entries(daily_entry), _bonus_multiplier(table)),
                _reward_ctx(ctx, table_id, "daily"))
            if not rw["ok"]:
                raise _Rollback("reward_failed")
            daily_granted.extend(rw["granted"])
            daily_skipped.extend(rw["skipped"])
            granted.extend(rw["granted"])
            skipped.extend(rw["skipped"])
            if fallback is not None:
                notes.append(f"第 {fallback} 天未配置，已按第 1 天奖励补全")
        # ③ streak 里程碑（恰好命中 days 阈值 → 额外发奖；每连签段至多一次，工程补白 4）
        for m in _milestones(table, "streak"):
            d = _as_int(m.get("days"))
            if d > 0 and streak == d:
                rw = dispatch_reward(
                    _scale_entries(_channel_entries(m), _bonus_multiplier(table)),
                    _reward_ctx(ctx, table_id, f"streak{d}"))
                if not rw["ok"]:
                    raise _Rollback("reward_failed")
                granted.extend(rw["granted"])
                skipped.extend(rw["skipped"])
                streak_hits.append({"days": d, "granted": rw["granted"],
                                    "skipped": rw["skipped"]})
        # ④ monthly_total 里程碑（当月累计达阈值 → 额外发奖；每档每月至多一次）
        granted_mm = node.get("month_milestones")
        if not isinstance(granted_mm, list):
            granted_mm = []
            node["month_milestones"] = granted_mm
        for m in _milestones(table, "monthly_total"):
            d = _as_int(m.get("days"))
            if d > 0 and month_days >= d and d not in granted_mm:
                rw = dispatch_reward(
                    _scale_entries(_channel_entries(m), _bonus_multiplier(table)),
                    _reward_ctx(ctx, table_id, f"month{d}"))
                if not rw["ok"]:
                    raise _Rollback("reward_failed")
                granted.extend(rw["granted"])
                skipped.extend(rw["skipped"])
                granted_mm.append(d)
                month_hits.append({"days": d, "granted": rw["granted"],
                                   "skipped": rw["skipped"]})
        # ⑤ 写存档（在全部发奖判定之后，契约 L62-73 ⑤ / 细化 §2.5）
        sd = node.get("signed_days")
        if not isinstance(sd, list):
            sd = []
        if today not in sd:
            sd.append(today)
        node["signed_days"] = sd
        node["month_total"] = month_days
        node["streak"] = streak
        node["last_date"] = today
        node["longline"] = _as_int(node.get("longline")) + 1
        llc = ctx.get("longline_counters")
        if isinstance(llc, MutableMapping):
            llc["checkin_total"] = _as_int(llc.get("checkin_total")) + 1
    except _Rollback as exc:
        _restore(ctx, snap)
        base.update({
            "failed": True, "reason": exc.reason,
            "message": "❌ 该表结算失败，已回滚",
            "streak": _as_int(node.get("streak")) if isinstance(node, Mapping) else 0,
            "today_signed": 0, "granted": [], "skipped": [], "notes": [],
            "daily_granted": [], "daily_skipped": [], "streak_hits": [], "month_hits": [],
        })
        return base

    base.update({
        "already_signed": False,
        "streak": streak, "day": day, "cycle_days": cd,
        "month_days": month_days, "today_signed": 1,
        "progress_current": month_days if typ == "monthly"
                            else (streak if typ == "loop" else day),
        "progress_total": cd,
        "granted": granted, "skipped": skipped, "notes": notes,
        "daily_granted": daily_granted, "daily_skipped": daily_skipped,
        "streak_hits": streak_hits, "month_hits": month_hits,
    })
    return base


def _grant_label(grant: Mapping) -> str:
    """grant 记录 → 简短展示标签（「药水×2」「50 金币」「exp20」）。"""
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


def _summary_lines(results: List[dict], today: str) -> List[str]:
    """汇总单条消息（定稿 L25/L210 防刷屏：一次 /签到 汇总所有生效表单条消息输出；2.4 模板口径）。
    纯文本渲染（3d D-01：去除 ┌─📅 表框 / ⚠ 装饰 emoji——审查_M4实现_批次2_jspace.md 后续衔接提醒
    L221；指令层仍按 tables 重建正文，本 message 仅作引擎侧兜底/测试口径）。"""
    lines = ["签到汇总"]
    for r in results:
        if not r.get("active", True):
            continue
        lines.append(f"═══ {r.get('name')}（{_TYPE_CN.get(r.get('type'), r.get('type'))}）═══")
        if r.get("already_signed"):
            lines.append("今天已签到（不重复发奖）")
            pc, pt = r.get("progress_current"), r.get("progress_total")
            lines.append(f"连签天数：{r.get('streak', 0)} 天 ｜ 进度 {pc}/{pt}")
            continue
        if r.get("failed"):
            lines.append(r.get("message", "结算失败，已回滚"))
            continue
        daily = r.get("daily_granted") or []
        if daily:
            lines.append("今日奖励：" + "、".join(_grant_label(g) for g in daily[:4]))
        else:
            lines.append("今日奖励：无")
        for n in r.get("notes") or []:
            lines.append(str(n))
        pc, pt = r.get("progress_current"), r.get("progress_total")
        lines.append(f"连签天数：{r.get('streak', 0)} 天 ｜ 进度 {pc}/{pt}")
        for h in r.get("streak_hits") or []:
            labs = "、".join(_grant_label(g) for g in h["granted"][:4])
            lines.append(f"[连签里程碑达成] {labs}（连签 {h['days']} 天）")
        for h in r.get("month_hits") or []:
            labs = "、".join(_grant_label(g) for g in h["granted"][:4])
            lines.append(f"[月度累计达成] {labs}（本月签满 {h['days']} 天）")
    return lines


def checkin_do(ctx: MutableMapping[str, Any]) -> dict:
    """/签到：一次完成所有生效表结算 → 汇总单条消息（定稿 L21/L62-73/L210）。

    生效表集合 = 逐表懒计算判定（loop/monthly 恒生效；activity 未开始/已过期自动停用，L78）。
    各表独立执行管线 ①~⑥；跨表互相独立（一表失败不影响其他表，D-05）；bonus 统一乘算（D-04）；
    同日重复 → 幂等「今天已签到」不重复发奖（D-02 仍附进度）；version 幂等（tx_id/ledger）。
    """
    if not isinstance(ctx, MutableMapping):
        return {"ok": False, "reason": "invalid_ctx", "message": "❌ 结算上下文非法"}
    if _idempotent_hit(ctx):
        st = checkin_state(ctx)
        return {"ok": True, "idempotent": True, "already_signed": True,
                "message": "今天已签到（重复指令，未重复发放）",
                "today": st["today"], "tables": st["tables"]}
    t = today_of(None, _now(ctx), _cfg(ctx))
    today = t["today"]
    results: List[dict] = []
    for table_id, table in _all_checkin_tables(ctx):
        if not table_active(table, _now(ctx)):
            results.append({"table_id": table_id, "name": table.get("name") or table_id,
                            "type": table.get("type", "loop"), "active": False})
            continue
        results.append(_settle_table(table, today, ctx))
    checkin_condition_ctx(ctx)          # 刷新三键投影（结算后键值已更新，TC-32）
    _mark_idempotent(ctx)
    return {"ok": True, "today": today, "tables": results,
            "message": "\n".join(_summary_lines(results, today))}


# -------------------------------------------------------------------------------------
# /签到 补签（默认关 / 两通道 / 月上限；裁决⑦ 只计不补发）
# -------------------------------------------------------------------------------------
def checkin_makeup(ctx: MutableMapping[str, Any], table_id: Optional[str] = None) -> dict:
    """/签到 补签：作用于目标表当前归属日 today（工程补白 5）。

    校验链：① ctx 合法 → ② 幂等闸（重放不双扣）→ ③ 目标表存在且生效 → ④ makeup.enabled 开 →
    ⑤ 同日幂等（今日已签/已补 → 不重复扣费，D-03/TC-24）→ ⑥ 月上限 max_per_month（0=不限；
    按「makeup_month 与当前月比对后的当月有效 used」判定，跨月视为 0——审查批次5 P1-1）→
    ⑦ 两通道任一满足（① 补签卡 ② 货币 cost）。
    应用（裁决⑦ 只计不补发）：signed_days 追加 today + streak 连续性保持 + month_total +1 +
    makeup_used +1；**不补发所补日期 daily 奖励、不触发任何里程碑**；longline 只增不减。
    """
    if not isinstance(ctx, MutableMapping):
        return {"ok": False, "reason": "invalid_ctx", "message": "❌ 结算上下文非法"}
    if _idempotent_hit(ctx):
        return {"ok": True, "idempotent": True,
                "message": "已补签（重复指令，未重复扣费）"}
    t = today_of(None, _now(ctx), _cfg(ctx))
    today = t["today"]

    if table_id is None:
        table_id = _primary_table_id(ctx)      # 缺省目标表 = 主表 loop（裁决⑧ 口径）
    if table_id is None:
        return {"ok": False, "reason": "no_table", "message": "❌ 未配置签到表"}
    table = resolve_checkin_table(ctx, table_id)
    if table is None:
        return {"ok": False, "reason": "no_table", "message": "❌ 签到表不存在"}
    if not table_active(table, _now(ctx)):
        return {"ok": False, "reason": "table_inactive", "message": "❌ 该签到表当前未生效",
                "table_id": table_id}
    makeup = table.get("makeup")
    if not isinstance(makeup, Mapping) or makeup.get("enabled") is not True:
        return {"ok": False, "reason": "makeup_disabled", "message": "❌ 当前未开启补签",
                "table_id": table_id}

    node = _peek_state(ctx, table_id)          # 守卫期只读，不落档（工程补白 5）
    sd = node.get("signed_days") if isinstance(node, Mapping) else None
    if not isinstance(sd, list):
        sd = []
    if today in sd:
        # 同日幂等（D-03 / TC-24）：今日已签或已补 → 不重复扣费、makeup_used 不 +1
        return {"ok": True, "idempotent": True, "already_signed": True,
                "message": "今日已补过/已签到，无需重复补签", "table_id": table_id,
                "streak": _as_int(node.get("streak")) if isinstance(node, Mapping) else 0,
                "month_days": len(sd),
                "makeup_used": _monthly_makeup_used(node, today)}

    # 月上限（TC-22/23；审查_M4实现_批次5_jspace.md P1-1：按「makeup_month 与当前月比对后的
    # 当月有效 used」判定，跨月视为 0 —— 新月份首日补签不误拦、不限 0 时不错计）
    max_per_month = _as_int(makeup.get("max_per_month"), 0)
    used = _monthly_makeup_used(node, today)
    if max_per_month > 0 and used >= max_per_month:
        return {"ok": False, "reason": "makeup_limit",
                "message": f"❌ 本月补签已达上限 {max_per_month} 次", "table_id": table_id,
                "makeup_used": used, "max_per_month": max_per_month}

    snap = _snapshot(ctx)
    try:
        # 两通道（TC-20/21）：① 补签卡 ② 货币付费 cost（任一满足即可用，定稿 L58）
        card_item = makeup.get("card_item") or ctx.get("makeup_card_item") or MAKEUP_CARD_ITEM
        if _count_item(ctx, card_item) >= 1:
            if not _remove_item(ctx, card_item, 1):
                raise _Rollback("card_remove_failed")
            channel = "card"
        else:
            cost = makeup.get("cost")
            if not isinstance(cost, Mapping) or not cost:
                raise _Rollback("no_payment_channel")
            shortage = _currency_shortage(ctx, cost)
            if shortage:
                _restore(ctx, snap)
                return {"ok": False, "reason": "insufficient_currency",
                        "message": "❌ 货币不足，补签失败", "table_id": table_id,
                        "detail": shortage}
            _deduct_currency(ctx, cost)
            channel = "currency"

        # 应用（支付成功后才落档）：只计不补发（裁决⑦），不发 daily/里程碑
        node = _get_state(ctx, table_id)
        _normalize_month(node, today)
        sd = node.get("signed_days")
        if not isinstance(sd, list):
            sd = []
        if today not in sd:
            sd.append(today)
        node["signed_days"] = sd
        node["month_total"] = len(sd)
        if node.get("last_date") != today:
            node["streak"] = _as_int(node.get("streak")) + 1
            node["last_date"] = today
        # P1-1 跨月归一口径：_normalize_month 后 makeup_month 已对齐当前月，
        # 用「当月有效 used + 1」写入（跨月首笔 = 1，不再沿用上月 used 错计）
        node["makeup_used"] = _monthly_makeup_used(node, today) + 1
        node["longline"] = _as_int(node.get("longline")) + 1
        llc = ctx.get("longline_counters")
        if isinstance(llc, MutableMapping):
            llc["checkin_total"] = _as_int(llc.get("checkin_total")) + 1
    except _Rollback as exc:
        _restore(ctx, snap)
        if exc.reason == "no_payment_channel":
            return {"ok": False, "reason": "no_payment_channel",
                    "message": "❌ 补签需要补签卡或货币，当前无可用通道", "table_id": table_id}
        return {"ok": False, "reason": exc.reason, "message": "❌ 补签失败，已回滚",
                "table_id": table_id}

    checkin_condition_ctx(ctx)          # 刷新三键投影
    _mark_idempotent(ctx)
    return {"ok": True, "channel": channel, "table_id": table_id,
            "message": "✅ 补签成功（" + channel + "）· 只计不补发",
            "streak": _as_int(node.get("streak")), "month_days": len(sd),
            "makeup_used": _as_int(node.get("makeup_used")), "max_per_month": max_per_month}

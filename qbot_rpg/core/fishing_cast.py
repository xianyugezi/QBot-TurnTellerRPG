"""M10 批2·路2B：抛竿 + 鱼讯 接线服务（qbot_rpg/core/fishing_cast.py）。

cast_fishing / bite_trigger —— 被路2A cmd_fishing 有参分支调用的抛竿 + 鱼讯接线层。

文件名：qbot_rpg/core/fishing_cast.py
创建时间：2026-08-31
作者：Hermes 子agent-2B（M10 钓鱼实现组批2·路2B：抛竿 + 鱼讯 接线服务；兄弟路2A/2C
      独占 commands/，本文件零 import 之，只读勿探查）

功能描述（T06 后半 / T07）：
  - cast_fishing(ctx, spot_id)：抛竿接线（被路2A cmd_fishing 有参分支调用）——
    ① 钓点解析 resolve_spot（名称/前缀匹配，对齐 M9 resolve 三态：精确 → 唯一前缀 →
       歧义/未找到）；② 调 FishingEngine.start_fishing（守卫 GU-01~04 由引擎拦，扣饵
       无饵保底 + 日计数+1 + 懒计时期注册）；③ 组装下钩成功消息（钓点/等待时长/日计数/
       饵使用情况）；wait_sec=0 即收提示（TC-07）。
  - bite_trigger(ctx, king_hit=False)：鱼讯接线（调引擎 bite_check 懒判到期）——未到期 →
    等待中消息（钓点/已耗时，TC-21）；到期 → 组装鱼讯三类消息（微动/拉扯/猛烈，按
    目标 rarity 映射）+ 金闪覆写位（king_hit 批4 接线，本路 golden 默认 False，TC-13）+
    收杆提醒（/收杆 满力/自动/止损，TC-22）。
  - fish_intent_of：复用 qbot_rpg/core/fishing.py 内实现（勿重写，先 grep 签名确认后
    import；本路不调用，保留供批4 金闪接线与测试断言消费）。

引擎复用（接口锚点）：
  - _engine_of(ctx)：ctx["fishing_engine"] 已注入 FishingEngine 实例 → 复用；缺省 →
    自建 FishingEngine(settings=ctx.get("settings"), rng=ctx.get("rng"))（species 由
    引擎运行期读 ctx["fish_table"]/ctx["fishing"]，测试直注 fish_table）。
  - 每日计数：引擎已做 fish_state{today, casts}（dayroll 懒重置）；本路只读展示。
  - 确定性：rng 走 ctx["rng"]（make_context 注入）或引擎注入 rng；禁裸 random。

消息输出：本地常量（批6 fishing_tpl 分区迁移，同路2A 约定）；零 emoji。

依据：细化_2c1b §一 1.2（下钩，GU-01~04 + 扣饵/日计数/懒计时期）+ §三（鱼讯三类
      §3.1 rarity→讯类映射 + §3.3 金闪覆写 + §3.4 决策窗）+ §五（/鱼讯 推进 TC-21/22）
      + 定稿 §1 M3（抛竿 L17）/ M4（鱼讯 L18）
      + docs/m10_shared_contract.md §五 铁律 + docs/m10_接口摸底.md §一（harvest_at
      懒判）/ §二（fish_intent_of rarity 直接映射）/ §八-3（ctx fish_table/fishing_cfg
      注入形态）/ §九（rng 注入、零定时器、确定性）
模式参考：
  - qbot_rpg/core/forge_tree.py resolve_node（M9 resolve 三态：精确 → 唯一前缀 → 歧义）
  - qbot_rpg/core/fishing.py（引擎复用 + MSG_* 常量 TODO 模板化惯例，批6 迁移）
  - qbot_rpg/core/quest.py / shop.py（ctx 注入确定性）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  C-1  钓点「名称」= 钓点 id：细化 §1.1 垂钓点 = 地图采集点变体（素材取自 maps 采集点，
      无独立名称字段）；本路 resolve 以钓点 id（如 gp_moon_grass）为可匹配名——精确
      命中 / 唯一前缀命中 / 歧义列候选 / 未找到。更细的 maps 采集点「时段偏好/稀有度
      标记」展示归路2A（列钓点）职责，本路只做下钩输入的 id 解析。
  C-2  resolve 数据源：已知钓点集 = 引擎 species 池 spots 并集（同 engine._known_spots
      口径），本路独立实现 _known_spot_ids（读 ctx["fish_table"] / ctx["fishing"]
      ["species"]，避免调引擎私有方法），resolve 结果与引擎 GU-03 同源同判。
  C-3  金闪覆写位：细化 §3.3 金闪 = 鱼王事件命中；批4 路4B 接线 king_hit 判定，本路
      bite_trigger(ctx, king_hit=False) 默认 False → golden 恒 False（金闪只可能出现在
      猛烈鱼讯，微动/拉扯永不金闪，TC-13 由 fish_intent_of 承载）。
  C-4  已耗时口径：bite_trigger 等待中消息的已耗时 = now - cast_at（懒计算期，未到期
      可能为负 → 夹取 0 展示），对齐细化 §五「S2 查询 钓点/已耗时/等待中」。

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器/零睡眠（时间戳懒判，无实时
      倒计时）；docstring 勿写字面定时器调用字样（M43 探针，用零定时器/零睡眠措辞）；
      零 emoji；本路独占 core/fishing_cast.py + tests/unit/test_fishing_cast.py，
      不碰 commands/ 与 core/fishing.py（批1 已落盘）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping

from qbot_rpg.core.fishing import (
    KIND_LABELS,
    STATE_BITE,
    STATE_IDLE,
    STATE_WAITING,
    FishingEngine,
    fish_intent_of,
)

# =====================================================================================
# 消息常量（TODO 模板化：批6 fishing_tpl 分区迁移，默认模板与旧输出逐字一致；本路
# 返回结构化 dict，文案仅为骨架占位，批6 迁模板后指令壳经 tpl_of 渲染）
# =====================================================================================
MSG_SPOT_NOT_FOUND: str = "钓点不存在：{key}"
MSG_SPOT_AMBIGUOUS: str = "钓点「{key}」匹配多个，请指定完整名称：{candidates}"
MSG_CAST_OK: str = (
    "已抛竿：钓点「{spot}」，等待 {wait_sec} 秒后鱼讯；今日已抛 {casts} 次；{bait_line}"
)
MSG_CAST_IMMEDIATE: str = (
    "已抛竿：钓点「{spot}」，鱼讯即刻可查（即收）；今日已抛 {casts} 次；{bait_line}"
)
MSG_BAIT_LINE: str = "饵：{bait}"
MSG_BAIT_NONE: str = "无饵抛竿（不吃对口饵加成）"
MSG_WAITING: str = "等待中：钓点「{spot}」，已等待 {elapsed} 秒，尚未有鱼讯"
MSG_BITE: str = "鱼讯：{label}"
MSG_GOLDEN_MARK: str = "金闪：鱼王出没"  # 批4 接线后才可能渲染（本路 golden 恒 False）
MSG_REEL_HINT: str = "请选择收杆方式：/收杆 满力 /收杆 自动 /收杆 止损"


# =====================================================================================
# 纯函数工具（零 NoneBot、确定性、ctx 注入）
# =====================================================================================
def _known_spot_ids(ctx: Mapping[str, Any]) -> List[str]:
    """已知钓点集（C-2）：引擎 species 池 spots 并集——读 ctx["fish_table"]（Mapping
    id→raw dict，values 的 spots 键）或 ctx["fishing"]["species"]（raw list，逐条的
    spots 键）。去重保序（鱼种顺序）。无可解析 → []（resolve 全 miss）。"""
    spots: List[str] = []
    seen: set = set()

    def _absorb(entry: object) -> None:
        if not isinstance(entry, Mapping):
            return
        raw_spots = entry.get("spots")
        if isinstance(raw_spots, (list, tuple)):
            for s in raw_spots:
                if isinstance(s, str) and s.strip() and s not in seen:
                    seen.add(s)
                    spots.append(s)

    ft = ctx.get("fish_table")
    if isinstance(ft, Mapping):
        for entry in ft.values():
            _absorb(entry)
    fishing = ctx.get("fishing")
    if isinstance(fishing, Mapping):
        species = fishing.get("species")
        if isinstance(species, list):
            for entry in species:
                _absorb(entry)
    return spots


def resolve_spot(ctx: Mapping[str, Any], key: object) -> Dict[str, Any]:
    """钓点解析（C-1/C-2，对齐 M9 resolve 三态）：key 非空 str 才参与匹配。

    匹配序：精确命中（key == 钓点 id）→ 唯一前缀（恰一钓点 id 以 key 开头）→
    歧义（多候选）→ 未找到。出参：
      {ok, match, spot_id, candidates}
      match ∈ {exact, prefix, ambiguous, not_found}；exact/prefix 带 spot_id；
      ambiguous 带 candidates（按已知钓点序）；not_found candidates 空。
    """
    if not isinstance(key, str) or not key.strip():
        return {"ok": False, "match": "not_found", "spot_id": None, "candidates": []}
    k = key.strip()
    known = _known_spot_ids(ctx)
    if k in known:
        return {"ok": True, "match": "exact", "spot_id": k, "candidates": []}
    hits = [s for s in known if s.startswith(k)]
    if not hits:
        return {"ok": False, "match": "not_found", "spot_id": None, "candidates": []}
    if len(hits) == 1:
        return {"ok": True, "match": "prefix", "spot_id": hits[0], "candidates": []}
    return {"ok": False, "match": "ambiguous", "spot_id": None, "candidates": hits}


def _engine_of(ctx: MutableMapping[str, Any]) -> FishingEngine:
    """引擎复用：ctx["fishing_engine"] 已注入 → 复用；缺省 → 自建兜底
    （构造器注入 ctx settings + rng，species 运行期读 ctx，确定性）。"""
    eng = ctx.get("fishing_engine")
    if isinstance(eng, FishingEngine):
        return eng
    settings = ctx.get("settings")
    rng = ctx.get("rng")
    return FishingEngine(
        settings=settings if isinstance(settings, Mapping) else None,
        rng=rng,
    )


def _bait_line(bait_used: object) -> str:
    """饵使用情况行：bait_used 非空 str → 「饵：X」；None/空 → 无饵保底提示。"""
    if isinstance(bait_used, str) and bait_used.strip():
        return MSG_BAIT_LINE.format(bait=bait_used)
    return MSG_BAIT_NONE


# =====================================================================================
# 抛竿接线（T06 后半）：resolve → 引擎守卫 → 组装下钩成功消息
# =====================================================================================
def cast_fishing(ctx: MutableMapping[str, Any], spot_id: object) -> dict:
    """抛竿接线：钓点解析 + 引擎 start_fishing（守卫 GU-01~04 由引擎拦）+ 组装消息。

    出参（结构化 dict）：
      - 解析失败：{ok:False, reason:"spot_not_found"|"spot_ambiguous", message,
        candidates?}（GU-03 语义，未进引擎）。
      - 引擎拒绝：透传引擎返回（guard/reason/message/state 全保留，GU-01/02/04）。
      - 下钩成功：{ok:True, state:"S2", spot_id, wait_sec, cast_at, bait_used,
        casts, message}——message 含 钓点/等待时长/日计数/饵使用情况；wait_sec=0 →
        MSG_CAST_IMMEDIATE 即收提示（TC-07）。
    """
    res = resolve_spot(ctx, spot_id)
    if not res["ok"]:
        if res["match"] == "ambiguous":
            cand = res.get("candidates") or []
            return {
                "ok": False, "reason": "spot_ambiguous",
                "message": MSG_SPOT_AMBIGUOUS.format(
                    key=str(spot_id), candidates="、".join(str(c) for c in cand)),
                "candidates": list(cand),
            }
        return {"ok": False, "reason": "spot_not_found",
                "message": MSG_SPOT_NOT_FOUND.format(key=str(spot_id))}

    eng = _engine_of(ctx)
    got = eng.start_fishing(ctx, res["spot_id"])
    if not got.get("ok"):
        return dict(got)  # 守卫 GU-01/02/03/04 拒绝透传（引擎 message 已就绪）

    spot = str(res["spot_id"])
    wait_sec = int(got.get("wait_sec") or 0)
    bait_used = got.get("bait_used")
    fs = ctx.get("fish_state")
    casts = int(fs.get("casts") or 0) if isinstance(fs, Mapping) else 0
    bait_line = _bait_line(bait_used)

    if wait_sec == 0:
        message = MSG_CAST_IMMEDIATE.format(
            spot=spot, casts=casts, bait_line=bait_line)
    else:
        message = MSG_CAST_OK.format(
            spot=spot, wait_sec=wait_sec, casts=casts, bait_line=bait_line)

    return {
        "ok": True, "state": STATE_WAITING, "spot_id": spot,
        "wait_sec": wait_sec, "cast_at": got.get("cast_at"), "bait_used": bait_used,
        "casts": casts, "message": message,
    }


# =====================================================================================
# 鱼讯接线（T07）：懒判到期 → 等待中 / 鱼讯三类 + 金闪覆写位 + 收杆提醒
# =====================================================================================
def bite_trigger(ctx: MutableMapping[str, Any], king_hit: bool = False) -> dict:
    """鱼讯接线：调引擎 bite_check（懒判 now >= cast_at）→ 组装消息。

    king_hit：金闪覆写位（批4 路4B 鱼王事件命中时传 True）；本路默认 False →
    golden 恒 False（TC-13 金闪隔离；微动/拉扯永不金闪）。

    出参（结构化 dict）：
      - 引擎拒绝（off/simple/无钓局）：透传引擎返回（guard/reason/message/state）。
      - 未到期等待中：{ok:True, bite:False, state:"S2", spot_id, elapsed_sec,
        message}——message 含 钓点/已耗时/等待中（TC-21）。
      - 到期咬钩：{ok:True, bite:True, kind, golden, state:"S3",
        target_species_id, target_rarity, message}——message 含 讯类（三类映射）+
        金闪标记行（仅 golden）+ 收杆提醒（TC-22）。
    """
    eng = _engine_of(ctx)
    got = eng.bite_check(ctx, king_hit=bool(king_hit))
    if not got.get("ok"):
        return dict(got)  # off / simple / no_session 拒绝透传

    fs = ctx.get("fish_state")
    spot = str(fs.get("spot_id") or "") if isinstance(fs, Mapping) else ""

    if not got.get("bite"):
        # 未到期等待中（TC-21）：钓点/已耗时/等待中——已耗时 = now - 下钩时刻
        # （cast_at - wait_sec，懒计算期跨会话可算）
        cast_at = int(fs.get("cast_at") or 0) if isinstance(fs, Mapping) else 0
        wait_sec = int(fs.get("wait_sec") or 0) if isinstance(fs, Mapping) else 0
        now = ctx.get("now")
        now_i = int(now) if now is not None else 0
        cast_start = cast_at - wait_sec
        elapsed = max(0, now_i - cast_start)
        return {
            "ok": True, "bite": False, "state": STATE_WAITING, "spot_id": spot,
            "elapsed_sec": elapsed,
            "message": MSG_WAITING.format(spot=spot, elapsed=elapsed),
        }

    # 到期咬钩：讯类 + 金闪标记行 + 收杆提醒（TC-22）
    kind = got.get("kind")
    golden = bool(got.get("golden", False))
    label = KIND_LABELS.get(str(kind), str(kind)) if kind is not None else str(kind)
    lines: List[str] = [MSG_BITE.format(label=label)]
    if golden:
        lines.append(MSG_GOLDEN_MARK)
    lines.append(MSG_REEL_HINT)
    return {
        "ok": True, "bite": True, "kind": kind, "golden": golden,
        "state": STATE_BITE,
        "target_species_id": got.get("target_species_id"),
        "target_rarity": got.get("target_rarity"),
        "message": "\n".join(lines),
    }


__all__ = [
    # 消息常量
    "MSG_SPOT_NOT_FOUND", "MSG_SPOT_AMBIGUOUS",
    "MSG_CAST_OK", "MSG_CAST_IMMEDIATE", "MSG_BAIT_LINE", "MSG_BAIT_NONE",
    "MSG_WAITING", "MSG_BITE", "MSG_GOLDEN_MARK", "MSG_REEL_HINT",
    # 纯函数
    "_known_spot_ids", "resolve_spot", "_engine_of", "_bait_line",
    # 接线服务
    "cast_fishing", "bite_trigger",
    # 复用
    "fish_intent_of", "FishingEngine",
    "STATE_IDLE", "STATE_WAITING", "STATE_BITE",
]

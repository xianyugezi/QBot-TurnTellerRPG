"""worldtime 变化检测 + 懒广播单测（M3 批次1·路D · M33/M34 · IF09/IF10）。

依据：细化_2a4a_时间引擎 §3.1（变化检测钩子 / 离线只报最新）/ §3.2（配置即重排）/
      §3.3（一次 ≤3 条顺序固定 季节→时段→天气）/ §4.3（跨群去重）
      + 细化_2a4c_时间天气接口 §1.1（IF09 check_changes / IF10 maybe_broadcast）/ §1.2（广播配置默认关）
      + m3_shared_contract §5.3（IF09/IF10 签名与语义）。

手算基准沿用 test_time_cycle_config：默认配置 7 天/季 · 60 分/段 · 60 分/抽，ANCHOR=946656000；
  2026-08-16 00:00 UTC+8 → season_idx=1（夏）、period_idx=1（午）、weather_tick=233376。
纯函数测试：IF09 经 player_ctx["now"] 注入时间戳，零 IO、零定时器。

【工程补白断言】：
  - 天气播报文案（name/emoji）需调用方经 IF04/IF08（批次2）取键后挂 Change——本路未挂载则
    占位符留空（test_broadcast_weather_without_display_fields_documents_boundary）。
  - 季节/时段中文名 + emoji 取本模块约定值（展示补白），可被 Change['emoji']/['name'] 覆盖。
"""
from __future__ import annotations

import datetime

from qbot_rpg.engine.worldtime import ANCHOR, DEFAULT_POOL, WorldTime

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


def default_cfg() -> dict:
    """默认 time_cycle 配置（细化_2a4a §1.3 拍板值）；broadcast.enabled 缺省 false。"""
    return {"time_cycle": {
        "enabled": True,
        "season": {"season_days": 7},
        "period": {"period_minutes": 60},
        "weather": {"weather_minutes": 60, "default_pool": list(DEFAULT_POOL)},
        "broadcast": {"enabled": False, "mode": "lazy"},
    }}


def broadcast_cfg(template=None) -> dict:
    """开启懒广播的配置；template 可选覆盖缺省 `{emoji} {name}`。"""
    cfg = default_cfg()
    cfg["time_cycle"]["broadcast"]["enabled"] = True
    if template is not None:
        cfg["time_cycle"]["broadcast"]["template"] = template
    return cfg


# -------------------------------------------------------------------------------------
# IF09 check_changes（比较缓存索引与公式重算值 → 变化列表）
# -------------------------------------------------------------------------------------
def test_no_changes_when_cache_matches():
    """缓存索引 == 公式重算值 → 无变化。"""
    wt = WorldTime(default_cfg())
    now = _ts(2026, 8, 16)
    cached = {"season_idx": 1, "period_idx": 1, "weather_tick": 233376}
    assert wt.check_changes(cached, {"now": now}) == []


def test_single_season_change():
    """只有季节变化 → 仅报一条 season（period/weather 未变不报）。"""
    wt = WorldTime(default_cfg())
    now = _ts(2026, 8, 16)
    cached = {"season_idx": 0, "period_idx": 1, "weather_tick": 233376}
    assert wt.check_changes(cached, {"now": now}) == [
        {"kind": "season", "old": 0, "new": 1}
    ]


def test_three_changes_fixed_order_season_period_weather():
    """三周期全变 → 顺序固定 季节→时段→天气。"""
    wt = WorldTime(default_cfg())
    # 2000-01-09 00:00：diff=200h → season=floor(200/168)%4=1 夏、period=200%5=0 晨、weather=200
    now = ANCHOR + 200 * 3600
    cached = {"season_idx": 3, "period_idx": 4, "weather_tick": 100}
    ch = wt.check_changes(cached, {"now": now})
    assert [c["kind"] for c in ch] == ["season", "period", "weather"]
    assert ch == [
        {"kind": "season", "old": 3, "new": 1},
        {"kind": "period", "old": 4, "new": 0},
        {"kind": "weather", "old": 100, "new": 200},
    ]


def test_offline_spanning_many_periods_reports_latest_once():
    """离线跨多周期 → 每条 kind 只报最新值一次，不逐条追报。"""
    wt = WorldTime(default_cfg())
    # 缓存停在 10h，30h 后才回来：期间跨 20 个时段；period 30%5=0、weather=30
    cached = {"season_idx": 0, "period_idx": 3, "weather_tick": 10}
    now = ANCHOR + 30 * 3600
    ch = wt.check_changes(cached, {"now": now})
    assert [c["kind"] for c in ch] == ["period", "weather"]  # season 未变（0 仍是春）不报
    kinds = [c["kind"] for c in ch]
    assert len(kinds) == len(set(kinds))  # 每条 kind 只出现一次
    assert ch[1] == {"kind": "weather", "old": 10, "new": 30}  # 只报最新 tick，不枚举 11..30


def test_merge_cap_max_three():
    """三周期全变 → 恰好 3 条（一次 ≤3 条上限）。"""
    wt = WorldTime(default_cfg())
    cached = {"season_idx": 0, "period_idx": 0, "weather_tick": 0}
    ch = wt.check_changes(cached, {"now": _ts(2026, 8, 16)})
    assert len(ch) <= 3
    assert len(ch) == 3
    assert [c["kind"] for c in ch] == ["season", "period", "weather"]


def test_missing_cache_is_first_time_full_change():
    """缺缓存（空 dict / None / 部分缺键）→ 首次全变化（old=None）。"""
    wt = WorldTime(default_cfg())
    now = _ts(2026, 8, 16)
    full = [
        {"kind": "season", "old": None, "new": 1},
        {"kind": "period", "old": None, "new": 1},
        {"kind": "weather", "old": None, "new": 233376},
    ]
    assert wt.check_changes({}, {"now": now}) == full
    assert wt.check_changes(None, {"now": now}) == full  # type: ignore[arg-type]
    # 部分缺键：season 已缓存且吻合 → 只报 period/weather 首次
    assert wt.check_changes({"season_idx": 1}, {"now": now}) == [
        {"kind": "period", "old": None, "new": 1},
        {"kind": "weather", "old": None, "new": 233376},
    ]


def test_check_changes_reconfig_invalidates_old_cache():
    """配置即重排（细化_2a4a §3.2）：season_days 改 2 → 旧 7 天缓存失效 → 检测到换季变化。"""
    cfg = default_cfg()
    cfg["time_cycle"]["season"]["season_days"] = 2
    wt = WorldTime(cfg)
    now = _ts(2026, 8, 16)
    # 2 天/季：season_idx = floor(9724/2)%4 = 4862%4 = 2（秋）；period/weather 配置未变仍吻合
    ch = wt.check_changes({"season_idx": 1, "period_idx": 1, "weather_tick": 233376}, {"now": now})
    assert ch == [{"kind": "season", "old": 1, "new": 2}]


def test_check_changes_no_player_ctx_uses_current_time():
    """player_ctx 缺省（None/非 Mapping）→ 用当前时刻；仅验证不崩溃、形状正确（纯函数零 IO）。"""
    ch = WorldTime(default_cfg()).check_changes({})
    assert isinstance(ch, list)
    assert len(ch) <= 3
    assert all(set(c) == {"kind", "old", "new"} for c in ch)


# -------------------------------------------------------------------------------------
# IF10 maybe_broadcast（懒广播：默认关；纯文案产出，零消息发送）
# -------------------------------------------------------------------------------------
def test_broadcast_disabled_returns_empty():
    """broadcast.enabled 缺省 false（/显式 false / 系统总开关 false）→ 返回 []。"""
    wt = WorldTime(default_cfg())
    chs = [{"kind": "season", "old": 0, "new": 1}]
    assert wt.maybe_broadcast(chs) == []
    cfg = default_cfg()
    cfg["time_cycle"]["broadcast"]["enabled"] = False
    assert WorldTime(cfg).maybe_broadcast(chs) == []
    # time_cycle.enabled=false → IF01 链整体失效（细化_2a4c §1.2）
    cfg2 = broadcast_cfg()
    cfg2["time_cycle"]["enabled"] = False
    assert WorldTime(cfg2).maybe_broadcast(chs) == []


def test_broadcast_enabled_renders_default_template():
    """开启后缺省模板 `{emoji} {name}`：季节/时段中文名 + emoji 由引擎自解。"""
    wt = WorldTime(broadcast_cfg())
    assert wt.maybe_broadcast([{"kind": "season", "old": 0, "new": 1}]) == ["☀️ 夏"]
    assert wt.maybe_broadcast([{"kind": "season", "old": 1, "new": 2}]) == ["🍂 秋"]
    assert wt.maybe_broadcast([{"kind": "period", "old": 2, "new": 3}]) == ["🌙 夜"]


def test_broadcast_template_placeholder_replacement():
    """自定义模板占位符 {type,name,emoji,map} 替换；天气经调用方挂展示字段。"""
    wt = WorldTime(broadcast_cfg(template="【{type}】{emoji} {name}（{map}）"))
    chs = [{"kind": "season", "old": 0, "new": 1}]
    assert wt.maybe_broadcast(chs, {"map": "初始之森"}) == ["【季节】☀️ 夏（初始之森）"]
    # 天气：调用方经 IF04/IF08 取键后挂 name/emoji/map（批次2 接线；本路纯透传）
    wch = {"kind": "weather", "old": 10, "new": 30, "name": "雷雨", "emoji": "⛈️", "map": "暴风峡谷"}
    assert wt.maybe_broadcast([wch]) == ["【天气】⛈️ 雷雨（暴风峡谷）"]
    # Change 自带 map 优先于 ctx 传入的 map
    assert wt.maybe_broadcast(
        [{"kind": "period", "old": 1, "new": 0, "map": "海边"}], {"map": "别处"}
    ) == ["【时段】🌅 晨（海边）"]


def test_broadcast_multiple_changes_merged_ordered():
    """多变化合并：每条一条文案，顺序 季节→时段→天气，≤3 条（合并一行由调用方 join）。"""
    wt = WorldTime(broadcast_cfg())
    chs = [
        {"kind": "season", "old": 0, "new": 1},
        {"kind": "period", "old": 4, "new": 0},
        {"kind": "weather", "old": 10, "new": 30, "name": "雨", "emoji": "🌧️"},
    ]
    out = wt.maybe_broadcast(chs)
    assert out == ["☀️ 夏", "🌅 晨", "🌧️ 雨"]
    assert len(out) <= 3


def test_broadcast_cross_group_dedup_by_seen_index():
    """跨群去重：已播索引（seen）命中 → 该条跳过；去重状态由路E 持久化，本路仅读不改。"""
    wt = WorldTime(broadcast_cfg())
    chs = [
        {"kind": "season", "old": 0, "new": 1},
        {"kind": "period", "old": 4, "new": 0},
    ]
    assert wt.maybe_broadcast(chs, seen={"season_idx": 1}) == ["🌅 晨"]
    # ctx 传 seen 同效
    assert wt.maybe_broadcast(chs, {"seen": {"season_idx": 1}}) == ["🌅 晨"]
    # 全部已播 → 空（无新变化可播）
    assert wt.maybe_broadcast(chs, seen={"season_idx": 1, "period_idx": 0}) == []


def test_broadcast_enabled_no_changes_returns_empty():
    """开启但无变化 / 非列表 → 返回 []。"""
    wt = WorldTime(broadcast_cfg())
    assert wt.maybe_broadcast([]) == []
    assert wt.maybe_broadcast(None) == []


def test_broadcast_weather_without_display_fields_documents_boundary():
    """【工程补白】天气值解析属 IF04/IF08（批次2）：未挂 name/emoji → 占位符留空（不崩溃）。"""
    wt = WorldTime(broadcast_cfg())
    out = wt.maybe_broadcast([{"kind": "weather", "old": 0, "new": 5}])
    assert out == [" "]  # 缺省模板 `{emoji} {name}` → 两个占位符均空；文案待调用方补齐

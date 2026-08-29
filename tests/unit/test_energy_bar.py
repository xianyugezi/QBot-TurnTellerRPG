"""调合能量条引擎单测（M8 批4·路2 · qbot_rpg/core/energy_bar.py）——细化 TC-21~TC-30 引擎可承载部分。

文件：tests/unit/test_energy_bar.py
创建：2026-08-29
作者：Hermes 子agent-2（路2）
功能：EnergyBar 调合能量条引擎单测——默认关直通/上限随等级 7 档/每炼金扣 1 格/合成豁免
      （引擎不扣 n=0）/能量不足提示+保底/懒计算补格与上限封顶/安全区 2 倍速/存档同步。

依据：docs/细化/细化_2c4f_投料触媒与能量条.md 三（ENG-01~10）+ 五（TC-21~30）+
      docs/m8_contract_核心机制.md 三（ENG-01~10）+ 批0 content/test_demo/settings.json
      alchemy 段（energy_enabled=false/energy_max 7 档/energy_regen_sec=1800/
      energy_regen_sec_safe=900）。

覆盖矩阵（每条正例 + 负例，断言精确数值/文本，now 确定性注入）：
  TC-21 见习 5/5（ENG-02/03）
  TC-22 七档上限逐档（正式 8/精通 10/专家 12/大师 15/宗师 18/王 20）+ 越界钳制 + 配置注入覆盖
  TC-23 /炼金 开会话扣 1 格（ENG-04，5/5 → 4/5）
  TC-24 /深度炼金 扣 1 格（大师 15/15 → 14/15，ENG-04 同口径）
  TC-25 合成豁免（ENG-07：引擎不扣——n=0 无操作，能量状态不变）
  TC-26 能量 0/10 不足提示 + /合成 保底（ENG-04/08：拒绝不扣 + message 定稿模板）
  TC-27 懒计算 1800s→+1 / 3600s→+2 / 上限封顶 / 碎片不补（ENG-05 工程补白 E-2）
  TC-28 安全区 900s 2 倍速 / 离开恢复 1800 基准 / safe=True 参数覆盖（ENG-06）
  TC-29 默认关直通：不扣能量、无能量不足模板、不写存档（ENG-01/ENG-10 守卫直通）
  TC-30 存档同步 current + energy_last_regen_ts（ENG-09）+ 首锚点缺失默认满格（E-3）

测试风格对齐 tests/unit/test_quality.py：纯 pytest、零 NoneBot、断言具体数值/文本；
now 统一用整秒时间戳注入确定性。
"""

from __future__ import annotations

from qbot_rpg.core.energy_bar import EnergyBar

T0 = 1_700_000_000  # 测试基准时刻（UTC 秒）

# 批0 settings 同款 7 档上限（TC-21/22 口径）
DEFAULT_MAX = {
    "见习": 5,
    "正式": 8,
    "精通": 10,
    "专家": 12,
    "大师": 15,
    "宗师": 18,
    "王": 20,
}


def _settings(**kw) -> dict:
    """开启能量条 + 批0 settings 同款配置（可覆盖）。"""
    alch = {
        "energy_enabled": True,
        "energy_max": dict(DEFAULT_MAX),
        "energy_regen_sec": 1800,
        "energy_regen_sec_safe": 900,
        "safe_scenes": ["town", "城镇", "休整"],
    }
    alch.update(kw)
    return {"alchemy": alch}


def _player(
    tier_level: int = 0,
    *,
    energy_current=None,
    last_ts=None,
    scene=None,
    job_id: str = "alchemy",
) -> dict:
    """玩家状态 dict：proficiency 档位 level + persistent_state 能量桶 + 可选场景标记。"""
    p: dict = {
        "job_id": job_id,
        "proficiency": {job_id: {"level": tier_level}},
        "persistent_state": {},
    }
    if energy_current is not None:
        p["persistent_state"]["energy_current"] = energy_current
    if last_ts is not None:
        p["persistent_state"]["energy_last_regen_ts"] = last_ts
    if scene is not None:
        p["scene"] = scene
    return p


# ---------------------------------------------------------------------------
# TC-21/22 上限随职业等级 7 档（ENG-02/03）
# ---------------------------------------------------------------------------
def test_tc21_apprentice_max_five() -> None:
    """TC-21 正例：见习（tier 0）开启能量条 → 上限 5/5（L416 见习=5）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=5, last_ts=T0)
    assert bar.max_for_tier(0) == 5
    assert bar.lazy_regen(p, now=T0)["current"] == 5
    assert bar.lazy_regen(p, now=T0)["max"] == 5


def test_tc22_seven_tiers_escalate() -> None:
    """TC-22 正例：王 20/20；每级一档（正式 8/精通 10/专家 12/大师 15/宗师 18）。"""
    bar = EnergyBar(_settings())
    expect = [5, 8, 10, 12, 15, 18, 20]
    for tier, want in enumerate(expect):
        assert bar.max_for_tier(tier) == want, f"tier {tier} 应 {want}"
    # 王玩家 20/20（tier=6）
    p = _player(tier_level=6, energy_current=20, last_ts=T0)
    r = bar.lazy_regen(p, now=T0)
    assert r["max"] == 20 and r["current"] == 20


def test_tc22_tier_clamp_and_config_override() -> None:
    """TC-22 负例/工程补白 E-8：档位索引越界钳制末档；自定义 energy_max 覆盖生效。"""
    bar = EnergyBar(_settings())
    assert bar.max_for_tier(7) == 20  # 越界 → 钳制王档
    assert bar.max_for_tier(-1) == 5  # 负 → 钳制见习档
    # 内容包覆盖：只给 7 档里的部分（缺键回落默认模板）
    custom = EnergyBar(_settings(energy_max={"见习": 3, "王": 25}))
    assert custom.max_for_tier(0) == 3
    assert custom.max_for_tier(1) == 8  # 正式缺键 → 回落默认模板
    assert custom.max_for_tier(6) == 25


# ---------------------------------------------------------------------------
# TC-23/24 每炼金消耗 1 格（ENG-04）
# ---------------------------------------------------------------------------
def test_tc23_craft_session_consumes_one() -> None:
    """TC-23 正例：/炼金 开会话 → 能量 -1（5/5 → 4/5）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=5, last_ts=T0)
    r = bar.consume(p, 1, now=T0)
    assert r["ok"] is True
    assert r["current"] == 4 and r["max"] == 5
    assert r["consumed"] == 1
    assert p["persistent_state"]["energy_current"] == 4  # 存档同步（TC-30）


def test_tc24_deep_craft_consumes_one() -> None:
    """TC-24 正例：大师 /深度炼金 → 能量 -1（15/15 → 14/15，ENG-04 同口径）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=4, energy_current=15, last_ts=T0)  # 大师=15
    r = bar.consume(p, 1, now=T0)
    assert r["ok"] is True and r["current"] == 14 and r["max"] == 15


def test_tc23_negative_and_multi_consume() -> None:
    """TC-23 负例/边界：批量 N 次扣 N 格（BATCH-03）；负消耗按 0 无操作（防御）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=5, last_ts=T0)
    r = bar.consume(p, 3, now=T0)
    assert r["ok"] is True and r["current"] == 2 and r["consumed"] == 3  # BATCH-03 按次
    r0 = bar.consume(p, -5, now=T0)
    assert r0["ok"] is True and r0["current"] == 2 and r0["consumed"] == 0


# ---------------------------------------------------------------------------
# TC-25 合成豁免（ENG-07：引擎不扣）
# ---------------------------------------------------------------------------
def test_tc25_synthesis_bypass_no_deduct() -> None:
    """TC-25 正例：合成不消耗能量——consume(n=0) 只补格不扣，能量状态不变（保底通道永可用）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=4, energy_current=2, last_ts=T0)
    r = bar.consume(p, 0, now=T0)
    assert r["ok"] is True
    assert r["current"] == 2 and r["consumed"] == 0
    assert p["persistent_state"]["energy_current"] == 2  # 不扣


# ---------------------------------------------------------------------------
# TC-26 能量不足提示 + 保底（ENG-04/08）
# ---------------------------------------------------------------------------
def test_tc26_insufficient_message_and_no_deduct() -> None:
    """TC-26 正例：能量 0/10 发 /炼金 → 拒绝 + 定稿模板 + 不扣（原子）；随后 /合成 仍可用。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=3, energy_current=0, last_ts=T0)  # 专家=12
    r = bar.consume(p, 1, now=T0)
    assert r["ok"] is False
    assert r["reason"] == "energy_insufficient"
    assert r["current"] == 0 and r["max"] == 12
    assert r["message"] == "能量 0/12，等 30 分钟回 1 格，或 /合成 保底"
    assert p["persistent_state"]["energy_current"] == 0  # 原子：不扣
    # 保底：/合成 走 consume(n=0) 正常执行
    syn = bar.consume(p, 0, now=T0)
    assert syn["ok"] is True


def test_tc26_partial_insufficient() -> None:
    """TC-26 负例补充：批量扣 N 格时余额不足也拒绝（如 8 格 /炼金 *10，TC-13 原子口径）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=2, energy_current=8, last_ts=T0)  # 精通=10
    r = bar.consume(p, 10, now=T0)
    assert r["ok"] is False and r["reason"] == "energy_insufficient"
    assert r["current"] == 8  # 不扣


# ---------------------------------------------------------------------------
# TC-27 懒计算 30 分钟回 1 格（ENG-05，工程补白 E-2/E-3/E-4）
# ---------------------------------------------------------------------------
def test_tc27_lazy_regen_1800s_one_bar() -> None:
    """TC-27 正例：1800s → +1 格；锚点覆写为 now（后续不重复计）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=4, last_ts=T0)
    r = bar.lazy_regen(p, now=T0 + 1800)
    assert r["regen_gained"] == 1 and r["current"] == 5 and r["max"] == 5
    assert p["persistent_state"]["energy_last_regen_ts"] == T0 + 1800  # 锚点同步
    # 再查一次同刻：不再重复补格
    r2 = bar.lazy_regen(p, now=T0 + 1800)
    assert r2["regen_gained"] == 0 and r2["current"] == 5


def test_tc27_lazy_regen_3600s_two_bars_capped() -> None:
    """TC-27 正例：3600s → +2 格；上限封顶（4/5 +2 → 5/5，capped=True）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=4, last_ts=T0)
    r = bar.lazy_regen(p, now=T0 + 3600)
    assert r["regen_gained"] == 2
    assert r["current"] == 5 and r["capped"] is True  # 有补格被上限吃掉
    assert p["persistent_state"]["energy_current"] == 5


def test_tc27_partial_elapsed_no_gain() -> None:
    """TC-27 负例：不足一个间隔（900s）→ 0 格（碎片化友好，向下取整，工程补白 E-2）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=4, last_ts=T0)
    r = bar.lazy_regen(p, now=T0 + 900)
    assert r["regen_gained"] == 0 and r["current"] == 4


def test_tc27_first_anchor_missing_defaults_full() -> None:
    """TC-27 工程补白 E-3：新玩家首锚点缺失 → 默认满格、锚点=now（不凭空补格）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0)  # persistent_state 空
    r = bar.lazy_regen(p, now=T0)
    assert r["current"] == 5 and r["max"] == 5  # 见习默认满格 5/5
    assert p["persistent_state"]["energy_last_regen_ts"] == T0
    # 只缺锚点（旧存档有 current 无 ts）→ current 保留、锚点=now
    p2 = _player(tier_level=0, energy_current=3)
    r2 = bar.lazy_regen(p2, now=T0)
    assert r2["current"] == 3 and p2["persistent_state"]["energy_last_regen_ts"] == T0


def test_tc27_clock_rewind_no_regen() -> None:
    """TC-27 工程补白 E-4：时钟回拨（now < last_ts）→ 不补格、不覆写锚点。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=4, last_ts=T0 + 5000)
    r = bar.lazy_regen(p, now=T0)
    assert r["regen_gained"] == 0 and r["current"] == 4
    assert p["persistent_state"]["energy_last_regen_ts"] == T0 + 5000  # 锚点未倒退


# ---------------------------------------------------------------------------
# TC-28 安全区 2 倍速（ENG-06，工程补白 E-5）
# ---------------------------------------------------------------------------
def test_tc28_safe_zone_900s_two_x_speed() -> None:
    """TC-28 正例：安全区/休整态 15 分钟（900s）→ +1 格（2 倍速）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=4, last_ts=T0, scene="town")
    r = bar.lazy_regen(p, now=T0 + 900)
    assert r["regen_gained"] == 1 and r["current"] == 5 and r["safe"] is True
    assert r["interval"] == 900


def test_tc28_out_of_safe_zone_back_to_1800() -> None:
    """TC-28 负例：离开安全区恢复 1800 基准——同 900s 无场景标记 → +0 格。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=4, last_ts=T0)  # 无场景标记（缺省 False）
    r = bar.lazy_regen(p, now=T0 + 900)
    assert r["safe"] is False and r["regen_gained"] == 0 and r["current"] == 4
    assert r["interval"] == 1800


def test_tc28_safe_param_override_and_ctx() -> None:
    """TC-28 工程补白：safe=True 参数显式覆盖 + is_safe_zone(ctx) 判定口径。"""
    bar = EnergyBar(_settings())
    # safe=True 参数（无场景标记也按 900s 补格）
    p = _player(tier_level=0, energy_current=4, last_ts=T0)
    r = bar.lazy_regen(p, now=T0 + 900, safe=True)
    assert r["regen_gained"] == 1 and r["safe"] is True
    # is_safe_zone：ctx["scene"] 与 ctx["player"]["scene"] 两种取景口径
    assert bar.is_safe_zone({"scene": "休整"}) is True
    assert bar.is_safe_zone({"player": {"scene": "城镇"}}) is True
    assert bar.is_safe_zone({"scene": "野外"}) is False
    assert bar.is_safe_zone({"scene": {"safe": True}}) is True  # Mapping 场景标记
    assert bar.is_safe_zone({}) is False  # 缺省 False


# ---------------------------------------------------------------------------
# TC-29 默认关直通（ENG-01/ENG-10）
# ---------------------------------------------------------------------------
def test_tc29_default_off_bypass() -> None:
    """TC-29 正例：构造器无 settings（默认关）→ 直通：不扣、无能量不足模板、不写存档。"""
    bar = EnergyBar()  # 无 settings → energy_enabled=false（ENG-01 默认关）
    assert bar.enabled() is False
    p = _player(tier_level=0)  # 空 persistent_state（无能量字段）
    r = bar.consume(p, 5, now=T0)  # 即使能量不足也直通
    assert r["ok"] is True
    assert r["bypassed"] is True
    assert r["current"] == 5 and r["max"] == 5
    assert "message" not in r  # 无能量不足模板
    assert p["persistent_state"] == {}  # 不写存档（不干预）


def test_tc29_explicit_disabled_settings() -> None:
    """TC-29 负例/配置：settings 显式 energy_enabled=false 同直通；mode=simple 无能量条同口径。"""
    bar = EnergyBar(_settings(energy_enabled=False))
    assert bar.enabled() is False
    p = _player(tier_level=3, energy_current=0, last_ts=T0)
    r = bar.consume(p, 1, now=T0)
    assert r["ok"] is True and r["bypassed"] is True


def test_tc29_consume_returns_current_max_on_bypass() -> None:
    """TC-29 补充：直通返回 {current, max}（供面板「无能量上限显示」外的展示兜底）。"""
    bar = EnergyBar()
    p = _player(tier_level=2, energy_current=7, last_ts=T0)
    r = bar.consume(p, 1, now=T0)
    assert r["current"] == 7 and r["max"] == 10 and r["ok"] is True


# ---------------------------------------------------------------------------
# TC-30 存档同步（ENG-09）
# ---------------------------------------------------------------------------
def test_tc30_sync_after_anchor() -> None:
    """TC-30 正例：结算后 sync_after 覆写 energy_last_regen_ts = now（懒计算不重计）。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=4, last_ts=T0)
    # 先消耗：能量 -1 且 current 落档
    bar.consume(p, 1, now=T0)
    assert p["persistent_state"]["energy_current"] == 3
    # 结算后同步锚点
    r = bar.sync_after(p, now=T0 + 60)
    assert r["ok"] is True
    assert p["persistent_state"]["energy_last_regen_ts"] == T0 + 60
    # 热重载口径：新引擎按存档值+懒计算恢复，不重算不丢（TC-30）
    bar2 = EnergyBar(_settings())
    r2 = bar2.lazy_regen(p, now=T0 + 60)
    assert r2["current"] == 3  # 存档值恢复，不因重载回满/清零


def test_tc30_current_of_query_regen_and_persist() -> None:
    """TC-30 补充：current_of 查询即补格（ENG-05 查询口径）并回写存档。"""
    bar = EnergyBar(_settings())
    p = _player(tier_level=0, energy_current=4, last_ts=T0)
    cur = bar.current_of(p, now=T0 + 1800)
    assert cur == 5  # 查询补 1 格
    assert p["persistent_state"]["energy_current"] == 5

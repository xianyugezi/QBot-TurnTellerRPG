"""战斗规则配置装配层（settings["battle"] 段读取；批④ 背击闭环管道）。

归属：增补 v1 实装批④（2026-09-11）——对齐 ctb_config.resolve_ctb_settings 模式：
内容包 settings.json 的段式配置 → 引擎 BattleEngine 构造 config 覆盖。

职责：
  - resolve_battle_settings(settings)  读取 settings["battle"] 段**白名单键**
    （只透传已知战斗配置键，防误键污染引擎配置；缺省/坏值 → 跳过该键不覆盖）。

白名单键（键值语义见 qbot_rpg/core/battle.py `_BATTLE_DEFAULT_CONFIG`）：
  - backstab_bonus: float ≥ 0 —— 背击加成（B5 背击闭环；缺省 0.10、0=关）。
    非数值 / 布尔 / 负数 → 忽略（回落引擎默认，绝不因配置失误关掉或放大机制）。
  - crit_cond_low_hp: (0, 1] —— 条件型会心「逆境」阈值（E20 批⑤；缺省 0.3）。
    非数值 / 布尔 / 越界 → 忽略（回落默认）。
  - stun_* / roar_* 批⑦A（2026-09-12）气绝 KO 与咆哮参数；各自区间校验，
    越界/坏值 → 忽略（回落引擎默认）。

调用点（与 ctb 段同源原则——实机开战 / 木桩战一致）：
  - qbot_rpg/commands/battle_launch_commands.py（launch_pve_battle）
  - qbot_rpg/commands/dummy_commands.py（木桩战）

硬约束（对齐仓库规范）：
  - 零 NoneBot import；确定性；防御性（非法输入 fail-safe 不抛错）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping

__all__ = [
    "BATTLE_SETTINGS_KEYS",
    "resolve_battle_settings",
]

_logger = logging.getLogger(__name__)

#: settings["battle"] 段可透传键白名单（新增键须同步 battle.py 默认表 + 本表）。
BATTLE_SETTINGS_KEYS = (
    "backstab_bonus", "crit_cond_low_hp",
    # 批⑦A 气绝 KO（怪猎采纳 #3）：打击×正方位积累 → 满值倒地
    "stun_enabled", "stun_base_threshold", "stun_escalation",
    "stun_decay_per_action", "stun_ko_window", "stun_ko_skip",
    "stun_hint_at", "stun_side_mult", "stun_back_mult",
    # 批⑦A 咆哮（怪猎采纳 #2）：打断连势 + 行动条后推；耳栓反制
    "roar_light_delay", "roar_heavy_delay", "roar_combo_clear",
    # 批⑦B 怒·三态 / 疲劳（怪猎采纳 #4/#5）：敌侧双轴
    "rage_per_damage", "rage_cool_actions", "stamina_max",
    "stamina_drain_blunt", "stamina_regen_per_action",
    "enrage_damage_mult", "enrage_recovery_mult",
    "fatigue_recovery_mult", "fatigue_stagger_chance",
)


def resolve_battle_settings(settings: Any = None) -> Dict[str, Any]:
    """读取 settings 的 "battle" 段（白名单键；缺省/非法 → 空 dict，绝不抛错）。

    :param settings: 全量 settings（Mapping / 对象 / None）
    :return: 引擎 config 覆盖段（只含已通过校验的白名单键）
    """
    out: Dict[str, Any] = {}
    try:
        seg: Any = None
        if isinstance(settings, Mapping):
            seg = settings.get("battle")
        elif settings is not None:
            seg = getattr(settings, "battle", None)
        if not isinstance(seg, Mapping):
            return out
        raw = seg.get("backstab_bonus")
        if (
            isinstance(raw, (int, float))
            and not isinstance(raw, bool)
            and float(raw) >= 0.0
        ):
            out["backstab_bonus"] = float(raw)
        raw_lh = seg.get("crit_cond_low_hp")
        if (
            isinstance(raw_lh, (int, float))
            and not isinstance(raw_lh, bool)
            and 0.0 < float(raw_lh) <= 1.0
        ):
            out["crit_cond_low_hp"] = float(raw_lh)
        # ---- 批⑦A：气绝 KO / 咆哮参数（同一白名单口径：坏值忽略，回落引擎默认）----
        def _num(key: str, lo: float, hi: float, *, excl_lo: bool = False) -> None:
            v = seg.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                fv = float(v)
                ok = (fv > lo if excl_lo else fv >= lo) and fv <= hi
                if ok:
                    out[key] = fv

        def _int(key: str, lo: int, hi: int) -> None:
            v = seg.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                iv = int(v)
                if lo <= iv <= hi and float(iv) == float(v):
                    out[key] = iv

        def _bool(key: str) -> None:
            v = seg.get(key)
            if isinstance(v, bool):
                out[key] = v

        _bool("stun_enabled")
        _num("stun_base_threshold", 0.0, 1e9, excl_lo=True)
        _num("stun_escalation", 1.0, 100.0)
        _num("stun_decay_per_action", 0.0, 1.0)
        _int("stun_ko_window", 0, 20)
        _bool("stun_ko_skip")
        _num("stun_hint_at", 0.0, 1.0)
        _num("stun_side_mult", 0.0, 10.0)
        _num("stun_back_mult", 0.0, 10.0)
        _num("roar_light_delay", 0.0, 100000.0)
        _num("roar_heavy_delay", 0.0, 100000.0)
        _bool("roar_combo_clear")
        # ---- 批⑦B：怒·三态 / 疲劳参数（同一白名单口径）----
        _num("rage_per_damage", 0.0, 100.0)
        _int("rage_cool_actions", 1, 1000)
        _num("stamina_max", 1.0, 1e9)
        _num("stamina_drain_blunt", 0.0, 1e6)
        _num("stamina_regen_per_action", 0.0, 1e6)
        _num("enrage_damage_mult", 0.05, 100.0)
        _num("enrage_recovery_mult", 0.05, 100.0)
        _num("fatigue_recovery_mult", 0.05, 100.0)
        _num("fatigue_stagger_chance", 0.0, 1.0)
        return out
    except Exception:  # pragma: no cover - 兜底不崩
        _logger.exception("resolve_battle_settings 失败，跳过 battle 段")
        return out

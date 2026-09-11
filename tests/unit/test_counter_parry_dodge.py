"""防反/闪反双子机制单测（2026-09-09 用户拍板标签制：不 roll——怪行动可反标签+玩家姿态）。

- 防反：怪行动带「可防反」+ 玩家防反姿态（守势 parry）→ 完全免伤 + 自动反击
- 闪反：怪行动带「可闪反」+ 玩家闪反姿态（回环/腾空 dodge）位移出范围 → 免伤（天然）+ 反击
- 失败：行动无标签 → 受伤（姿态减伤照常）+ 无反击

窗口口径（2026-09-11 增补 v1 §一 **实装为时间制**）：
  姿态窗口 = [写入时刻, 写入时刻 + 行动时间)（行动条；半开区间）——「行动时间」
  取技能 def 的 `action_time`（缺省 = 规则 `default_action_time`，默认 400）。
  到期自然结束（无补偿）；**持有者提前再次行动不提前关闭窗口**（纯时间口径）。
  原 R10「至持有者再次行动止」计数口径（`_stance_owner_seq`）已退役。

  触发几何：窗口命中 = 敌方行动的时刻落在施放后的 0~400 行动条内。怪与玩家
  同拍（速度比整除）时窗口恒空；怪不同拍时（本文件用 spd=8 → 怪 +250 出手）
  自然命中。测试分两层：直写窗口（边界精确）+ 端到端（spd=8 自然触发）。

CTB 语义（2026-09-10 迁移保留）：怪侧行动经单次结算入口 `do_action("enemy", ...)`
显式驱动；玩家侧走 `player_act`（调度器自动推进 NPC 连锁）。
"""
from pathlib import Path


from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.monster_ai import MonsterAI


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _pack(action_time=None):
    """加载 veinborn 包并构建 defs/combo 引擎。

    :param action_time: 测试专用——统一改写全部反制技的 `action_time`（窗宽实验：
        传具体值统一覆盖；None → 保持内容包原值 400）。
    """
    pack, _ = build_pack(Path("content/veinborn"))
    raw = pack.registry.modules_raw
    if action_time is not None:
        for _sk in raw["skills"]:
            if isinstance(_sk, dict) and _sk.get("counter_type"):
                _sk["action_time"] = action_time
    skills = {s["id"]: s for s in raw["skills"]}
    actions = {a["id"]: a for a in raw["action"]}
    chains = {c["id"]: c for c in raw.get("skill_chains", [])}
    all_defs = {**skills, **actions}
    for tbl in ("effects", "marks", "statuses"):
        for e in raw.get(tbl, []):
            all_defs.setdefault(e["id"], e)
    ce = ComboEngine(
        defs={**all_defs, **chains},
        resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
    )
    return raw, all_defs, ce


_PLAYER = {
    "max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 10, "mag": 10,
    "proficiency": {"alchemy": {"level": 4, "exp": 0}},
}


def _enemy(raw, eid, *, spd=None):
    """构造敌人战斗侧数值。

    CTB 迁移（2026-09-10）：`spd` 不再是「排序用的装饰字段」，而是**行动条推进的
    唯一分母**——`next_ready` 增量 = `recovery * speed_reference / max(spd, min_speed)`。
    故 `spd=0` 在 CTB 下等价于「该单位永不 ready」（cost 被 clamp 到 min_speed 后
    仍极大），旧回合制里「spd=0 表示怪不抢先手」的用法不再成立。

    :param spd: 显式指定速度；None → 取敌人 def 的 `stats.agi`（CTB 下怪也需要能行动）
    """
    et = next(e for e in raw["enemies"] if e["id"] == eid)
    st = et.get("stats") or {}
    _spd = int(st.get("agi", 10) or 10) if spd is None else int(spd)
    return et, {
        "id": et["id"], "hp": 3000, "max_hp": 3000, "mp": 0,
        "atk": int(st.get("str", 10)), "dfn": int(st.get("con", 10)),
        "mag": 0, "spd": _spd, "foc": 0, "lck": 0,
        "con": int(st.get("con", 10)), "agi": 0, "name": et["name"],
    }


def _fresh(raw, all_defs, ce, *, spd=None):
    et, mob = _enemy(raw, "ridge_cub", spd=spd)
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                   rng=_QR([0.1] * 800))
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7)
    eng._enemy_ai = ai
    return eng


def _set_window(eng, cast_time=None, dur=400, ctype="parry", skill="sw_guard_counter"):
    """测试专用：直写姿态窗口（精确控制 [cast_time, cast_time+dur)）。

    cast_time=None → 对齐到当前 battle_time（模拟「敌方攻击恰在窗口内」）。
    """
    eng._snap["counter_stance"] = {
        "type": ctype, "skill": skill,
        "cast_time": float(eng.battle_time if cast_time is None else cast_time),
        "action_time": float(dur),
    }


def _fx_types(outcomes):
    """TurnReport.outcomes → 各 outcome 的 side_effects type 列表。"""
    out = []
    for o in (getattr(outcomes, "outcomes", None) or []):
        for x in (getattr(o, "side_effects", ()) or ()):
            out.append(str(x.get("type")))
    return out


def _fx_of(outcome):
    """单个 ActionOutcome → side_effects type 列表。"""
    return [str(x.get("type")) for x in (getattr(outcome, "side_effects", ()) or ())]


def _parryable_action(raw):
    act = next((a for a in raw["action"] if "可防反" in (a.get("tags") or [])), None)
    assert act is not None, "内容层应有可防反行动"
    return act


# ---------------------------------------------------------------------------
# 一、窗口写入：时间字段（cast_time + action_time）
# ---------------------------------------------------------------------------


def test_stance_written_with_time_window_fields():
    """施放守势 → snap.counter_stance 记「写入时刻 + 时长」（时间窗口口径）。

    窗宽实验（action_time=5000）让窗口横跨整段自动推进 → 窗口数据可直接观察：
    cast_time=施放时刻的 battle_time（1000），action_time=技能 def 值（5000）。
    """
    raw, all_defs, ce = _pack(action_time=5000)
    eng = _fresh(raw, all_defs, ce)
    eng.do_action("player", {"type": "skill", "skill_id": "sw_guard"})
    st = dict(eng._snap.get("counter_stance") or {})
    assert st.get("type") == "parry" and st.get("skill") == "sw_guard_counter", \
        f"守势施放应写入防反姿态，got {st}"
    assert float(st.get("cast_time", -1)) == 1000.0, f"cast_time 应为施放时刻，got {st}"
    assert float(st.get("action_time", -1)) == 5000.0, f"action_time 应取技能 def，got {st}"
    # 闪反（dodge）侧同构：回环施放 → 姿态 type=dodge / skill=回环反击
    eng2 = _fresh(raw, all_defs, ce)
    eng2.do_action("player", {"type": "skill", "skill_id": "sw_circle"})
    st2 = dict(eng2._snap.get("counter_stance") or {})
    assert st2.get("type") == "dodge" and st2.get("skill") == "sw_circle_counter", \
        f"回环施放应写入闪反姿态，got {st2}"
    assert float(st2.get("cast_time", -1)) == 1000.0, f"dodge cast_time 异常，got {st2}"


def test_content_action_time_is_400():
    """内容层：veinborn 反制技 action_time 标配 400（增补 v1 §一标准示例）。"""
    raw, _, _ = _pack()
    for sk in raw["skills"]:
        if isinstance(sk, dict) and sk.get("counter_type"):
            assert sk.get("action_time") == 400, f"{sk.get('id')} 缺 action_time=400"


# ---------------------------------------------------------------------------
# 二、防反：命中窗口 → 完全免伤 + 反击
# ---------------------------------------------------------------------------


def test_parry_guard_fully_negates_and_counter():
    """守势挡可防反行动（窗口内）→ 完全免伤（hp 不减）+ parry_counter 反击伤害。

    窗口口径（时间制）：直写窗口对齐当前时刻（模拟敌方攻击恰在窗口内）——
    与旧 R10「对齐 action_seq」等价，但判据是 battle_time。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    eng.do_action("player", {"type": "skill", "skill_id": "sw_guard"})
    hp_before = int(eng._snap["player"]["hp"])
    _set_window(eng)  # cast_time=当前时刻 → 敌方下一步行动恰在窗口内
    act = _parryable_action(raw)
    out = eng.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = _fx_of(out)
    assert "parry" in fx and "parry_counter" in fx, f"防反应触发 parry/counter，got {fx}"
    assert out.target_hp == hp_before, \
        f"防反成功应完全免伤（hp {hp_before}），got {out.target_hp}"
    cd = next((int(x.get("damage") or 0)
               for x in (getattr(out, "side_effects", ()) or ())
               if x.get("type") == "parry_counter"), 0)
    assert cd > 0, f"防反反击应造成伤害，got {cd}"


def test_guard_vs_non_parryable_action_takes_damage():
    """守势挡不可防反行动（窗口内）→ 受伤（减伤照常）+ 无 parry 事件。"""
    raw, all_defs, ce = _pack()
    act = next((a for a in raw["action"]
                if a.get("intent") == "伤害" and "可防反" not in (a.get("tags") or [])), None)
    assert act is not None, "内容层应有不可防反的伤害行动"
    eng = _fresh(raw, all_defs, ce)
    eng.do_action("player", {"type": "skill", "skill_id": "sw_guard"})
    _set_window(eng)
    out = eng.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = _fx_of(out)
    assert "parry" not in fx, f"不可防反行动不应触发防反，got {fx}"
    assert out.target_hp < 900, "不可防反行动应造成伤害"


# ---------------------------------------------------------------------------
# 三、窗口边界与到期（时间制：半开区间 [cast, cast+dur)）
# ---------------------------------------------------------------------------


def test_window_boundary_half_open():
    """边界：cast_time = now-399（内）触发；= now-400（外）不触发（半开区间）。"""
    raw, all_defs, ce = _pack()
    act = _parryable_action(raw)

    eng_in = _fresh(raw, all_defs, ce)
    eng_in.do_action("player", {"type": "skill", "skill_id": "sw_guard"})
    hp_in = int(eng_in._snap["player"]["hp"])
    _set_window(eng_in, cast_time=eng_in.battle_time - 399)
    out_in = eng_in.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    assert "parry" in _fx_of(out_in), "399 < 400 应在窗口内"
    assert out_in.target_hp == hp_in, "窗口内应完全免伤"

    eng_out = _fresh(raw, all_defs, ce)
    eng_out.do_action("player", {"type": "skill", "skill_id": "sw_guard"})
    _set_window(eng_out, cast_time=eng_out.battle_time - 400)
    out_out = eng_out.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    assert "parry" not in _fx_of(out_out), "400 恰在窗口外（半开区间）"
    assert out_out.target_hp < 900, "窗口外应照常受伤"


def test_window_expired_and_cleaned():
    """到期自然结束：远离窗口的敌方行动不触发，且过期窗口被清理（快照不残留）。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    eng.do_action("player", {"type": "skill", "skill_id": "sw_guard"})
    # 默认 400 窗口 + 默认 spd=5 怪：自动推进后（2000）窗口早已过期并被清理
    assert eng._snap.get("counter_stance") is None or \
        eng._snap["counter_stance"].get("cast_time") is not None, "窗口数据形态异常"
    _set_window(eng, cast_time=eng.battle_time - 100000)  # 人为写入已过期窗口
    act = _parryable_action(raw)
    out = eng.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    assert "parry" not in _fx_of(out), "过期窗口不应触发"
    assert out.target_hp < 900, "过期后应照常受伤"


# ---------------------------------------------------------------------------
# 四、端到端：自然节奏下的触发 / 不触发（spd 决定窗口几何）
# ---------------------------------------------------------------------------


def test_e2e_trigger_when_enemy_action_within_window():
    """端到端（spd=8）：怪在 +250 行动条出手 → 落在 [1000,1400) 窗口内 → 防反触发。

    几何：玩家普攻 1000 行动条/次行动；spd=8 怪每 1250 行动条行动一次 → 首次
    施放后怪的下次行动在 +250 处 → 窗口命中。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce, spd=8)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    fx = _fx_types(tr)
    assert "parry" in fx and "parry_counter" in fx, f"端到端防反应触发，got {fx}"
    assert tr.player == 900, f"防反成功应完全免伤，got {tr.player}"


def test_e2e_no_trigger_when_enemy_action_outside_window():
    """端到端（spd=5 默认）：怪在 +1000 行动条出手 → 窗口（+400）已过 → 不触发。

    几何：spd=5 怪每 2000 行动条行动一次，与玩家 1000 拍同相 → 窗口恒空——
    这是「行动时间」的取舍一面（窗口越长覆盖率越高；数值可调）。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)  # spd=None → 取怪 agi=5
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    fx = _fx_types(tr)
    assert "parry" not in fx and "parry_counter" not in fx, \
        f"窗口外的怪行动不应触发防反，got {fx}"
    assert tr.player < 900, "窗口未命中应照常受伤"


def test_fallback_default_action_time():
    """行动时间缺省链：技能未给有效 action_time（0/缺失）→ 规则 default_action_time（400）。

    spd=8 场景（+250 命中 400 窗）：若回退失败（窗宽 0 → 恒空）则不会触发。
    """
    raw, all_defs, ce = _pack(action_time=0)  # 0 = 非法 → 应回退默认 400
    eng = _fresh(raw, all_defs, ce, spd=8)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    fx = _fx_types(tr)
    assert "parry" in fx, f"action_time 非法应回退 default_action_time=400，got {fx}"


# ---------------------------------------------------------------------------
# 五、闪反（dodge）：位移出范围 → 未命中 + dodge_counter
# ---------------------------------------------------------------------------


def test_dodge_circle_position_miss_counter():
    """回环（闪反姿态）→ 侧移出扑咬方位 → 未命中（免伤）+ dodge_counter 反击。

    窗口口径（时间制）：直写窗口对齐当前时刻，再直驱怪行动（旧 R10 对齐
    action_seq 的等价改造）；侧移用回环施放产物 + 显式置 side 保证确定性。
    """
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    act = next((a for a in raw["action"] if "可闪反" in (a.get("tags") or [])), None)
    assert act is not None, "内容层应有可闪反行动"
    # 真实施放回环 → 侧移产物（默认窗在自动推进后到期清理——直写窗口再驱动）
    eng.do_action("player", {"type": "skill", "skill_id": "sw_circle"})
    pos = eng._snap.setdefault("combat_position", {}).setdefault("player", {})
    pos["side"] = "right"                      # 位移出正面（回环侧移产物）
    _set_window(eng, ctype="dodge", skill="sw_circle_counter")  # 对齐当前时刻
    out = eng.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = _fx_of(out)
    assert "position_miss" in fx, f"回环侧移后扑咬应未命中，got {fx}"
    assert out.target_hp == 900, f"闪反成功应免伤，got {out.target_hp}"
    cd = next((int(x.get("damage") or 0)
               for x in (getattr(out, "side_effects", ()) or ())
               if x.get("type") == "dodge_counter"), 0)
    assert cd > 0, f"闪反反击应造成伤害，got {cd}"


def test_e2e_dodge_natural_trigger():
    """端到端（spd=8）：回环在 +250 处自然命中窗口 → position_miss + dodge_counter。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce, spd=8)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_circle"})
    fx = _fx_types(tr)
    assert "dodge_counter" in fx, f"端到端闪反应触发，got {fx}"
    assert tr.player == 900, f"闪反应免伤，got {tr.player}"


# ---------------------------------------------------------------------------
# 六、窗口与持有者行动解耦（纯时间口径）
# ---------------------------------------------------------------------------


def test_window_survives_holder_next_action():
    """持有者提前再次行动**不**提前关闭窗口（增补 v1 §一推定：以时间到期为准）。

    窗宽实验（5000）：施放后跨越持有者再行动 + 敌方后手，窗口仍在 → 后半段
    敌方行动仍触发防反（旧 R10 口径下此处必然过期）。
    """
    raw, all_defs, ce = _pack(action_time=5000)
    eng = _fresh(raw, all_defs, ce)
    eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    assert eng._snap.get("counter_stance") is not None, "窗宽 5000 下姿态应仍在"
    # 持有者再行动（窗宽 5000 内不会被关闭）
    eng.player_act({"type": "skill", "skill_id": "sw_slash"})
    st = eng._snap.get("counter_stance")
    assert st is not None, "持有者再次行动不应关闭时间窗口"
    # 后半段敌方行动（仍在窗口内）→ 触发
    act = _parryable_action(raw)
    out = eng.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = _fx_of(out)
    assert "parry" in fx and "parry_counter" in fx, \
        f"窗口内（即使持有者已再行动）应触发防反，got {fx}"

"""实机证据 · 最低伤害保底（settings.battle.min_damage）：真实内容包 + 真实引擎跑一场战斗。

用法（仓库根执行）：

    PYTHONPATH= .venv/bin/python scripts/min_damage_floor_probe.py

做的事：
  1. 读真实包 `content/veinborn/settings.json`，把 `battle.min_damage` 按「设置页可选项」
     覆写为 0 / 5（模拟作者在设置页配置），经 `resolve_battle_settings` 白名单装配；
  2. `build_pack("content/veinborn")` 取真实 registry；用引擎同源 `_enemy_combatant`
     把真实 `enemies.json` 条目（砾甲兽）转成敌方 combatant；
  3. 用真实 BattleEngine 各跑一场「玩家普攻」战斗，打印每次命中的 raw → final 与保底事件。

输出即报告「实机证据」片段（真实引擎管线，非 mock）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from qbot_rpg.commands.battle_launch_commands import _enemy_combatant  # noqa: E402
from qbot_rpg.content.loader import build_pack  # noqa: E402
from qbot_rpg.core.battle import BattleEngine  # noqa: E402
from qbot_rpg.core.battle_config import resolve_battle_settings  # noqa: E402

SETTINGS = REPO / "content" / "veinborn" / "settings.json"
ENEMIES = REPO / "content" / "veinborn" / "enemies.json"

PLAYER = {
    "hp": 400, "max_hp": 400, "mp": 30, "max_mp": 30,
    "atk": 20, "dfn": 30, "mag": 10, "spd": 10, "foc": 10,
    "con": 30, "agi": 10, "lck": 10, "name": "玩家",
}


def _enemy(entry_id: str) -> dict:
    rows = json.loads(ENEMIES.read_text(encoding="utf-8"))
    entry = next(e for e in rows if e.get("id") == entry_id)
    return _enemy_combatant(entry)


def _run(min_damage: int) -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    settings["battle"]["min_damage"] = min_damage  # 设置页可选项
    cfg = resolve_battle_settings(settings)
    pack, _changed = build_pack(REPO / "content" / "veinborn")
    assert pack.report.ok, pack.report.errors
    eng = BattleEngine(registry=pack.registry, config=cfg)
    eng.start(dict(PLAYER), _enemy("gravel_armor_beast"), random_seed=42)
    print(f"--- battle.min_damage={min_damage}  resolve_battle_settings→"
          f"{cfg.get('min_damage')}  敌=砾甲兽(con=45) ---")
    for i in range(1, 5):
        rep = eng.player_act({"type": "normal", "attack_type": "slash",
                              "mult": 0.20})  # 弱击：压低单次伤害以观察保底
        for o in rep.outcomes:
            if o.actor != "player" or o.final_damage is None:
                continue
            ev = [e for e in (o.side_effects or ()) if e.get("type") == "min_damage"]
            flag = f"  ← 保底 {ev[0]['from']}→{ev[0]['to']}" if ev else ""
            print(f"  第{i}击  raw={o.raw_damage:>3}  final={o.final_damage:>3}"
                  f"  crit={o.crit}{flag}")
        if rep.ended:
            print(f"  （战斗结束 status={rep.status}）")
            break


if __name__ == "__main__":
    _run(0)
    _run(5)

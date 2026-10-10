#!/usr/bin/env python3
"""能力闭环门禁（scripts/check_capability_closure.py）——「登记 ≠ 实现」的最小对拍。

背景（2026-10-10 · 日研 Q3「治理元数据开口子」后选定的**最小形态**）：外部日研 10-05 篇主张
建 `Capability Manifest` + `check_capability_closure.py`。本实现**不新建中央能力清单**，
而是**复用既有唯一源**——`qbot_rpg/data/gear_stats.py` 的 `EFFECT_AXIS_SPECS`（17 条特效轴，
每条自带 `consumer`「唯一消费点」+ `consumer_note`）——只补三件缺失的可见性/门禁：

  D-01（红拦）每轴必须写 `consumer` 与 `consumer_note`
              —— 守「无消费点的轴不得登记」（`cooldown_reduction_pct` 的教训：登记了不生效 = 陷阱）
  D-02（红拦）「消费点待接」（哨兵 `EFFECT_CONSUMER_PENDING`）的轴集合**冻结**；
              新增/移除哨兵轴必须显式改本脚本的 FROZEN_PENDING 并写明理由
  D-03（黄提示）把每轴的 `consumer` 标识分为「代码内可定位」与「仅契约命名」两类并打印清单
              —— **不红拦**：契约命名是既有事实（收口函数名未必与标识同名），只做可见化

**不新增任何声明文件、不改内容包格式**：判据全部来自既有唯一源。
退出码：0 = 通过（含仅有黄提示）；1 = D-01/D-02 失败；2 = 无法导入既有唯一源。
用法：python scripts/check_capability_closure.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Mapping, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent

#: 冻结的「消费点待接」轴（哨兵）：2026-10-10 现状 = 1 条。
#: 新增哨兵轴 = 新增「登记了不生效」的轴，必须在本表登记并写理由（否则 D-02 红拦）。
#: 现状理由：`reward_mult_pct`（D5 登记）——奖励类别分散在三处、无唯一收口，故不硬造。
FROZEN_PENDING: Tuple[str, ...] = ("reward_mult_pct",)


def _ident_target(consumer: str) -> Tuple[str, str]:
    """`module.func` 形态 -> (module, func)；非该形态 -> ("", consumer)。"""
    parts = str(consumer).split(".")
    if len(parts) >= 2:
        return parts[0], parts[-1]
    return "", str(consumer)


def locate_consumers(specs: Sequence[Mapping[str, object]],
                     core_dir: Path) -> Tuple[List[str], List[str]]:
    """把每轴 consumer 标识分为 (代码内可定位, 仅契约命名)。纯函数，便于测试。"""
    located: List[str] = []
    contract_only: List[str] = []
    for spec in specs:
        axis = str(spec.get("axis", "?"))
        con = str(spec.get("consumer", "")).strip()
        mod, fn = _ident_target(con)
        path = core_dir / f"{mod}.py" if mod else None
        if path is not None and path.is_file():
            text = path.read_text(encoding="utf-8")
            if fn and (fn in text or fn.lstrip("_") in text):
                located.append(f"{axis} -> {con}")
                continue
        contract_only.append(f"{axis} -> {con}")
    return located, contract_only


def run_check(specs: Sequence[Mapping[str, object]], core_dir: Path,
              pending_sentinel: str) -> Tuple[List[str], List[str], List[str], List[str]]:
    """返回 (错误, 待接轴, 可定位, 仅契约命名)。纯函数，便于测试。"""
    errors: List[str] = []
    pending: List[str] = []
    for spec in specs:
        axis = str(spec.get("axis", "?"))
        consumer = str(spec.get("consumer", "")).strip()
        note = str(spec.get("consumer_note", "")).strip()
        if not consumer:
            errors.append(f"D-01 轴「{axis}」缺 `consumer`（无消费点的轴不得登记）")
        if not note:
            errors.append(f"D-01 轴「{axis}」缺 `consumer_note`（消费点收口说明）")
        if consumer == pending_sentinel:
            pending.append(axis)
    extra = sorted(set(pending) - set(FROZEN_PENDING))
    missing = sorted(set(FROZEN_PENDING) - set(pending))
    if extra:
        errors.append(
            "D-02 新增「消费点待接」轴：" + ", ".join(extra)
            + "（哨兵轴集合已冻结 —— 要么接线，要么在 FROZEN_PENDING 登记并写理由）")
    if missing:
        errors.append(
            "D-02 冻结点已接线但未从 FROZEN_PENDING 移除：" + ", ".join(missing)
            + "（接线后请同步本表，避免门禁与事实漂移）")
    located, contract_only = locate_consumers(specs, core_dir)
    return errors, pending, located, contract_only


def main() -> int:
    sys.path.insert(0, str(REPO))
    try:
        from qbot_rpg.data.gear_stats import EFFECT_AXIS_SPECS, EFFECT_CONSUMER_PENDING
    except Exception as exc:  # noqa: BLE001
        print(f"无法导入既有唯一源 qbot_rpg/data/gear_stats.py：{type(exc).__name__}: {exc}")
        return 2

    errors, pending, located, contract_only = run_check(
        list(EFFECT_AXIS_SPECS), REPO / "qbot_rpg" / "core", EFFECT_CONSUMER_PENDING)

    print("能力闭环门禁（scripts/check_capability_closure.py）")
    print(f"  唯一源：qbot_rpg/data/gear_stats.py EFFECT_AXIS_SPECS（{len(EFFECT_AXIS_SPECS)} 轴）")
    print(f"  D-02 消费点待接（哨兵）轴：{len(pending)} 条 {pending}")
    print(f"  D-03 consumer 可定位 {len(located)} 条 / 仅契约命名 {len(contract_only)} 条"
          "（黄提示，不拦）")
    if contract_only:
        print("    仅契约命名的标识（收口函数名未必与标识同名，属既有事实）：")
        for item in contract_only:
            print(f"      - {item}")
    if errors:
        print(f"\n发现 {len(errors)} 处问题：")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\n通过：每轴都有消费点声明；待接轴集合与冻结点一致。CLOSURE-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""批28 · D-6：`transfer_allowed` 空壳键删除的回归断言（CakeGame 补漏 §七 D-6）。

主 agent 裁决（2026-09-16 · 用户授权「你判断就行」）：**删除**——键在、校验在、
`qbot_rpg/core/` 无任何消费点（「看着像功能其实没接线」），遵循奥卡姆直接删。

本用例锁死删除结果（防回归）：
  ① 框架字段元数据（`default_field_meta_table` 的 enhance.settings 子结构）不再登记该键；
  ② `DEFAULT_ENHANCE.settings` 缺省锚点不再含该键；
  ③ `validate_enhance` 不再对该键做 V5 布尔校验（未知键按「默认放行」不误伤）；
  ④ `level_gated` 的 V5 布尔校验保留（证明只删空壳、未误伤同模块真字段）。

合成样本（不写任何真实内容包）；真实内容包里的残留数据按纪律**不擅自删**，
登记为「需用户确认后清理」（见批28 报告与 `docs/矛盾与待裁决登记.md` D-6 行）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from qbot_rpg.content.enhance_models import DEFAULT_ENHANCE, validate_enhance


class _Report:
    """`validate_enhance` 的鸭子类型替身（签名对齐 `validator._Checker`）。"""

    def __init__(self) -> None:
        self.errors: List[Tuple[str, str, Dict[str, Any]]] = []
        self.warnings: List[Tuple[str, str, Dict[str, Any]]] = []

    def _err(self, module: str, field: str, kind: str, **detail: Any) -> None:
        self.errors.append((field, kind, dict(detail)))

    def _warn(self, module: str, field: str, kind: str, **detail: Any) -> None:
        self.warnings.append((field, kind, dict(detail)))


def _settings(extra: Dict[str, Any]) -> Dict[str, Any]:
    """最小可进入 V5 段的 enhance raw（含合法 max_by_rarity 防提前 return）。"""
    body: Dict[str, Any] = {"max_by_rarity": {"normal": 5}}
    body.update(extra)
    return {"enhance": {"settings": body}}


def test_framework_meta_no_longer_registers_key() -> None:
    """框架子结构（CHILD_SPEC → 编辑器元数据）已不含该键。"""
    from qbot_rpg.content.field_meta import default_field_meta_table

    kids = default_field_meta_table().modules["enhance"].fields["settings"].children
    assert "transfer_allowed" not in kids
    # 同段真字段仍在（防误删整段）
    assert {"max_by_rarity", "fail_tier_split", "shatter_mode", "luck_affects",
            "level_gated"} <= set(kids)


def test_default_anchor_no_longer_has_key() -> None:
    """缺省锚点（内容包未配 enhance 时的兜底）不再含该键。"""
    assert "transfer_allowed" not in DEFAULT_ENHANCE["settings"]


def test_v5_no_longer_validates_removed_key() -> None:
    """非法布尔形态的该键 → 不再触发 V5 红拦（降级为未知键默认放行）。"""
    report = _Report()
    validate_enhance(_settings({"transfer_allowed": "not-a-bool"}), report)
    assert not [e for e in report.errors if "transfer_allowed" in e[0]]


def test_v5_keeps_level_gated_validation() -> None:
    """同段真字段 level_gated 的 V5 布尔校验保留（删除未误伤）。"""
    report = _Report()
    validate_enhance(_settings({"level_gated": "not-a-bool"}), report)
    assert any(field == "enhance.settings.level_gated" and kind == "V5"
               for field, kind, _ in report.errors)

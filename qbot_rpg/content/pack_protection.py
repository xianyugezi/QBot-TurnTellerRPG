"""数据包保护（框架 §6.12-25「作者更新中」；批32 A1）。

语义（settings 段 `pack_protection.enabled`，缺省 false = 现状不变）：
  · 未开启 → 门禁直接放行，**零额外校验**（行为与现状逐字段一致，零新增拦截）；
  · 开启 → 进入游玩前跑**既有包校验**（`loader.build_pack` → `validator.check_pack`），
    红拦 → 拒绝进入游玩，并给人话提示（哪个包 / 什么问题 / 去哪改）；
    同时把既有 Y-6「manifest 声明但缺模块数据」黄提示在保护期**升级为阻断**
    （门禁只能更严；半成品包正是保护要挡住的场景）；
  · 开启期间玩家（非 GM）指令由 `assembly/runner.py` 统一拦截 → 「作者更新中，请稍后再试...」。

**不新增第二套校验逻辑**：门禁只消费既有校验器的报告，外加「保护期升级 Y-6」这一条更严判定；
**不影响编辑器**：编辑器读取/写入链路不经过本模块（作者照常进编辑器补数据）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from qbot_rpg.content.atomic_store import humanize_errors
from qbot_rpg.content.loader import PackLoadError, build_pack

__all__ = [
    "PLAYER_NOTICE",
    "PackProtectionError",
    "enforce_play_gate",
    "is_enabled",
    "play_gate",
    "player_notice",
    "read_pack_settings",
]

#: 保护开启期间玩家指令的统一人话提示（框架 §6.12-25 原文）。
PLAYER_NOTICE = "作者更新中，请稍后再试..."


class PackProtectionError(RuntimeError):
    """保护开启 + 包不完整 → 拒绝进入游玩；携带结构化门禁结果（人话在 `.gate`）。"""

    def __init__(self, gate: Mapping[str, Any]) -> None:
        self.gate: Dict[str, Any] = dict(gate)
        super().__init__(str(gate.get("message") or "数据包保护：内容包未完成，已拒绝进入游玩。"))


def read_pack_settings(pack_dir: object) -> Mapping[str, Any]:
    """读包内 ``settings.json``（缺失/损坏/非对象 → 空映射，绝不抛）。"""
    path = Path(str(pack_dir)) / "settings.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return dict(doc) if isinstance(doc, Mapping) else {}


def is_enabled(settings: object) -> bool:
    """`settings.pack_protection.enabled` 是否为真（非法/缺省 → False）。"""
    if not isinstance(settings, Mapping):
        return False
    cfg = settings.get("pack_protection")
    if not isinstance(cfg, Mapping):
        return False
    return bool(cfg.get("enabled"))


def player_notice(settings: object) -> Optional[str]:
    """保护开启 → 玩家指令人话提示；未开启 → None（调用方照常执行）。"""
    return PLAYER_NOTICE if is_enabled(settings) else None


def _pack_name(pack_dir: Path) -> str:
    """包显示名（manifest.name → 目录名兜底）。只读，绝不抛。"""
    try:
        doc = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
        if isinstance(doc, Mapping):
            name = doc.get("name")
            if isinstance(name, str) and name:
                return name
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return pack_dir.name


def _missing_module_problem(module: object) -> Dict[str, Any]:
    """既有 Y-6「声明但缺模块数据」→ 保护期阻断条目（人话含去哪改）。"""
    mod = str(module)
    return {
        "level": "red",
        "code": "module_missing_protected",
        "rule": "module_missing",
        "module": mod,
        "field": f"{mod}.json",
        "message": f"模块「{mod}」已在 manifest 声明，但缺少数据文件 {mod}.json"
                   "（保护期内视为半成品）。",
        "why": "作者大改版中模块数据尚未补齐；此时进入游玩会让玩家用到半成品数据。",
        "how": f"请在编辑器打开该包，选择模块「{mod}」补全数据"
               "（或从 manifest 去掉该模块声明）后重试。",
    }


def _blocked_message(pack_name: str, problems: List[Mapping[str, Any]]) -> str:
    """拒绝进入游玩的人话提示：哪个包 / 什么问题 / 去哪改（三段齐备）。"""
    lines = [f"数据包保护已开启：内容包「{pack_name}」尚未完成，已拒绝进入游玩。", "问题："]
    for i, p in enumerate(problems, 1):
        lines.append(f"  {i}. {p.get('message') or p.get('raw') or p.get('code')}")
    lines.append(
        f"去哪改：请打开编辑器 → 选择内容包「{pack_name}」→ 按上面提示补全/修正；"
        "确认发布完成后，可在「通用设置 → 数据包保护」关闭保护。"
    )
    return "\n".join(lines)


def play_gate(pack_dir: object, meta: Optional[object] = None) -> Dict[str, Any]:
    """进入游玩门禁（同步纯逻辑，复用既有校验器）。

    返回 ``{enabled, allowed, pack, pack_name, message, problems, fix_hint}``：
      · 未开启 → ``allowed=True`` 且不跑任何校验（现状逐字段一致）；
      · 开启 → 跑 `build_pack`：红拦 + 保护期升级的缺模块 → ``allowed=False``。
    """
    pd = Path(str(pack_dir))
    settings = read_pack_settings(pd)
    pack_name = _pack_name(pd)
    if not is_enabled(settings):
        return {"enabled": False, "allowed": True, "pack": pd.name, "pack_name": pack_name,
                "message": "", "problems": [], "fix_hint": ""}
    problems: List[Dict[str, Any]] = []
    try:
        pack, _changed = build_pack(pd, meta)  # type: ignore[arg-type]
        warnings = list(getattr(pack.report, "warnings", ()) or ())
    except PackLoadError as exc:
        problems.extend(humanize_errors(exc.errors))
        warnings = list(getattr(exc.report, "warnings", ()) or ())
    for w in warnings:
        detail = dict(getattr(w, "detail", {}) or {})
        if str(detail.get("rule") or "") == "module_missing":
            problems.append(_missing_module_problem(getattr(w, "module", "")))
    allowed = not problems
    message = "" if allowed else _blocked_message(pack_name, problems)
    return {
        "enabled": True,
        "allowed": allowed,
        "pack": pd.name,
        "pack_name": pack_name,
        "message": message,
        "problems": problems,
        "fix_hint": "" if allowed else f"在编辑器中补全内容包「{pack_name}」后重试。",
    }


def enforce_play_gate(pack_dir: object, meta: Optional[object] = None) -> Dict[str, Any]:
    """门禁执行入口：允许 → 返回门禁结果；拒绝 → 抛 `PackProtectionError`。"""
    gate = play_gate(pack_dir, meta)
    if not gate["allowed"]:
        raise PackProtectionError(gate)
    return gate

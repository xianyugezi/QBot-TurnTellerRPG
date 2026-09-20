"""批70 · 登记失效清账（走查 §3 左栏 / 中栏可见引导 + 「空骨架模块」容忍复用）回归测试。

依据：`/root/deliverables/编辑器_新用户走查.md`
  §3 左栏：未启用行要有**可见**的启用引导（不能只藏在 hover title 里）；
  §3 中栏：0 条时两分支都要给「下一步」；
  §5 新卡点（批69 自查）：推荐组合会启用空骨架模块（如技能库无普攻），
      修前这些红拦会把**其它**模块的新建 / 保存一并阻断；批69 复用模块开关同一
      `_tolerate_empty_modules` 机制——空骨架只提示不阻断，真正的问题照常红拦。

断言纪律（并行批会改文案/UI）：只测「机制 / 结构 / 分支 / 状态位 / 长度」，
不比对任何一句中文提示的逐字原文；写盘只落 `tmp_path` 临时内容包，
绝不触碰仓库 `content/` 下任何真实内容包。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
NEW_NOTE = "批74 · 手册真bug修复"
OLD_NOTE = "批68 · 新手上路打磨"


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_pack(root: Path, skills_body: Any, *, modules: Any = None) -> Path:
    """临时包：物品有 1 条，技能（或指定模块）按 `skills_body` 造「空骨架 / 非空」两态。"""
    pkg = root / "p1"
    pkg.mkdir(parents=True)
    _write(pkg / "manifest.json",
           {"name": "p1", "version": "1", "schema_version": 1,
            "modules": list(modules or ["items", "skills"])})
    _write(pkg / "items.json", [{"id": "item_001", "name": "剑"}])
    _write(pkg / "skills.json", skills_body)
    return pkg


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn_src(name: str) -> str:
    """从 index.html 截取 `function name(` 到下一个顶层 `function ` 的源码（按名切片）。"""
    html = _html()
    start = html.index("function %s(" % name)
    nxt = html.find("\nfunction ", start + 1)
    assert nxt != -1, name
    return html[start:nxt]


# =====================================================================================
# A · 新卡点（批69 自查）：其它模块「空骨架」不再阻断本模块的新建 / 保存
# =====================================================================================
def test_empty_skeleton_module_does_not_block_create(tmp_path: Path) -> None:
    """技能库还是空骨架（触发 V-7）→ 新建物品照常成功，且如实给出「被容忍」黄提示。"""
    pkg = _make_pack(tmp_path, [])                       # skills.json = []（空骨架）
    env = editor_ops.create_entry("p1", "items", "item_002", {"name": "新剑"}, root=tmp_path)
    assert env["ok"] is True
    assert env["level"] == "yellow"                      # 放行但有如实提示，不是静默
    written = _read(pkg / "items.json")
    assert any(str(e.get("id")) == "item_002" for e in written)
    assert _read(pkg / "skills.json") == []              # 其它模块文件零改动
    tolerated = [w for w in env["warnings"] if w.get("tolerated")]
    assert tolerated, "空骨架放行必须如实返回黄提示"
    assert str(tolerated[0].get("module") or "") != "items"   # 提示归属出问题的那个模块


def test_empty_skeleton_module_does_not_block_validate(tmp_path: Path) -> None:
    """校验路径与保存路径同一口径：空骨架只提示，ok=True 且红拦为 0。"""
    _make_pack(tmp_path, [])
    env = editor_ops.validate_entry("p1", "items", "item_001", {"name": "改名"}, root=tmp_path)
    assert env["ok"] is True
    assert env["errors"] == []
    assert any(w.get("tolerated") for w in env["warnings"])


def test_empty_skeleton_module_does_not_block_save(tmp_path: Path) -> None:
    """编辑已存在条目：其它模块空骨架不阻断保存，目标文件真的写下去。"""
    pkg = _make_pack(tmp_path, [])
    env = editor_ops.save_entry("p1", "items", "item_001", {"name": "改名"}, root=tmp_path)
    assert env["ok"] is True
    assert _read(pkg / "items.json")[0]["name"] == "改名"


def test_non_empty_invalid_module_still_blocks(tmp_path: Path) -> None:
    """边界：模块**非空但确实有问题** → 照常红拦、零写入（容忍只对空骨架生效）。"""
    pkg = _make_pack(tmp_path, [{"id": "s1", "name": "x", "job": "j"}])
    before = (pkg / "items.json").read_bytes()
    env = editor_ops.create_entry("p1", "items", "item_002", {"name": "新剑"}, root=tmp_path)
    assert env["ok"] is False and env["level"] == "red"
    assert env["errors"]
    assert (pkg / "items.json").read_bytes() == before


def test_tolerate_helper_scoped_to_empty_skeletons() -> None:
    """复用的判定本身：空 list / 空 dict 才容忍；非空模块 → 严格（None）。"""
    from qbot_rpg.web.editor_ops import _tolerate_empty_modules

    class _E:
        def __init__(self, module: str) -> None:
            self.module = module

    assert _tolerate_empty_modules({"skills": []})(_E("skills")) is True
    assert _tolerate_empty_modules({"settings": {}})(_E("settings")) is True
    assert _tolerate_empty_modules({"skills": [{"id": "x"}]}) is None
    assert _tolerate_empty_modules({"items": [1], "skills": []})(_E("items")) is False


def test_tolerated_warning_is_marked_and_has_human_module_label(tmp_path: Path) -> None:
    """容忍黄提示带 `tolerated` 标记（前端收敛时保留）+ 模块中文名（不裸露英文键）。"""
    _make_pack(tmp_path, [])
    env = editor_ops.validate_entry("p1", "items", "item_001", {"name": "改名"}, root=tmp_path)
    tol = [w for w in env["warnings"] if w.get("tolerated")]
    assert tol
    w = tol[0]
    assert w.get("module")
    assert str(w.get("module_label") or "").strip()
    assert w.get("module_label") != w.get("module")      # 中文名而非裸键名


# =====================================================================================
# B · §3 左栏：未启用行给可见启用引导（且不再重复「未启用」两遍）
# =====================================================================================
def test_left_rail_available_row_has_visible_action_label() -> None:
    """未启用行的 innerHTML 里出现一个**短动作词**（不是只写进 title）。"""
    html = _html()
    m = re.search(r'esc\(impl\s*\?\s*"([^"]+)"\s*:\s*capsTag\(a\)\)', html)
    assert m, "未启用行缺少可见动作标签"
    assert 0 < len(m.group(1)) <= 6, "动作词应为短标签（≤6 字），不是长句"


def test_left_rail_action_tag_is_structurally_distinct() -> None:
    """动作标签只在「可实现」行加 `act` 类，并有独立样式（与灰标签区分，看得见可点）。"""
    html = _html()
    assert '(impl ? " act" : "")' in html
    assert ".mod.off .tag.act" in html
    # 旧写法：无 act 类 + 直接摊 capsTag → 未启用行重复「未启用」两遍，必须已消失。
    assert "'<span class=\"tag\">' + esc(capsTag(a))" not in html


def test_left_rail_group_hint_is_rendered_visibly() -> None:
    """分组旁那行「点一项即可启用…」仍在（可见提示），且 display:block 生效。"""
    html = _html()
    assert "sep-h" in _fn_src("renderModules")
    assert re.search(r"\.mod-sep \.sep-h\s*\{[^}]*display:\s*block", html)


# =====================================================================================
# C · §3 中栏：0 条时两分支都给「下一步」
# =====================================================================================
def test_center_empty_state_offers_next_step_in_both_branches() -> None:
    src = _fn_src("listEmptyHtml")
    assert src.count("le-t") == 2, "应有两个空态分支（未启用任何模块 / 本模块无条目）"
    assert "data-open-modules" in src            # 分支1：可直接打开模块开关
    assert "新建" in src                          # 分支2：指向「+ 新建条目」


def test_center_empty_state_reuses_header_counts() -> None:
    """中栏 0 条时标题/计数/页脚三处状态位仍被写入（「我是谁 / 我在哪」不缺口）。"""
    src = _fn_src("renderEmptyPack")
    for token in ('el("list-title")', 'setHdrNote("list-count"', 'el("list-ft")'):
        assert token in src, token


# =====================================================================================
# D · 页脚批次串
# =====================================================================================
def test_footer_batch_note_is_batch69() -> None:
    html = _html()
    assert NEW_NOTE in html
    assert OLD_NOTE not in html

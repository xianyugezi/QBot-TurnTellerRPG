"""编辑器重写批15 · #8 页面化（二级折叠块）测试。

覆盖任务书要求（通用机制，不写死模块名/字段名）：
  · 分组页签之下支持**子分组 / 折叠块**（子块来自元数据 subgroup / field_subgroups）；
  · 分组内字段过多时，按**元数据声明顺序**把超出部分收进隐式「更多字段」折叠块
    （规则只看 order/数量，不硬编码字段名）；
  · 折叠**不减少字段集**（一号原则：字段全部还在，只是默认收起）——块计数之和 == 字段数；
  · 大段默认折叠（collapsed=True）、主块常驻展开；显式子块默认折叠、顺序/显示名来自元数据；
  · 前端折叠块纯逻辑（node 执行 EditorBlocks）+ 页面接线/CSS 断言；
  · DOM 实测（真 Chromium）：长模块「折叠前（全展开）vs 折叠后」右栏 scrollHeight 对比。

批20 C 起：**声明了子分组**的模块（框架元数据 field_subgroups）改出「二级页签」，本测试对
这两套呈现都做断言（页签制：可见字段 = 当前子页里能看见的字段，且首屏仍不滚动）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content.models import FieldMeta, ModuleMeta
from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

# 首屏主块就够长的真实长模块（元数据分组内字段数 > AUTO_MORE_AFTER，折叠前后差异可量）
MEASURE_CASES = ("settings:battle", "action:bb_slam",
                 "effects:guard_up", "skills:mastery_skills")


def _marked_block(begin: str, end: str) -> str:
    html = HTML.read_text(encoding="utf-8")
    match = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), html, re.S)
    assert match, f"index.html 缺少标记块 {begin} … {end}"
    return match.group(1)


def _first_entry(mod: str, pack: str = "veinborn") -> str:
    return api.list_entries(pack, mod, root=CONTENT)["entries"][0]["id"]


# ---------------------------------------------------------------------------
# 一、折叠块计划（后端元数据/顺序驱动）
# ---------------------------------------------------------------------------
def test_long_group_splits_into_main_and_more_block() -> None:
    d = api.entry_detail("veinborn", "settings", "battle", root=CONTENT)
    assert d["field_count"] > api.AUTO_MORE_AFTER
    blocks = d["blocks"]["默认"]
    assert [b["name"] for b in blocks] == ["", api.AUTO_MORE_BLOCK]
    main, more = blocks
    assert main["count"] == api.AUTO_MORE_AFTER and main["collapsed"] is False
    assert more["collapsed"] is True
    assert more["label"] == api.MORE_FIELDS_LABEL
    # 折叠不减少字段：主块 + 更多块 == 全部字段，且每个字段恰落一块
    assert main["count"] + more["count"] == d["field_count"]
    keys = [f["key"] for f in d["fields"]]
    assert main["keys"] + more["keys"] == keys
    assert len(set(keys)) == len(keys)
    # 字段的 block 归属与计划一致
    by_key = {f["key"]: f for f in d["fields"]}
    for k in more["keys"]:
        assert by_key[k]["subgroup"] == api.AUTO_MORE_BLOCK


def test_short_group_has_single_expanded_block() -> None:
    d = api.entry_detail("veinborn", "quest", _first_entry("quest"), root=CONTENT)
    for name, blocks in d["blocks"].items():
        assert len(blocks) == 1
        b = blocks[0]
        assert b["name"] == "" and b["collapsed"] is False
        assert b["count"] <= api.AUTO_MORE_AFTER


def test_generic_rule_needs_no_module_or_field_names() -> None:
    """通用性：换一个模块/字段仍按「order + 数量」折叠；显式子块按声明顺序与显示名。"""
    fields = [
        {"key": f"f{i}", "group": "g", "subgroup": ""} for i in range(3)
    ]
    mmeta = ModuleMeta(entry_type="list")
    plan = api._block_plan([dict(f) for f in fields], mmeta)
    assert [b["name"] for b in plan["g"]] == [""]
    assert plan["g"][0]["count"] == 3 and plan["g"][0]["collapsed"] is False
    # 显式子块：字段自带 subgroup + 模块级 subgroup_labels / subgroup_order
    fs = [
        {"key": "a", "group": "g", "subgroup": "z"},
        {"key": "b", "group": "g", "subgroup": ""},
        {"key": "c", "group": "g", "subgroup": "y"},
    ]
    mm2 = ModuleMeta(entry_type="list",
                     subgroup_order=("y", "z"),
                     subgroup_labels={"y": "进阶", "z": "稀有"})
    plan2 = api._block_plan(fs, mm2)
    assert [(b["name"], b["label"], b["collapsed"]) for b in plan2["g"]] == [
        ("", "", False), ("y", "进阶", True), ("z", "稀有", True),
    ]
    # 字段集守恒
    assert plan2["g"][0]["keys"] == ["b"]
    assert plan2["g"][1]["keys"] == ["c"] and plan2["g"][2]["keys"] == ["a"]


def test_field_meta_subgroup_wins_over_module_table() -> None:
    fm = FieldMeta(type="str", subgroup="explicit")
    mmeta = ModuleMeta(entry_type="list", field_subgroups={"k": "module"})
    assert api._resolve_subgroup("k", fm, mmeta) == "explicit"
    assert api._resolve_subgroup("k", None, mmeta) == "module"
    assert api._resolve_subgroup("other", None, mmeta) == ""


def test_all_long_modules_conserve_field_set() -> None:
    """一号原则：折叠只是展示，字段键集合逐模块守恒（修前后字段完全相同）。"""
    for case in MEASURE_CASES:
        mod, eid = case.split(":")
        d = api.entry_detail("veinborn", mod, eid, root=CONTENT)
        planned = [k for blocks in d["blocks"].values() for b in blocks for k in b["keys"]]
        assert sorted(planned) == sorted(f["key"] for f in d["fields"]), case


# ---------------------------------------------------------------------------
# 二、前端纯逻辑（node 执行 EditorBlocks）+ 接线/CSS
# ---------------------------------------------------------------------------
_BLOCKS_HARNESS = r"""
const B = require(process.argv[1]);
const out = {};
const plan = {
  "g": [
    { name: "", label: "", count: 2, collapsed: false, keys: ["a", "b"] },
    { name: "@more", label: "更多字段", count: 3, collapsed: true, keys: ["c", "d", "e"] },
    { name: "rare", label: "稀有", count: 1, collapsed: false, keys: ["f"] }
  ]
};
const bs = B.blocksFor("g", plan);
out.names = bs.map(function (x) { return x.name; });
out.main = bs.map(function (x) { return B.isMain(x); });
const st = B.initState(bs);
out.initCollapsed = B.view(bs, st).map(function (x) { return x.collapsed; });
B.toggle(st, bs[1]);
out.afterToggleMore = B.view(bs, st)[1].collapsed;
B.toggle(st, bs[1]);
out.afterToggleBack = B.view(bs, st)[1].collapsed;
out.unknownGroup = B.blocksFor("nope", plan).length;   // 未给计划 → 单主块兜底
out.mainNeverCollapses = B.collapsed(st, bs[0]);
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 折叠块语义执行")
def test_editor_blocks_js_semantics(tmp_path: Path) -> None:
    src = tmp_path / "blocks.js"
    src.write_text(_marked_block("/* EDITOR_BLOCKS_BEGIN */", "/* EDITOR_BLOCKS_END */"),
                   encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _BLOCKS_HARNESS, str(src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out: Dict[str, Any] = json.loads(proc.stdout)
    assert out["names"] == ["", "@more", "rare"]
    assert out["main"] == [True, False, False]
    assert out["initCollapsed"] == [False, True, False]   # 主块展开；命名块默认折叠
    assert out["afterToggleMore"] is False                  # 点一次 → 展开
    assert out["afterToggleBack"] is True                   # 再点 → 收起
    assert out["unknownGroup"] == 1 and out["mainNeverCollapses"] is False


def test_frontend_wires_collapsible_blocks() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "EditorBlocks.blocksFor" in html
    assert "function groupPaneHtml(" in html and "function bindSubBlocks(" in html
    assert "bindSubBlocks();" in html
    assert "data-sbtoggle=" in html and "data-sb=" in html
    assert "sbbody" in html and ".subblk" in html and ".sbhead" in html
    # 折叠块在 gpane 内、字段行仍走统一 fieldRow（块状换行/列表表格等既有布局不变）
    pane = re.search(r"function groupPaneHtml\(.*?\n\}", html, re.S)
    assert pane and "fieldRow" in pane.group(0)
    # 既有分组页签与草稿不被折叠逻辑触碰
    assert ".gpane[hidden] { display: none; }" in html or ".gpane[hidden]" in html


# ---------------------------------------------------------------------------
# 三、DOM 实测（真 Chromium）：折叠前（全展开）vs 折叠后
# ---------------------------------------------------------------------------
def _playwright_python() -> str:
    """找一个装了 playwright 的解释器（本机 playwright 与仓库 venv 可能不是同一个）。

    量测脚本本身在有 playwright 的解释器下跑；被量的编辑器宿主用当前解释器（能 import
    `qbot_rpg`）→ 由 `--host-python` 传下去。
    """
    for cand in (sys.executable, "/usr/bin/python3", shutil.which("python3") or ""):
        if not cand:
            continue
        probe = subprocess.run([cand, "-c", "import playwright"], capture_output=True)
        if probe.returncode != 0:
            continue
        check = subprocess.run(
            [cand, "-c",
             "from playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as p:\n"
             "    b = p.chromium.launch()\n"
             "    b.close()"],
            capture_output=True)
        if check.returncode == 0:
            return cand
    return ""


PW_PY = _playwright_python()
PW_READY = bool(PW_PY)


@pytest.mark.skipif(not PW_READY, reason="本机无 playwright/chromium，跳过 DOM 量测")
def test_dom_measure_scrolling_reduced(tmp_path: Path) -> None:
    out_json = tmp_path / "dom.json"
    cmd = [PW_PY, str(REPO / "scripts" / "editor_dom_measure.py"),
           "--pack", "veinborn", "--host-python", sys.executable, "--json", str(out_json)]
    for case in MEASURE_CASES:
        cmd += ["--case", case]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    data = json.loads(out_json.read_text(encoding="utf-8"))
    for case in data["cases"]:
        before = case["before_expanded"]
        after = case["after"]
        # 修前（全展开）：内容高于首屏 → 必须滚动
        assert before["scrollHeight"] > before["clientHeight"], case
        # 修后（折叠 / 二级页签）：**首屏可看完**（内容不高于右栏可视高度）
        assert after["scrollHeight"] <= after["clientHeight"], case
        assert after["scrollHeight"] < before["scrollHeight"], case
        # 折叠 / 分页只是收起，字段总数不变
        assert after["totalRows"] == before["totalRows"], case
        assert after["clientHeight"] == before["clientHeight"], case
        if after.get("subTabs"):
            # 批20 C：声明了子分组的模块 → 二级页签；一次只看一个子页
            assert after["subPanes"] >= after["subTabs"], case
            assert after["visibleRows"] == after["activeSubVisible"], case
            assert 0 < after["activeSubVisible"] <= after["activeSubTotal"], case
            assert after["activeSubTotal"] < after["totalRows"], case
        else:
            # 既有口径：折叠块收起后，首屏可见字段 = 主块（常驻）字段
            assert after["visibleRows"] == after["activeMain"], case
            assert after["activeMain"] <= after["activeTotal"], case

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M8 炼金 fixtures 自检脚本（纯 JSON 结构断言，无引擎/校验器依赖）。

依据契约 docs/m8_contract_数据与校验.md §一~§五 字段表与校验规则（REC/TRT/PRF/ALC）：
对 content/test_demo 与 tests/fixtures/packs/legal 两包逐项断言——
  ① 每个 JSON 可解析
  ② 必填键齐全（照契约字段表）
  ③ 包内引用自洽：recipe materials/inputs/output/catalyst/combine_from/evolve_to 引用
     items/recipe id 存在于本包；traits.effects 引用效果家族存在；slots.equip_id 引用
     items/equipment 存在
  ④ 进化线无环（DFS）
  ⑤ element_req / items.elements 元素键 ∈ 8 元素注册表（地水火风雷晶月无）
  ⑥ manifest modules 与磁盘 json 文件一一对应（无声明缺失、无未声明文件）
  ⑦ settings.alchemy 段键值类型正确
  ⑧ 装饰珠 quality 键 ∈ {common, uncommon, rare, legendary}

运行：.venv/bin/python3 scripts/check_m8_fixtures.py
退出码：0=全部通过；1=存在失败项。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent

PACKS = {
    "test_demo": REPO / "content" / "test_demo",
    "legal": REPO / "tests" / "fixtures" / "packs" / "legal",
}

ELEMENTS = {"earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void"}
QUALITY_KEYS = {"common", "uncommon", "rare", "legendary"}
TRAIT_RARITY = {"normal", "super"}
TRAIT_SOURCE = {"素材", "成品", "金色素材"}
KIND_ENUM = {"craft", "combine", "upgrade"}
TIERS = ["见习", "正式", "精通", "专家", "大师", "宗师", "王"]
SP_PANEL_KEYS = {"id", "name", "cost", "repeatable", "max_repeat", "desc"}
TITLE_KEYS = {"id", "name", "icon", "source", "desc"}
TITLE_SOURCES = {"king", "contest", "achievement", "custom"}
GEM_DOTTED_KEYS = (
    "gem.分解", "gem.复制", "gem.成品合成", "gem.配方合成",
    "gem.特性合成", "gem.珠升阶", "gem.复制额外", "gem.decompose_formula",
)


class Reporter:
    def __init__(self, pack: str) -> None:
        self.pack = pack
        self.errors: list[str] = []
        self.checks: list[str] = []

    def ok(self, label: str, detail: str = "") -> None:
        self.checks.append(f"[PASS] {label}{(' - ' + detail) if detail else ''}")

    def fail(self, label: str, msg: str) -> None:
        self.errors.append(f"[FAIL] {label}: {msg}")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def get_ids(data: object, key: str = "id") -> set[str]:
    if not isinstance(data, list):
        return set()
    return {str(e.get(key)) for e in data if isinstance(e, dict) and e.get(key) is not None}


# ---------------------------------------------------------------------------
# ① JSON 可解析 + 建包内 ID 索引
# ---------------------------------------------------------------------------
def parse_pack(pack_dir: Path, rep: Reporter) -> dict[str, object] | None:
    data: dict[str, Any] = {}
    for jf in sorted(pack_dir.glob("*.json")):
        if jf.name == "manifest.json":
            continue
        try:
            data[jf.stem] = load_json(jf)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            rep.fail("JSON 可解析", f"{jf.name}: {e}")
    return data if not rep.errors else None


# ---------------------------------------------------------------------------
# ② 必填键齐全（照契约字段表）
# ---------------------------------------------------------------------------
def check_recipe_schema(recipes: list[dict], rep: Reporter) -> None:
    for i, r in enumerate(recipes):
        base = f"recipe[{i}]({r.get('id', '?')})"
        for k in ("id", "name", "kind", "level"):
            if k not in r:
                rep.fail("recipe 必填键", f"{base} 缺 {k}")
                continue
        if r.get("kind") not in KIND_ENUM:
            rep.fail("recipe kind", f"{base} kind={r.get('kind')!r} 不在 {sorted(KIND_ENUM)}")
        if not isinstance(r.get("level"), int) or not (1 <= r["level"] <= 99):
            rep.fail("recipe level", f"{base} level 须 1-99")
        if "id" in r and any(c in r["id"] for c in "* ,=+"):
            rep.fail("recipe id 命名", f"{base} 含保留字符 * , = + 空格")
        kind = r.get("kind")
        if kind in ("craft", "combine"):
            if "materials" not in r:
                rep.fail("recipe materials", f"{base} craft/combine 必填 materials")
            if "inputs" in r:
                rep.fail("recipe 互斥", f"{base} craft/combine 不得写 inputs（与 materials 互斥）")
            for m in r.get("materials", []):
                if not isinstance(m, dict) or "id" not in m or "count" not in m:
                    rep.fail("recipe materials 结构", f"{base} materials 项须 {{id,count}}")
                elif not isinstance(m["count"], int) or m["count"] < 1:
                    rep.fail("recipe materials count", f"{base} {m.get('id')} count ≥1")
        elif kind == "upgrade":
            if "inputs" not in r:
                rep.fail("recipe inputs", f"{base} upgrade 必填 inputs")
            if "materials" in r:
                rep.fail("recipe 互斥", f"{base} upgrade 不得写 materials")
            if "output" not in r:
                rep.fail("recipe output", f"{base} upgrade 必填 output")
            out = r.get("output")
            if isinstance(out, dict) and out.get("count") != 1:
                rep.fail("recipe output.count", f"{base} upgrade output.count 须=1")
            for ipt in r.get("inputs", []):
                if not isinstance(ipt, dict) or "item" not in ipt or "count" not in ipt:
                    rep.fail("recipe inputs 结构", f"{base} inputs 项须 {{item,count}}")
                elif not isinstance(ipt["count"], int) or ipt["count"] < 1:
                    rep.fail("recipe inputs count", f"{base} {ipt.get('item')} count ≥1")
        cost = r.get("cost")
        if cost is not None:
            if not isinstance(cost, dict) or not set(cost).issubset({"coins", "gem"}):
                rep.fail("recipe cost", f"{base} cost 须 {{coins,gem}}")
            else:
                for ck in ("coins", "gem"):
                    if ck in cost and (not isinstance(cost[ck], (int, float)) or cost[ck] < 0):
                        rep.fail("recipe cost 非负", f"{base} cost.{ck} 非负")
        ti = r.get("traits_inherit")
        if ti is not None and (not isinstance(ti, int) or not (1 <= ti <= 3)):
            rep.fail("recipe traits_inherit", f"{base} traits_inherit 须 1-3")
        for bk in ("synth_allowed", "master_only"):
            if bk in r and not isinstance(r[bk], bool):
                rep.fail("recipe bool", f"{base} {bk} 须布尔")
        if "evolve_to" in r:
            ev = r["evolve_to"]
            if not isinstance(ev, dict) or "id" not in ev:
                rep.fail("recipe evolve_to", f"{base} evolve_to 须 {{id,condition}}")
            else:
                cond = ev.get("condition", {})
                if not isinstance(cond.get("count"), int) or cond.get("count", 0) < 1:
                    rep.fail("recipe evolve_to.condition", f"{base} condition.count ≥1")
                if not isinstance(cond.get("source"), str) or not cond.get("source"):
                    rep.fail("recipe evolve_to.source",
                             f"{base} condition.source 非空字符串（枚举以 0A 校验器为准）")


def check_traits_schema(traits: list[dict], rep: Reporter) -> None:
    for i, t in enumerate(traits):
        base = f"traits[{i}]({t.get('id', '?')})"
        for k in ("id", "name", "rarity", "effects", "source"):
            if k not in t:
                rep.fail("traits 必填键", f"{base} 缺 {k}")
        if "id" in t and any(c in t["id"] for c in "* ,=+"):
            rep.fail("traits id 命名", f"{base} 含保留字符 * , = + 空格")
        if t.get("rarity") not in TRAIT_RARITY:
            rep.fail("traits rarity", f"{base} rarity 须 normal|super")
        if t.get("source") not in TRAIT_SOURCE:
            rep.fail("traits source", f"{base} source 须 素材|成品|金色素材")
        if "repeatable" in t and not isinstance(t["repeatable"], bool):
            rep.fail("traits repeatable", f"{base} repeatable 须布尔")
        if not isinstance(t.get("effects"), list):
            rep.fail("traits effects", f"{base} effects 须数组")


def check_proficiency_schema(prof: list[dict], rep: Reporter) -> None:
    for i, p in enumerate(prof):
        base = f"proficiency[{i}]({p.get('id', '?')})"
        for k in ("id", "tier_names", "job_rank_levels", "exp_sources",
                  "sp_per_level", "sp_panel", "energy", "titles"):
            if k not in p:
                rep.fail("proficiency 必填键", f"{base} 缺 {k}")
        tn = p.get("tier_names", [])
        jrl = p.get("job_rank_levels", [])
        if not isinstance(tn, list) or len(tn) < 2:
            rep.fail("proficiency tier_names", f"{base} tier_names 长度 ≥2")
        if not isinstance(jrl, list) or len(jrl) != len(tn):
            rep.fail("proficiency job_rank_levels",
                     f"{base} job_rank_levels 与 tier_names 一一对应")
        elif jrl and (jrl[0] != 0 or any(b <= a for a, b in zip(jrl, jrl[1:]))):
            rep.fail("proficiency 单调", f"{base} job_rank_levels 单调递增且首项=0")
        es = p.get("exp_sources", {})
        if isinstance(es, dict):
            for k in ("craft", "gather", "combat"):
                if k not in es or (not isinstance(es[k], (int, float)) or es[k] < 0):
                    rep.fail("proficiency exp_sources", f"{base} exp_sources.{k} 缺或 <0")
        if not isinstance(p.get("sp_per_level"), int) or p["sp_per_level"] < 0:
            rep.fail("proficiency sp_per_level", f"{base} sp_per_level 非负整数")
        panel = p.get("sp_panel", [])
        if isinstance(panel, list):
            seen = set()
            for item in panel:
                if not isinstance(item, dict) or not SP_PANEL_KEYS.issubset(item):
                    rep.fail("proficiency sp_panel", f"{base} sp_panel 项缺键 {SP_PANEL_KEYS}")
                    continue
                if item["id"] in seen:
                    rep.fail("proficiency sp_panel", f"{base} sp_panel id 重复 {item['id']}")
                seen.add(item["id"])
                if (item.get("cost", 0) < 1
                        or not isinstance(item.get("repeatable"), bool)
                        or item.get("max_repeat", 0) < 1):
                    rep.fail(
                        "proficiency sp_panel 字段",
                        f"{base} sp_panel 项 cost≥1/repeatable bool/max_repeat≥1",
                    )
        e = p.get("energy")
        if isinstance(e, dict):
            if not isinstance(e.get("enabled"), bool):
                rep.fail("proficiency energy", f"{base} energy.enabled 须布尔")
            if e.get("enabled") is True:
                if (not isinstance(e.get("max_by_tier"), list)
                        or len(e.get("max_by_tier", [])) != len(tn)):
                    rep.fail("proficiency energy",
                             f"{base} energy.max_by_tier 长度与 tier_names 一致")
            if not isinstance(e.get("regen_sec"), int) or e.get("regen_sec", 0) < 0:
                rep.fail("proficiency energy", f"{base} energy.regen_sec ≥0")
        jtm = p.get("job_tier_map")
        if isinstance(jtm, dict):
            tiers = list(jtm.keys())
            if tiers != list(tn):
                rep.fail("proficiency job_tier_map",
                         f"{base} job_tier_map 称号须与 tier_names 一致")
            prev_hi = 0
            for t in tiers:
                rng = jtm[t]
                if not (isinstance(rng, list) and len(rng) == 2 and rng[0] <= rng[1]):
                    rep.fail("proficiency job_tier_map", f"{base} {t} 区间非法")
                    continue
                if rng[0] <= prev_hi:
                    rep.fail("proficiency job_tier_map", f"{base} {t} 区间不单调")
                prev_hi = rng[1]
        titles = p.get("titles", [])
        if isinstance(titles, list):
            for t in titles:
                if not isinstance(t, dict) or not TITLE_KEYS.issubset(t):
                    rep.fail("proficiency titles", f"{base} titles 项缺键 {TITLE_KEYS}")
                    continue
                if t.get("source") not in TITLE_SOURCES:
                    rep.fail("proficiency titles.source", f"{base} source={t.get('source')!r} 非法")
                if t.get("source") == "king":
                    rep.fail("proficiency titles.king", f"{base} king 条目应自动生成、不手写配置")


def check_slots_schema(slots: list[dict], rep: Reporter) -> None:
    for i, s in enumerate(slots):
        base = f"slots[{i}]({s.get('equip_id', '?')})"
        if "equip_id" not in s or "slots" not in s:
            rep.fail("slots 必填键", f"{base} 缺 equip_id/slots")
            continue
        for sl in s["slots"]:
            if (not isinstance(sl, dict)
                    or not isinstance(sl.get("slot_level"), int)
                    or not (1 <= sl["slot_level"] <= 3)):
                rep.fail("slots slot_level", f"{base} slot_level 须 1-3")


def check_items_schema(items: list[dict], rep: Reporter) -> None:
    for i, it in enumerate(items):
        base = f"items[{i}]({it.get('id', '?')})"
        if "id" not in it or "name" not in it or "type" not in it:
            rep.fail("items 必填键", f"{base} 缺 id/name/type")
        if it.get("type") == "装饰珠":
            if it.get("quality") not in QUALITY_KEYS:
                rep.fail("装饰珠 quality", f"{base} quality 须 ∈ {sorted(QUALITY_KEYS)}")
            if not isinstance(it.get("base_effects"), dict) or not it["base_effects"]:
                rep.fail("装饰珠 base_effects", f"{base} base_effects 必填非空对象")
            if not isinstance(it.get("traits"), list) or not it["traits"]:
                rep.fail("装饰珠 traits", f"{base} traits 必填非空数组")
        el = it.get("elements")
        if el is not None:
            if not isinstance(el, dict):
                rep.fail("items elements", f"{base} elements 须对象")
            elif not set(el).issubset(ELEMENTS):
                rep.fail("items elements 键",
                         f"{base} elements 键须 ∈ 8 元素注册表，实际 {sorted(el)}")


# ---------------------------------------------------------------------------
# ③ 包内引用自洽
# ---------------------------------------------------------------------------
def check_refs(pack: str, data: dict[str, Any], rep: Reporter) -> None:
    item_ids = get_ids(data.get("items")) | get_ids(data.get("equipment"))
    recipe_ids = get_ids(data.get("recipe"))
    effect_ids = (get_ids(data.get("effects"))
                  | get_ids(data.get("statuses"))
                  | get_ids(data.get("marks")))
    trait_ids = get_ids(data.get("traits"))

    for r in data.get("recipe", []) or []:
        rid = r.get("id", "?")
        for m in r.get("materials", []) or []:
            if m.get("id") not in item_ids:
                rep.fail("引用自洽",
                         f"[{pack}] recipe {rid} materials.{m.get('id')} 不在本包 items")
        for ipt in r.get("inputs", []) or []:
            if ipt.get("item") not in item_ids:
                rep.fail("引用自洽",
                         f"[{pack}] recipe {rid} inputs.{ipt.get('item')} 不在本包 items")
        out = r.get("output")
        if isinstance(out, dict) and out.get("item") not in item_ids:
            rep.fail("引用自洽", f"[{pack}] recipe {rid} output.{out.get('item')} 不在本包 items")
        for c in r.get("catalyst", []) or []:
            if c not in item_ids:
                rep.fail("引用自洽", f"[{pack}] recipe {rid} catalyst.{c} 不在本包 items")
            elif c not in {
                it["id"] for it in (data.get("items") or [])
                if isinstance(it, dict) and it.get("type") == "触媒"
            }:
                rep.fail("引用自洽", f"[{pack}] recipe {rid} catalyst.{c} 非 type=触媒")
        for cf in r.get("combine_from", []) or []:
            if cf not in recipe_ids:
                rep.fail("引用自洽", f"[{pack}] recipe {rid} combine_from.{cf} 不在本包 recipe")
        ev = r.get("evolve_to")
        if isinstance(ev, dict) and ev.get("id") not in recipe_ids:
            rep.fail("引用自洽", f"[{pack}] recipe {rid} evolve_to.{ev.get('id')} 不在本包 recipe")
        er = r.get("element_req")
        if isinstance(er, dict):
            for elem, conds in er.items():
                if elem not in ELEMENTS:
                    rep.fail("元素注册表",
                             f"[{pack}] recipe {rid} element_req.{elem} 不在 8 元素注册表")
                for cond in conds or []:
                    if isinstance(cond, dict) and cond.get("effect") not in effect_ids:
                        rep.fail(
                            "引用自洽",
                            f"[{pack}] recipe {rid} element_req.{elem}.effect "
                            "不在本包效果家族",
                        )

    for t in data.get("traits", []) or []:
        for eff in t.get("effects", []) or []:
            if eff not in effect_ids:
                rep.fail("引用自洽", f"[{pack}] trait {t.get('id')} effects.{eff} 不在本包效果家族")

    for s in data.get("slots", []) or []:
        if s.get("equip_id") not in item_ids:
            rep.fail("引用自洽", f"[{pack}] slots {s.get('equip_id')} 不在本包 items/equipment")

    for it in data.get("items", []) or []:
        for tr in it.get("traits", []) or []:
            if tr not in trait_ids:
                rep.fail("引用自洽", f"[{pack}] item {it.get('id')} traits.{tr} 不在本包 traits")


# ---------------------------------------------------------------------------
# ④ 进化线无环（DFS）
# ---------------------------------------------------------------------------
def check_acyclic(pack: str, data: dict[str, Any], rep: Reporter) -> None:
    edges: dict[str, str] = {}
    for r in data.get("recipe", []) or []:
        ev = r.get("evolve_to")
        if isinstance(ev, dict) and ev.get("id"):
            edges[str(r["id"])] = str(ev["id"])
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in edges}
    stack: list[str] = []

    def dfs(n: str) -> bool:
        color[n] = GRAY
        stack.append(n)
        nxt = edges.get(n)
        if nxt and color.get(nxt, WHITE) == GRAY:
            rep.fail("进化线无环", f"[{pack}] 成环: {' -> '.join(stack + [nxt])}")
            return True
        if nxt and color.get(nxt, WHITE) == WHITE and dfs(nxt):
            return True
        stack.pop()
        color[n] = BLACK
        return False

    for n in list(edges):
        if color[n] == WHITE:
            dfs(n)


# ---------------------------------------------------------------------------
# ⑥ manifest modules 与磁盘 json 一一对应
# ---------------------------------------------------------------------------
def check_manifest(pack_dir: Path, rep: Reporter) -> None:
    manifest = load_json(pack_dir / "manifest.json")
    declared = [m for m in manifest.get("modules", []) if isinstance(m, str)]
    disk = sorted(f.stem for f in pack_dir.glob("*.json") if f.name != "manifest.json")
    missing = sorted(set(declared) - set(disk))
    undeclared = sorted(set(disk) - set(declared))
    for m in missing:
        rep.fail("manifest 声明缺失", f"声明但缺文件: {m}")
    for f in undeclared:
        rep.fail("manifest 未声明文件", f"磁盘文件未声明: {f}.json")


# ---------------------------------------------------------------------------
# ⑦ settings.alchemy 段键值类型
# ---------------------------------------------------------------------------
def check_settings_alchemy(pack: str, data: dict[str, Any], rep: Reporter) -> None:
    settings = data.get("settings")
    if not isinstance(settings, dict):
        rep.fail("settings", f"[{pack}] settings 缺失")
        return
    currencies = settings.get("currencies", [])
    cur_ids = {c.get("id") for c in currencies if isinstance(c, dict)}
    if "gem" not in cur_ids:
        rep.fail("settings gem 货币", f"[{pack}] currencies 缺 gem（reward 发放器依赖登记）")
    al = settings.get("alchemy")
    if not isinstance(al, dict):
        rep.fail("settings.alchemy", f"[{pack}] alchemy 段缺失")
        return

    def need_str(key: str, allowed: set[str] | None = None) -> None:
        v = al.get(key)
        if not isinstance(v, str):
            rep.fail("settings.alchemy 类型", f"[{pack}] {key} 须字符串")
        elif allowed is not None and v not in allowed:
            rep.fail("settings.alchemy 枚举", f"[{pack}] {key}={v!r} 不在 {sorted(allowed)}")

    need_str("mode", {"full", "simple", "off"})
    need_str("pp_refresh", {"会话重置"})
    need_str("catalyst_unlock_tier", set(TIERS) | {"expert"})
    need_str("synth_exp")

    for key, chk in (
        ("energy_enabled", lambda v: isinstance(v, bool)),
        ("catalyst_consume", lambda v: isinstance(v, bool)),
        ("sp_per_level", lambda v: isinstance(v, int) and v >= 0),
        ("energy_regen_sec", lambda v: isinstance(v, int) and v >= 0),
        ("energy_regen_sec_safe", lambda v: isinstance(v, int) and v >= 0),
        ("max_qty", lambda v: isinstance(v, int) and v > 0),
    ):
        if key not in al:
            rep.fail("settings.alchemy 缺键", f"[{pack}] alchemy.{key} 缺失")
        elif not chk(al[key]):
            rep.fail("settings.alchemy 类型", f"[{pack}] alchemy.{key} 类型/取值错误")

    qt = al.get("quality_tiers")
    if isinstance(qt, dict):
        if set(qt) != QUALITY_KEYS:
            rep.fail("settings.alchemy quality_tiers", f"[{pack}] 键须 {sorted(QUALITY_KEYS)}")
        else:
            bounds = [v for k in ("common", "uncommon", "rare", "legendary") for v in qt[k]]
            if any(not (isinstance(b, int)) for b in bounds) or bounds != sorted(bounds):
                rep.fail("settings.alchemy quality_tiers", f"[{pack}] 区间未单调覆盖 0-100")
    else:
        rep.fail("settings.alchemy quality_tiers", f"[{pack}] 缺失/非对象")

    qc = al.get("quality_coef")
    if not (isinstance(qc, dict) and set(qc) == QUALITY_KEYS
            and all(isinstance(v, (int, float)) and v > 0 for v in qc.values())):
        rep.fail("settings.alchemy quality_coef", f"[{pack}] 键须 4 档、数值 >0")

    cm = al.get("chain_map")
    if not (isinstance(cm, dict) and all(isinstance(v, int) and 1 <= v <= 6 for v in cm.values())):
        rep.fail("settings.alchemy chain_map", f"[{pack}] 值须 ∈1-6 整数")

    pc = al.get("pp_cost")
    if not (isinstance(pc, dict) and set(pc) == {"normal", "super"}
            and all(isinstance(v, int) and v > 0 for v in pc.values())):
        rep.fail("settings.alchemy pp_cost", f"[{pack}] 须 {{normal,super}} 正整数")

    em = al.get("energy_max")
    if not (isinstance(em, dict) and set(em) == set(TIERS)
            and all(isinstance(v, int) and v >= 0 for v in em.values())):
        rep.fail("settings.alchemy energy_max", f"[{pack}] 须 7 档非负整数")

    dr = al.get("decompose_rate")
    if not (isinstance(dr, dict) and set(dr) == {"正式", "精通", "专家", "大师", "宗师", "王"}):
        rep.fail("settings.alchemy decompose_rate", f"[{pack}] 须 6 档（见习起）")
    elif any(not (isinstance(v, (int, float)) and 0 < v <= 1) for v in dr.values()):
        rep.fail("settings.alchemy decompose_rate", f"[{pack}] ratio 须 ∈(0,1]")

    gem_keys = set(GEM_DOTTED_KEYS)
    if not gem_keys.issubset(al):
        rep.fail(
            "settings.alchemy gem",
            f"[{pack}] 缺 gem 点号键（契约 §五："
            "gem.分解/复制/成品合成/配方合成/特性合成/珠升阶/复制额外/decompose_formula）",
        )
    else:
        dec = al["gem.分解"]
        if not (isinstance(dec, dict) and set(dec) == QUALITY_KEYS
                and all(isinstance(v, int) and v >= 0 for v in dec.values())):
            rep.fail("settings.alchemy gem.分解", f"[{pack}] 须 4 档非负整数")
        if not (isinstance(al["gem.复制"], (int, float)) and al["gem.复制"] >= 0):
            rep.fail("settings.alchemy gem.复制", f"[{pack}] 须非负数（可浮点）")
        for k in ("成品合成", "配方合成", "特性合成", "珠升阶", "复制额外"):
            if not (isinstance(al[f"gem.{k}"], int) and al[f"gem.{k}"] >= 0):
                rep.fail("settings.alchemy gem", f"[{pack}] gem.{k} 须非负整数")
        if "gem.秘钥" in al:
            rep.fail("settings.alchemy gem.秘钥", f"[{pack}] gem.秘钥 已砍，不得出现")

    gd = al.get("gem_diminish")
    if not (isinstance(gd, list) and all(
        isinstance(d, dict) and isinstance(d.get("n"), int) and d["n"] >= 2
        and isinstance(d.get("mult"), (int, float)) and 0 < d["mult"] <= 1
        for d in gd
    )):
        rep.fail("settings.alchemy gem_diminish", f"[{pack}] 须 [{{n≥2, mult∈(0,1]}}]")

    sp = al.get("sp_panel")
    if not (isinstance(sp, list) and len(sp) >= 1):
        rep.fail("settings.alchemy sp_panel", f"[{pack}] 缺失")
    elif any(not (isinstance(i, dict) and SP_PANEL_KEYS.issubset(i)
                  and isinstance(i.get("repeatable"), bool)) for i in sp):
        rep.fail("settings.alchemy sp_panel", f"[{pack}] 项须含 {SP_PANEL_KEYS} 且 repeatable 布尔")

    bq = al.get("战斗道具")
    if not (isinstance(bq, dict) and isinstance(bq.get("强度公式"), str)
            and isinstance(bq.get("珠触发上限"), int) and bq.get("珠触发上限", 0) >= 1):
        rep.fail("settings.alchemy 战斗道具", f"[{pack}] 强度公式字符串 + 珠触发上限 ≥1")

    bi = al.get("战斗即时调合")
    if not (isinstance(bi, dict) and isinstance(bi.get("auto_use"), bool)
            and isinstance(bi.get("per_battle_limit"), int) and bi.get("per_battle_limit", 0) >= 1):
        rep.fail("settings.alchemy 战斗即时调合", f"[{pack}] auto_use 布尔 + per_battle_limit ≥1")

    jtm = al.get("job_tier_map")
    if not (isinstance(jtm, dict) and set(jtm) == set(TIERS)):
        rep.fail("settings.alchemy job_tier_map", f"[{pack}] 须 7 档称号")
    elif any(not (isinstance(v, list) and len(v) == 2 and v[0] <= v[1]) for v in jtm.values()):
        rep.fail("settings.alchemy job_tier_map", f"[{pack}] 区间非法")


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def run_pack(name: str, pack_dir: Path) -> int:
    rep = Reporter(name)
    data = parse_pack(pack_dir, rep)
    if data is None:
        rep.fail("JSON 可解析", "存在不可解析 JSON，跳过后续检查")
    else:
        rep.ok("JSON 可解析", f"{len(data)} 个模块文件")
        recipes = data.get("recipe") or []
        if isinstance(recipes, list):
            check_recipe_schema(recipes, rep)
            rep.ok("recipe 必填键/值域", f"{len(recipes)} 条配方")
        traits = data.get("traits") or []
        if isinstance(traits, list):
            check_traits_schema(traits, rep)
            rep.ok("traits 必填键/值域", f"{len(traits)} 条特性")
        prof = data.get("proficiency") or []
        if isinstance(prof, list):
            check_proficiency_schema(prof, rep)
            rep.ok("proficiency 必填键/值域", f"{len(prof)} 个职业")
        slots = data.get("slots") or []
        if isinstance(slots, list):
            check_slots_schema(slots, rep)
            rep.ok("slots 必填键/值域", f"{len(slots)} 件装备")
        items = data.get("items") or []
        if isinstance(items, list):
            check_items_schema(items, rep)
            rep.ok("items/装饰珠 必填键", f"{len(items)} 个物品")
        err0 = len(rep.errors)
        check_refs(name, data, rep)
        if len(rep.errors) == err0:
            rep.ok("包内引用自洽", "recipe/traits/slots 引用全部指向本包真实 ID")
        check_acyclic(name, data, rep)
        if len(rep.errors) == err0:
            rep.ok("进化线无环", "DFS 未发现 evolve_to 成环")
        check_manifest(pack_dir, rep)
        if len(rep.errors) == err0:
            rep.ok("manifest ↔ 磁盘文件", "声明与磁盘 json 一一对应")
        check_settings_alchemy(name, data, rep)
        if len(rep.errors) == err0:
            rep.ok("settings.alchemy 段", "键值/类型/默认值照契约 §五 全字段表")

    print(f"\n===== pack: {name} =====")
    for c in rep.checks:
        print(f"  {c}")
    if rep.errors:
        for e in rep.errors:
            print(f"  {e}")
        print(f"  >>> {len(rep.errors)} 个失败项")
    else:
        print("  >>> 全部通过")
    return len(rep.errors)


def main() -> int:
    total_fail = 0
    for name, pack_dir in PACKS.items():
        if not pack_dir.exists():
            print(f"[FAIL] 包目录不存在: {pack_dir}")
            total_fail += 1
            continue
        fails = run_pack(name, pack_dir)
        total_fail += fails
    print(f"\n===== 汇总 =====\n两包失败项合计: {total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

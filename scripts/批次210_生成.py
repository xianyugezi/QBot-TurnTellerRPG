# -*- coding: utf-8 -*-
"""九期批次 210 生成：content/cloudsea/ 内容包骨架
manifest 22 模块（沿 veinborn 单包铁律）＋editor.json（enemies/action 大模块页停用）
＋settings/stats 首版（208 产物口径对齐）＋smoke 装载验证。
既有在途文件（axes/effects/formula/statuses，211–213 产出）零触碰。
"""
import asyncio
import io
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "content" / "cloudsea"
VB = ROOT / "content" / "veinborn"
DEMO = ROOT / "content" / "test_demo"

def wj(p: Path, obj):
    io.open(p, "w", encoding="utf-8", newline="\n").write(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n")

# 1) manifest.json —— 22 模块沿 veinborn（单包铁律：零·7）
vb_manifest = json.load(io.open(VB / "manifest.json", encoding="utf-8"))
manifest = {
    "name": "云海猎团 Cloudsea Hunting Corps（内容包）",
    "version": "0.1.0",
    "schema_version": 1,
    "author": "yunhai-design",
    "modules": list(vb_manifest["modules"]),
}
assert len(manifest["modules"]) == 22
wj(PACK / "manifest.json", manifest)
print("manifest.json：22 模块", manifest["modules"][:5], "...")

# 2) editor.json —— 沿 test_demo 页表条目；enemies(monster)/action 大模块页停用
demo_ed = json.load(io.open(DEMO / "editor.json", encoding="utf-8"))
by_id = {p["page_id"]: p for p in demo_ed["pages"]}
WANT = ["formula", "statuses", "effects", "stats", "settings"]   # 现有模块页（首版）
pages = []
for pid in WANT:
    src = by_id.get(pid)
    assert src, f"test_demo 缺页 {pid}"
    pages.append({k: src[k] for k in ("page_id", "title", "icon", "module_file",
                                      "meta_source", "enabled", "validator")})
for pid in ("monster", "action"):   # 大模块页停用（任务书口径）
    src = by_id.get(pid)
    assert src, f"test_demo 缺页 {pid}"
    d = {k: src[k] for k in ("page_id", "title", "icon", "module_file",
                             "meta_source", "enabled", "validator")}
    d["enabled"] = False
    pages.append(d)
editor = {"schema_version": 1, "pages": pages}
wj(PACK / "editor.json", editor)
print("editor.json：", len(pages), "页（停用:", [p["page_id"] for p in pages if not p["enabled"]], "）")

# 3) settings.json 首版 —— 引擎 settings schema 最小面（settings_1g4 校验合规：
#    currencies[].id 定义币空间；无 death_penalty 段＝F-02 面不启用；无战斗超时类键）
settings = {
    "world_name": "云海猎团·云海之上",
    "level_cap": 10,
    "currencies": [
        {"id": "gold", "name": "金标", "icon": "🪙"},
        {"id": "honor", "name": "公会勋", "icon": "🏅"},
        {"id": "ticket", "name": "航券", "icon": "🎟️"},
    ],
}
wj(PACK / "settings.json", settings)
print("settings.json：level_cap=$C.LEVEL_MAX(10)＋三币（金标/公会勋/航券，映射#24）")

# 4) stats.json 首版 —— veinborn 基线原样承载（引擎 stat_map 兼容骨架；
#    云海数值重校归 211 速度流/221 职业批，本批只落骨架不落数值改判）
vb_stats = json.load(io.open(VB / "stats.json", encoding="utf-8"))
wj(PACK / "stats.json", vb_stats)
print("stats.json：veinborn 基线原样", len(vb_stats), "键（首版骨架）")

# 5) smoke：骨架包独立装载（本批四件 → 临时包目录 load 全流程）。
#    全包直装当前被 211/212/213 在途件（formula.json rng_band R-1 等）阻断——
#    归属批收尾后 content/cloudsea/ 全包 smoke 复跑（登记 210 断言 D-3）。
sys.path.insert(0, str(ROOT))
import shutil

async def _load(p: Path):
    from qbot_rpg.content.loader import build_pack
    from qbot_rpg.content.field_meta import default_field_meta_table
    return build_pack(p, default_field_meta_table(), None, 1)

tmp = PACK.parent / "_cloudsea_smoke_210"
tmp.mkdir(parents=True, exist_ok=True)
try:
    for f in ("manifest.json", "editor.json", "settings.json", "stats.json"):
        shutil.copy(PACK / f, tmp / f)
    pack, _ = asyncio.run(_load(tmp))
    mods = sorted((getattr(pack, "registry", None).modules_raw or {}).keys())
    print("smoke OK（骨架包独立装载）：modules =", mods)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

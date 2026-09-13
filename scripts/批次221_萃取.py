# -*- coding: utf-8 -*-
"""九期批次 221 萃取（跨轮增量 · 本轮＝萃取管线＋jobs 骨架）：
13_职业数值卡 14 卡 → 结构化草稿（§1 概览/§2 资源/§3 基础动作表/§4 战技表/§5 绝技表）
输出＝设计稿仓 生产日志/九期/批次221_萃取.out.txt（人工复核面）
       TTR content/cloudsea/jobs.json（14 职业元数据骨架，技能面随下轮增量）
"""
import io, json, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
CARDS = Path(r"D:\1V1TXTRPG\yunhai\cloudsea-hunting-corps\13_职业数值卡")
OUTLOG = Path(r"D:\1V1TXTRPG\yunhai\cloudsea-hunting-corps\生产日志\九期\批次221_萃取.out.txt")

JOB_IDS = {  # 14 职业稳定 id（英文卡名小写）
    "战士": "warrior", "剑客": "duelist", "圣骑士": "paladin", "盗贼": "rogue",
    "斗士": "brawler", "吟游诗人": "bard", "骑士": "knight", "枪手": "gunner",
    "狂战士": "berserker", "守卫": "guardian", "德鲁伊": "druid", "游侠": "ranger",
    "机械师": "artificer", "弓手": "archer",
}
WPN_IDS = {  # 偏好武器 → weapon id（词表沿 engine 武器类型；veinborn 先例 ridgeblade 等）
    "巨剑": "greatsword", "长刀": "longblade", "剑盾": "swordshield", "双刃": "dualblades",
    "战锤": "warhammer", "号角": "horn", "长枪": "lance", "晶铳": "crystalgun",
    "战斧": "waraxe", "战盾": "wardshield", "法杖": "staff", "轻弩": "lightbow",
    "重弩": "heavybow", "长弓": "longbow",
}

def section(txt, title_start):
    """取 `## N · <title_start>` 段到下一 `## ` 的正文。"""
    m = re.search(r"^## \d+[^\n]*" + title_start + r"[^\n]*\n(.*?)(?=^## \d+|\Z)", txt, re.S | re.M)
    return m.group(1).strip() if m else ""

def table_rows(sec):
    """粗提 markdown 表数据行（首列非空、含 |）。"""
    rows = []
    for ln in sec.splitlines():
        ln = ln.strip()
        if ln.startswith("|") and not ln.startswith("|:--") and not ln.startswith("|---"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if cells and cells[0] and cells[0] not in ("动作名", "战技名", "绝技名", "字段", "维度"):
                rows.append(cells)
    return rows

jobs = []
log = []
for card in sorted(CARDS.glob("[0-1][0-9]_*.md")):
    if card.stem.startswith("00"):
        continue  # 00＝规格契约，非卡
    txt = io.open(card, encoding="utf-8").read()
    s1 = section(txt, "职业概览")
    s2 = section(txt, "专属资源")
    s3 = section(txt, "基础动作表")
    s4 = section(txt, "战技表")
    s5 = section(txt, "绝技表")
    # §1 概览＝键值表（| 键 | 值 |），逐行抓已知键
    kv = {}
    for ln in s1.splitlines():
        m = re.match(r"^\|\s*(中文名|英文名|定位|节奏|偏好武器|专属资源名|核心特色|生态位)\s*\|\s*([^|]+?)\s*\|", ln)
        if m:
            kv.setdefault(m.group(1), m.group(2).strip())
    name = kv.get("中文名", card.stem.split("_")[1])
    en = card.stem.split("_")[-1].lower()
    jid = JOB_IDS.get(name, en)
    job = {
        "id": jid, "name": name, "card": card.name,
        "weapon_types": [kv["偏好武器"]] if "偏好武器" in kv else [],
        "resource_name": kv.get("专属资源名", ""),
        "playstyle": kv.get("定位", ""),
        "counts": {"基础动作": len(table_rows(s3)), "战技": len(table_rows(s4)), "绝技": len(table_rows(s5))},
    }
    jobs.append(job)
    log.append(f"== {card.name}｜{name}｜{jid}｜武器={job['weapon_types']}｜资源={job['resource_name']}｜计数={job['counts']}")

log.append(f"jobs 萃取 {len(jobs)}/14")
# jobs.json＝裸数组（jobs 校验器 module_structure expect list；V1 键面＝jobs_fields
# 34 键登记表——本骨架只出登记键 id/name/weapon_types/playstyle，weapon id 沿
# WPN_IDS 词表；resource_name/card 系萃取工作单字段不入数据文件）
out = []
for job in jobs:
    pref = next(iter(job["weapon_types"]), "")
    wpn = next((v for k, v in WPN_IDS.items() if k in pref), "")
    out.append({"id": job["id"], "name": job["name"],
                "weapon_types": [wpn] if wpn else [],
                "playstyle": job["playstyle"]})
io.open(ROOT / "content/cloudsea/jobs.json", "w", encoding="utf-8", newline="\n").write(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print("jobs.json 骨架落盘（", len(out), "jobs）")
io.open(OUTLOG, "w", encoding="utf-8", newline="\n").write(
    "批次 221 萃取（跨轮增量）\n" + "=" * 60 + "\n" + "\n".join(log) + "\n")

# -*- coding: utf-8 -*-
"""九期批次 221 增量二：content/cloudsea/skills.json（§4 战技表＋§5 绝技表 → 引擎 35 键契约）
保守映射：power=M×100／hits 段数／mp_cost=消耗首位数值（首版近似，工作单登记）／
position_rule 仅对空显式落 requires_target_height=air；保底位＝全职业通用池（job_restrict=[]，
跨卡去重）。链面 skill_chains 随后继增量。
"""
import io, json, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
CARDS = Path(r"D:\1V1TXTRPG\yunhai\cloudsea-hunting-corps\13_职业数值卡")
OUTLOG = Path(r"D:\1V1TXTRPG\yunhai\cloudsea-hunting-corps\生产日志\九期\批次221_萃取.out.txt")

JOB_IDS = {"战士": "warrior", "剑客": "duelist", "圣骑士": "paladin", "盗贼": "rogue",
           "斗士": "brawler", "吟游诗人": "bard", "骑士": "knight", "枪手": "gunner",
           "狂战士": "berserker", "守卫": "guardian", "德鲁伊": "druid", "游侠": "ranger",
           "机械师": "artificer", "弓手": "archer"}

def section(txt, title_start):
    m = re.search(r"^## \d+[^\n]*" + title_start + r"[^\n]*\n(.*?)(?=^## \d+|\Z)", txt, re.S | re.M)
    return m.group(1).strip() if m else ""

def rows_of(sec):
    out = []
    for ln in sec.splitlines():
        ln = ln.strip()
        if ln.startswith("|") and not re.match(r"^\|[:\-\s|]+\|$", ln):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if cells and cells[0] and cells[0] not in ("战技名", "绝技名", "战技", "绝技", "名称"):
                out.append(cells)
    return out

def num(x, default=0):
    m = re.search(r"(\d+\.?\d*)", x or "")
    return float(m.group(1)) if m else default

def parse_m(cells):
    """M 值识别：扫描行内单元格，取首个落在 $C.BATTLE.MULT_M 带 [0.6,3.2] 的纯数；
    找不到 → 0（utility）。V-13 power≤500 由 ×100 后天然满足（≤320）。"""
    for c in cells:
        c = c.strip()
        if re.fullmatch(r"[×x]?\d(\.\d+)?", c):
            v = float(c.lstrip("×x"))
            if 0.6 <= v <= 3.2:
                return v
        m = re.search(r"[Mm倍]\s*[=＝]?\s*(\d\.\d+)", c)
        if m:
            v = float(m.group(1))
            if 0.6 <= v <= 3.2:
                return v
    return 0.0

skills = []
seen = {}
log = []
gseq = 0  # 通用池（保底）全局序号：跨卡唯一
for card in sorted(CARDS.glob("[0-1][0-9]_*.md")):
    if card.stem.startswith("00"):
        continue
    txt = io.open(card, encoding="utf-8").read()
    name = None
    for ln in section(txt, "职业概览").splitlines():
        m = re.match(r"^\|\s*中文名\s*\|\s*([^|]+?)\s*\|", ln)
        if m:
            name = m.group(1).strip()
    jid = JOB_IDS.get(name, card.stem.split("_")[-1].lower())
    n0 = len(skills)
    k = 0  # 战技序（确定性 id）
    # §4 战技表：主/副＝职业专属；保底＝通用池（去重）
    for cells in rows_of(section(txt, "战技表")):
        if len(cells) < 4:
            continue
        sname = cells[0].strip("**").strip()
        slot = cells[1] if len(cells) > 1 else ""
        mrow = cells[2] if len(cells) > 2 else ""
        fx = cells[3] if len(cells) > 3 else ""
        cost = cells[4] if len(cells) > 4 else ""
        generic = "保底" in slot
        key = sname
        if generic and key in seen:
            continue
        gseq += 1
        k += 1
        M = parse_m(cells)
        hits = 1
        hm = re.search(r"(\d+)\s*段", mrow + fx)
        if hm:
            hits = max(1, int(hm.group(1)))
        sk = {
            "id": (f"common_s{gseq:03d}" if generic else f"{jid}_s{k:03d}"),
            "name": sname,
            "type": "active",
            "kind": "damage" if M > 0 else "utility",
            "power": int(round(M * 100)),
            "attack_type": "slash",
            "element": None,
            "effects": [],
            "mp_cost": int(num(cost, 0)),
            "cooldown": 0,
            "tag": "none",
            "armor": False,
            "interrupt": False,
            "chain_refs": [],
            "consume_marks": {},
            "job_restrict": [] if generic else [jid],
            "job_form": None,
            "level": None,
            "hits": hits,
            "trigger_limit": {"per_round": 10, "per_battle": 99},
            "desc": (fx or mrow)[:200],
            "hit_mod": 1.0, "crit_mod": 1.0, "block_mode": "auto",
        }
        if ("对空" in fx or "空中目标" in fx) and "对空" not in name:
            sk["position_rule"] = {"requires_target_height": "air"}
        skills.append(sk)
        seen[key] = True
    # §5 绝技表：职业专属
    u = 0
    for cells in rows_of(section(txt, "绝技表")):
        if len(cells) < 2:
            continue
        sname = cells[0].strip("**").strip()
        if sname in seen:
            continue
        u += 1
        fx = cells[2] if len(cells) > 2 else (cells[1] if len(cells) > 1 else "")
        M = parse_m(cells)
        skills.append({
            "id": f"{jid}_u{u:03d}",
            "name": sname, "type": "active",
            "kind": "damage" if M > 0 else "utility",
            "power": int(round(M * 100)), "attack_type": "slash", "element": None,
            "effects": [], "mp_cost": 0, "cooldown": 0, "tag": "none",
            "armor": False, "interrupt": False, "chain_refs": [], "consume_marks": {},
            "job_restrict": [jid], "job_form": None, "level": None, "hits": 1,
            "trigger_limit": {"per_round": 1, "per_battle": 9},
            "desc": fx[:200], "hit_mod": 1.0, "crit_mod": 1.0, "block_mode": "auto",
        })
        seen[sname] = True
    log.append(f"== {card.name}｜{jid}：技能 +{len(skills)-n0}（累计 {len(skills)}）")

log.append(f"skills 萃取 {len(skills)} 条（14 职业；保底通用池去重）")
io.open(ROOT / "content/cloudsea/skills.json", "w", encoding="utf-8", newline="\n").write(
    json.dumps(skills, ensure_ascii=False, indent=1) + "\n")
io.open(OUTLOG, "a", encoding="utf-8", newline="\n").write(
    "\n—— 增量二（skills.json）——\n" + "\n".join(log) + "\n")
print("skills.json 落盘：", len(skills), "条")

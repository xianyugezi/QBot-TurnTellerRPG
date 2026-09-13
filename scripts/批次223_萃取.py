# -*- coding: utf-8 -*-
"""九期批次 223 增量一：equipment/items 索引萃取（3613 把恰尽）
源＝武器名录 4 分册＋巨兽派生 22 文件＋王骸七篇＋典录 31 域；微特性＝特性映射册/00 §一类型锚定。
输出＝content/cloudsea/generated/equipment_index_223.json（结构面索引；items/equipment JSON 全量展开归增量二）。
"""
import io, json, re, sys
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
WN = Path(r"D:\1V1TXTRPG\yunhai\cloudsea-hunting-corps\18_装备与素材图鉴\武器名录")
POOL00 = WN / "特性映射册" / "00_特性池与总则.md"
OUT = ROOT / "content/cloudsea/generated/equipment_index_223.json"
TYPES = ["巨剑", "长刀", "剑盾", "双刃", "战锤", "号角", "长枪", "晶铳", "战斧", "战盾", "法杖", "轻弩", "重弩", "长弓"]

def rd(p):
    return io.open(p, encoding="utf-8").read().replace("\r\n", "\n")

pool = {}
for line in rd(POOL00).splitlines():
    m = re.match(r"^\| (\S+) \| [^|]*?(巨剑|长刀|剑盾|双刃|战锤|号角|长枪|晶铳|战斧|战盾|法杖|轻弩|重弩|长弓|通用（专械）)[^|]*\|", line)
    if m:
        pool[m.group(2)] = m.group(1)
assert len(pool) == 15

index = {"基础域": [], "巨兽派生": [], "王骸": [], "典录": []}

def scan(path, domain_label, beast_col=None, domain_override=None):
    n0 = sum(len(v) for v in index.values())
    for i, ln in enumerate(rd(path).splitlines()):
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) >= 3 and cells[2] in TYPES and cells[1] and "名" not in cells[1][:2]:
            boss = ""
            if beast_col and len(cells) > beast_col:
                bm = re.search(r"（来源：(.+?)）|（来源：(.+?)）|来源[：:](.+)", cells[beast_col])
                boss = (bm.group(1) or bm.group(2) or bm.group(3) if bm else cells[beast_col]).strip(" ：") if bm else cells[beast_col].strip()
            index[domain_label].append({
                "name": cells[1], "type": cells[2], "trait": pool[cells[2]],
                "file": path.name, "boss": boss,
            })

# 1) 基础域四分册（01 基础与专械 33／02 云兽 24／03 商店 308／04 填充 14）
for fn in ("01_基础与专械.md", "02_云兽武器.md", "03_商店武器.md", "04_填充武器.md"):
    scan(WN / fn, "基础域")
# 2) 巨兽派生（22 文件；cells[1]=类型、cells[5]=来源巨兽——260 批形态）
for p in sorted((WN / "巨兽派生").glob("*.md")):
    for ln in rd(p).splitlines():
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) >= 6 and cells[2] in TYPES:
            index["巨兽派生"].append({"name": cells[1], "type": cells[2],
                                      "trait": pool[cells[2]], "beast": cells[5], "file": p.name})
# 3) 王骸七篇（cells[1]=类型、cells[2]?=名——实测行首=名，cells[2]=类型，cells[3]=Boss）
for p in sorted((WN / "王骸").glob("*.md")):
    for ln in rd(p).splitlines():
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) >= 4 and cells[2] in TYPES:
            index["王骸"].append({"name": cells[1], "type": cells[2],
                                  "trait": pool[cells[2]], "boss": cells[3], "file": p.name})
# 4) 典录 31 活跃域
for p in sorted((WN / "典录" / "01_典录名录").glob("[0-9][0-9]_*.md")):
    if "佛道" in p.name or p.stem.startswith("00"):
        continue
    dom = re.sub(r"^\d+_", "", p.stem)
    for ln in rd(p).splitlines():
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) >= 3 and cells[2] in TYPES and cells[1] and "典录名" not in cells[1]:
            bm = re.search(r"（来源：(.+?)）", cells[7]) if len(cells) > 7 else None
            index["典录"].append({"name": cells[1], "type": cells[2], "trait": pool[cells[2]],
                                  "domain": dom, "boss": bm.group(1).strip() if bm else "", "file": p.name})

tot = {k: len(v) for k, v in index.items()}
grand = sum(tot.values())
print("索引：", tot, "合计=", grand)
assert grand == 3613, f"expected 3613 got {grand}"

names = [w["name"] for grp in index.values() for w in grp]
assert len(names) == len(set(names)), "跨域重名"

OUT.parent.mkdir(parents=True, exist_ok=True)
payload = {"_comment": "九期批次223 增量一：3613 把装备索引（结构面）。trait＝特性映射册/00 §一 类型锚定微特性（222 聚合器消费形态）。items/equipment JSON 全量展开＋forge sets 504＋王骸 7 位小套装＋符文槽位归增量二。",
           "_totals": tot, **index}
io.open(OUT, "w", encoding="utf-8", newline="\n").write(json.dumps(payload, ensure_ascii=False, indent=1) + "\n")
print("落盘：", OUT.name, "字节=", len(OUT.read_bytes()))

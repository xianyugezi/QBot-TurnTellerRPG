"""内容包校验（绕过 load_pack 阻塞，直接 check_pack 看红拦明细）。"""
import json
import os
import sys

sys.path.insert(0, "/root/QBot-TurnTellerRPG")
os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/test_demo"

from qbot_rpg.content.validator import check_pack

mods = {}
base = "/root/QBot-TurnTellerRPG/content/test_demo"
for fn in sorted(os.listdir(base)):
    if fn.endswith(".json") and fn != "manifest.json":
        mods[fn[:-5]] = json.load(open(os.path.join(base, fn), encoding="utf-8"))
report = check_pack(mods)
errs = list(report.errors or [])
warns = list(report.warnings or [])
print("errors:", len(errs), "warnings:", len(warns))
for e in errs:
    print(" ERR -", getattr(e, "module", "?"), getattr(e, "field", "?"),
          getattr(e, "kind", "?"), dict(e.detail or {}) if hasattr(e, "detail") else "")
for w in warns[:15]:
    print(" WARN -", getattr(w, "module", "?"), getattr(w, "field", "?"),
          getattr(w, "kind", "?"), dict(w.detail or {}) if hasattr(w, "detail") else "")

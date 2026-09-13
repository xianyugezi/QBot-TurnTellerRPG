# -*- coding: utf-8 -*-
"""九期242：第 1 章 MVP E2E——微澜段灰岗闭环（云海内容包全链路）。

按真实玩家流程走云海指令链：注册 → 帮（云海速查）→ 锁定灰岗 → 开战 →
攻击/防御/云海战斗指令 → 击败 → 结算。闭环判据＝战报链
「战斗开始 →（攻击/云海指令回执）→ 击败/结算」全程零未处理异常。
沿 deploy_smoke 范式（build_app_deps + run_command 逐指令收集）。
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("QBotRPG_PACK_DIR", str(_ROOT / "content" / "cloudsea"))
os.environ.setdefault("QBotRPG_DB_PATH", str(_ROOT / "data" / "e2e_cloudsea_mvp.db"))

from qbot_rpg_bridge.assemble import build_app_deps
from qbot_rpg.assembly import runner as R

FLOW = [
    "/注册",
    "/状态",
    "进入 云顶针叶林",          # 进图（微澜段第一章地图，灰岗所在）
    "锁定 1",                  # 活动怪物序号锁定（云顶针叶林怪）
    "开战",
    "攻击",                    # 基础攻击
    "局面",                    # 231 局面聚合
    "1",                       # 数字快捷主战技
    "攻击",
    "2",                       # 绝技·瞬御
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "攻击",
    "状态",
]


async def main() -> int:
    deps = await build_app_deps()
    transcript: list[str] = []

    async def say(text: str, uid: str = "u_e2e_灰岗") -> str:
        ev = {"group_id": "g_e2e", "user_id": uid, "message": text,
              "message_id": str(uuid.uuid4()), "channel": "group", "group_name": "E2E群"}
        try:
            return await asyncio.wait_for(R.run_command(ev, deps), timeout=60)
        except Exception as e:  # noqa: BLE001
            return f"[异常 {type(e).__name__}] {e}"

    for msg in FLOW:
        r = await say(msg)
        transcript.append(f">>> {msg}\n{(r or '(无回复/静默)')[:400]}\n---")

    # 灰岗闭环：循环攻击直到击败（上限 200 回合防挂死）
    for i in range(200):
        r = await say("攻击")
        transcript.append(f">>> 攻击#{i+1}\n{(r or '(无回复/静默)')[:400]}\n---")
        if "击败" in (r or "") or "战斗结束" in (r or ""):
            break

    full = "\n".join(transcript)
    out_path = Path(__file__).resolve().parent / "e2e_cloudsea_mvp_out.txt"
    out_path.write_text(full, encoding="utf-8")

    closed = ("战斗开始" in full or "开战" in full) and (
        "击败" in full or "战斗结束" in full or "结算" in full)
    boom = "[异常" in full
    print("闭环判据: %s | 异常: %s | 明细: %s" % (
        "PASS" if closed and not boom else "FAIL", boom, out_path))
    return 0 if (closed and not boom) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

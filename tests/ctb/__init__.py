"""CTB 重写契约测试包（Agent 6 · 契约守卫）。

本包只测**契约**（行为边界与不变量），不测实现细节；用于在 Agent 3 重写
`qbot_rpg/core/battle.py` 期间充当「靶子」。凡契约要求 CTB 行为但当前引擎仍是
回合制实现的用例，一律 `xfail(..., reason="待 Agent 3 实现")` 或 skip，**不降低断言强度**。
"""

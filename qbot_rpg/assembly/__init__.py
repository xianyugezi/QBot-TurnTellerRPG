"""装配层：把 M4-M6 引擎 + 指令壳 + 路由基建串成可运行完整入口（M7 A 系列）。

本层为最顶层装配：仅组装（读）不写业务，零 NoneBot import。
子模块：context.py（A-01 make_context 工厂）；router_setup / runner /
bootstrap 由 A-02~A-05 落地。
"""

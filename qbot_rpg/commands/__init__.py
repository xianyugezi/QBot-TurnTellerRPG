"""壳层适配器 commands/（唯一 NoneBot 接触点，细化_3a §1.3 / D-02）。

本包 = NoneBot 插件入口：M4 起做装配（拉起 Router/Parsers/Errors/Sender + web 子进程，
【规则】L35，「插件入口只做装配，不写业务」）。M0 阶段**零 nonebot import**
（3a R1/R2：pytest 核心层可脱离平台运行；全仓 import nonebot 仅允许本包与入口装配文件）。
"""

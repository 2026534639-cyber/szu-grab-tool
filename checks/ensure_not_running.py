# -*- coding: utf-8 -*-
"""打包前检查：桌面上的 exe 是不是还在运行（在运行就覆盖不了）。

跑法： python checks/ensure_not_running.py
退出码：0 ＝ 可以覆盖；1 ＝ 有进程在跑（并打印是哪一份）。

为什么不用批处理里的 tasklist + find：那个 find 在不同 PATH 下会解析成
MSYS 的 GNU find，参数写法完全不同，报一堆 "No such file or directory"。
用 Python 判断既准确又不用跟引号搏斗。
"""

import os
import subprocess
import sys

NAMES = ("深大抢课助手.exe", "深大抢课助手_自己用.exe")


def running_names():
    try:
        raw = subprocess.run(["tasklist", "/FO", "CSV"],
                             capture_output=True).stdout
    except Exception:
        return []
    text = raw.decode("gb18030", "replace")
    return [name for name in NAMES if name in text]


def main():
    running = running_names()
    if running:
        print("  ★ 这些程序还在运行，先关掉再打包：%s" % "、".join(running))
        return 1
    print("  桌面两份都没在运行，可以覆盖。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

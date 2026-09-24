# -*- coding: utf-8 -*-
"""算出口令（发给同学的那个）。双击「看今天的口令.bat」就是跑这个。

口令 = 由「密钥 + 段号 + 版本号」算出来的一串字符，和 exe 里用的是同一个算法。
**不是存了一张表，而是现算**——所以任何时间段都算得出来，同一天算多少次都一样。

几天换一次由 activation.json 里的 period_days 决定（现在是 3 = 三天一换）。

★ 密钥从本机的 activation.json 里读（那个文件不进 git、也不发给任何人）。
  这个脚本本身**不含密钥**，可以安全地放进仓库或分享。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import activation  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, "activation.json")
AHEAD_DAYS = 14         # 往后列多少天（按段归并显示）


def wait_enter():
    try:
        input("  按回车关闭…")
    except EOFError:
        pass


def load_local_config():
    if not os.path.exists(CONFIG_PATH):
        print()
        print("  找不到 activation.json（密钥在里面）。")
        print("  它应该在： %s" % CONFIG_PATH)
        print("  如果丢了，就重新生成一个密钥，并把「给大家用」那份重新打包。")
        wait_enter()
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main():
    cfg = load_local_config()
    secret = str(cfg.get("secret") or "")
    version = str(cfg.get("version") or "2.0.0")
    if not secret:
        print("  activation.json 里没填 secret，先填一个。")
        wait_enter()
        return 1

    activation.CONFIG = cfg
    period = activation.period_days()

    def code(offset):
        return activation.password_for(secret, activation.period_index(offset),
                                       version)

    print()
    print("  深大抢课助手 · 口令")
    print("  （这一份 exe 的版本 %s，%d 天换一次）" % (version, period))
    print("  ------------------------------------------")
    print("    今天  %s   %s   <- 现在发这个"
          % (activation.day_string(0), code(0)))
    if period > 1:
        print("    这段还剩 %d 天（含今天）" % activation.period_last_day(0))
    print("    昨天  %s   %s   <- 也认（容忍电脑时间偏差）"
          % (activation.day_string(-1), code(-1)))
    print()

    # 按段归并：同一个口令的几天合成一行，一眼能看出哪天换
    print("  接下来 %d 天（想一次发完，就照这个发）：" % AHEAD_DAYS)
    seen = {}
    order = []
    for offset in range(1, AHEAD_DAYS + 1):
        value = code(offset)
        day = activation.day_string(offset)
        if value not in seen:
            seen[value] = []
            order.append(value)
        seen[value].append(day)
    for value in order:
        days = seen[value]
        if len(days) == 1:
            span = days[0]
        else:
            span = "%s ~ %s" % (days[0], days[-1])
        print("    %-24s   %s" % (span, value))
    print()
    print("  同学那边：双击 exe -> 输入当天的口令 -> 进。")
    print("  exe 认「今天前后各一天」所在的那段，所以换口令那天前后两个码都能用，")
    print("  免得有人电脑时间偏一点就卡住。")
    print()
    print("  想立刻作废旧版：把 activation.json 里的 version 改成新版本号、")
    print("  重新打包「给大家用」那份，整套口令会换掉。")
    print()
    wait_enter()
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""算出今天的口令（发给同学的那个）。双击「看今天的口令.bat」就是跑这个。

口令 = 由「密钥 + 日期 + 版本号」算出来的一串字符，和 exe 里用的是同一个算法。
不是存了一张表，而是**每天现算**——所以任何一天都算得出来，同一天算多少次都一样。

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
AHEAD_DAYS = 7          # 往后列几天（方便一次发完）


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

    activation.CONFIG = {"secret": secret, "version": version}

    def code(offset):
        return activation.password_for(secret, activation.day_string(offset),
                                       version)

    def day(offset):
        return activation.day_string(offset)

    print()
    print("  深大抢课助手 · 口令（这一份 exe 的版本：%s）" % version)
    print("  ------------------------------------------")
    print("    今天  %s   %s   <- 现在发这个" % (day(0), code(0)))
    print("    昨天  %s   %s   <- 也认（容忍电脑时间偏差）"
          % (day(-1), code(-1)))
    print()
    print("  接下来 %d 天（想一次发完，就照这个发）：" % AHEAD_DAYS)
    for offset in range(1, AHEAD_DAYS + 1):
        print("    %s   %s" % (day(offset), code(offset)))
    print()
    print("  同学那边：双击 exe -> 输入当天那个口令 -> 进。")
    print("  注意：exe 只认「今天」和「昨天」两天的口令，"
          "提前发出去的那些要到那天才生效。")
    print()
    print("  想立刻作废旧版：把 activation.json 里的 version 改成新版本号、")
    print("  重新打包「给大家用」那份，整套口令会换掉。")
    print()
    wait_enter()
    return 0


if __name__ == "__main__":
    sys.exit(main())

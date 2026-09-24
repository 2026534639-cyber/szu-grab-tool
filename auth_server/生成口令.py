# -*- coding: utf-8 -*-
"""算出今天的口令（发给同学的那个）。双击「生成口令.bat」就是跑这个。

口令 = 由「密钥 + 日期 + 版本号」算出来的一串字符，和 exe 里用的是同一个算法。
所以：换一天就换一个口令；换了版本号，旧 exe 的口令就自然失效了。

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


def wait_enter():
    try:
        input("  按回车关闭…")
    except EOFError:
        pass


def main():
    if not os.path.exists(CONFIG_PATH):
        print()
        print("  找不到 activation.json（密钥在里面）。")
        print("  它应该在： %s" % CONFIG_PATH)
        print("  如果丢了，就重新生成一个密钥，并把「给大家用」那份重新打包。")
        wait_enter()
        return 1
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    secret = str(cfg.get("secret") or "")
    version = str(cfg.get("version") or "2.0.0")
    if not secret:
        print("  activation.json 里没填 secret，先填一个。")
        wait_enter()
        return 1

    activation.CONFIG = {"secret": secret, "version": version}
    print()
    print("  深大抢课助手 · 口令（版本 %s）" % version)
    print("  ----------------------------------")
    for offset, label in ((0, "今天"), (-1, "昨天"), (1, "明天")):
        code = activation.password_for(secret, activation.day_string(offset),
                                       version)
        print("     %s ：  %s" % (label, code))
    print()
    print("  把「今天」那个发到群里就行；「昨天」那个是为了容忍用户电脑")
    print("  时间偏差，两边都能用。")
    print()
    print("  想换口令：明天自然就换了（每天一个）。")
    print("  想立刻作废旧版：把 activation.json 里的 version 改成新版本号、")
    print("  重新打包「给大家用」那份，再发新口令。")
    print()
    wait_enter()
    return 0


if __name__ == "__main__":
    sys.exit(main())

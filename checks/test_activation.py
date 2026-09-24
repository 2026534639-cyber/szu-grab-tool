# -*- coding: utf-8 -*-
"""授权门（口令）的检查。

跑法： python checks/test_activation.py

重点盯三件事：
  1. 口令算得对、认得出今天和昨天的、认不出明天和错的；
  2. **版本绑定**：用别的版本算出来的口令，本版必须拒绝——这就是"旧版崩坏"的原理；
  3. **授权服务器连不上时一律放行**——绝不能因为网络问题把人锁在门外
     （抢课那天连不上授权服务器的话，那才是最糟的事）。
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import activation  # noqa: E402
import szu_grab_app as app  # noqa: E402

FAILURES = []
CHECKS = [0]


def check(label, got, want):
    CHECKS[0] += 1
    if got != want:
        FAILURES.append("%s：得到 %r，期望 %r" % (label, got, want))
        print("  FAIL %s：得到 %r，期望 %r" % (label, got, want))
    else:
        print("  ok   %s → %r" % (label, got))


def check_true(label, got, why=""):
    CHECKS[0] += 1
    if not got:
        FAILURES.append("%s%s" % (label, ("：" + why) if why else ""))
        print("  FAIL %s %s" % (label, why))
    else:
        print("  ok   %s" % label)


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


SECRET = activation.CONFIG.get("secret", "")
VERSION = activation.app_version()

# ==========================================================================
section("1 口令：算得对、认得对、认不出错的")
# ==========================================================================

check_true("打包进来的授权配置里有密钥（说明这一份是「给大家用」的）",
           bool(SECRET), "没有密钥 → 这一份不会要口令")

today = activation.password_for(SECRET, activation.day_string(0), VERSION)
yesterday = activation.password_for(SECRET, activation.day_string(-1), VERSION)
tomorrow = activation.password_for(SECRET, activation.day_string(1), VERSION)

check("口令长度 6", len(today), 6)
check_true("口令只用大写字母和数字", today.isupper() or today.isalnum(), today)
check_true("去掉了容易看错的 0/O/1/I",
           not (set(today) & set("0O1I")), today)
check("同样的输入算两次结果一样",
      activation.password_for(SECRET, activation.day_string(0), VERSION), today)
check_true("换一天就换一个口令", today != yesterday and today != tomorrow,
           "%s / %s / %s" % (today, yesterday, tomorrow))

check("今天的口令：认", activation.check_password(today), True)
check("昨天的口令：也认（容忍电脑时间偏一点）",
      activation.check_password(yesterday), True)
check("明天的口令：不认（还没到那天）",
      activation.check_password(tomorrow), False)
check("随便一个错口令：不认", activation.check_password("AAAAAA"), False)
check("空口令：不认", activation.check_password(""), False)
check("None 不炸", activation.check_password(None), False)
check("小写也认（用户懒得切大写）",
      activation.check_password(today.lower()), True)
check("前后带空格也认", activation.check_password("  " + today + " "), True)

# ==========================================================================
section("2 版本绑定：旧 exe 拿着新口令也不好使（这就是「旧版崩坏」）")
# ==========================================================================

newer = activation.password_for(SECRET, activation.day_string(0), "9.9.9")
check_true("用 9.9.9 版算出的口令和本版不一样", newer != today, newer)
check("本版拒绝 9.9.9 版的口令", activation.check_password(newer), False)
check_true("也就是说：作者一发新版口令，旧版自然失效（不需要服务器）",
           activation.check_password(newer) is False)

# ==========================================================================
section("3 服务器：能连上才听它的，连不上绝不影响使用")
# ==========================================================================

real_endpoint = activation.CONFIG.get("endpoint")


def with_endpoint(value):
    activation.CONFIG["endpoint"] = value


# ① 连不上（用一个必然被拒的本地端口，秒失败）
with_endpoint("http://127.0.0.1:9/check")
check("连不上服务器时，server_verdict 返回空（＝当没这回事）",
      activation.server_verdict(today), "")
ok, why = activation.verify(today)
check_true("连不上服务器时，正确口令照样放行（这条最关键：不能把人锁在门外）",
           ok, why)

# ② 没配 endpoint：完全不联网
with_endpoint("")
check("没配服务器时不请求（返回空）", activation.server_verdict(today), "")
ok, _ = activation.verify(today)
check_true("没配服务器时正确口令放行", ok)

# ③ 服务器说不行时，才真的拒绝（这里用假返回值模拟）
original_check = activation.check_password
try:
    activation.check_password = lambda typed: True
    activation.server_verdict = lambda typed: "deny:这一版已停用，找作者要新版"
    ok, why = activation.verify("WHATEVER")
    check("服务器说停用时：拒绝", ok, False)
    check_true("并且把服务器的原话告诉用户", "停用" in why, why)
finally:
    activation.check_password = original_check
    if real_endpoint is not None:
        with_endpoint(real_endpoint)

# ==========================================================================
section("4 本机记录：安装号稳定、缓存文件写得出")
# ==========================================================================

first = activation.install_id()
check("安装号长度 12", len(first), 12)
check("再问一次还是同一个号", activation.install_id(), first)
cache_path = os.path.join(activation._app_dir(), activation.CACHE_NAME)
activation.mark_ok()
check_true("写了本机记录文件", os.path.exists(cache_path), cache_path)
if os.path.exists(cache_path):
    import json
    with open(cache_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    check_true("记录里有上次成功时间", int(data.get("last_ok", 0)) > 0)
    check_true("记录里没有明文口令",
               today not in json.dumps(data, ensure_ascii=False),
               "缓存里出现了口令明文，应该只存时间和安装号")

# ==========================================================================
section("5 「自己用」的那一份：不该问口令")
# ==========================================================================

saved = activation.ENABLED
try:
    activation.ENABLED = False       # 模拟没打包 activation.json 的那一份
    check("没启用授权时，口令门直接放行", app.activation_gate(), True)
finally:
    activation.ENABLED = saved

if os.path.exists(cache_path):
    os.remove(cache_path)

print("\n" + "=" * 72)
print("跑了 %d 项检查，失败 %d 项" % (CHECKS[0], len(FAILURES)))
for item in FAILURES:
    print("  · " + item)
print("=" * 72)
sys.exit(1 if FAILURES else 0)

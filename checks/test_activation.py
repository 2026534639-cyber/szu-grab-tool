# -*- coding: utf-8 -*-
"""授权门（口令）的检查。

跑法： python checks/test_activation.py

重点盯四件事：
  1. 口令算得对：同一段算多少次都一样、不同段算出来不一样；
  2. **三天一换**：一个口令能撑 1~3 天，更早的段一律不认；
  3. **版本绑定**：用别的版本算出来的口令，本版必须拒绝（「旧版崩坏」的原理）；
  4. **授权服务器连不上时一律放行**——绝不能因为网络问题把人锁在门外
     （抢课那天连不上授权服务器的话，那才是最糟的事）。
"""

import os
import sys

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
PERIOD = activation.period_days()


def code_for_period(period, version=None):
    return activation.password_for(SECRET, period, version or VERSION)


def code_for_offset(days, version=None):
    return code_for_period(activation.period_index(days), version)


# ==========================================================================
section("1 口令怎么算：同一段一样、不同段不一样")
# ==========================================================================

check_true("这一份带了密钥（说明是「给大家用」的那份）", bool(SECRET))
check("几天换一次", PERIOD, 3)

today = code_for_offset(0)
check("口令长度 6", len(today), 6)
check_true("口令只用大写字母和数字", today.isalnum() and today.upper() == today,
           today)
check_true("去掉了容易看错的 0/O/1/I", not (set(today) & set("0O1I")), today)
check("同一个段算两次结果一样", code_for_offset(0), today)
check_true("换一段就换一个口令",
           code_for_period(activation.period_index(0) + 1) != today,
           code_for_period(activation.period_index(0) + 1))

# 这一段里的每一天都该算出同一个口令（这就是"三天一换"）
same_period_offsets = [offset for offset in range(-5, 6)
                       if activation.period_index(offset) ==
                       activation.period_index(0)]
same_period = [code_for_offset(offset) for offset in same_period_offsets]
check_true("同一段里的每一天都算同一个口令", len(set(same_period)) == 1,
           same_period)
# 注意不能断言"今天往后还有 3 天"——今天是这一段中间那天的话，往后只剩 2 天。
# 真正的性质是：前后各 ±5 天这个范围里，属于本段的日期正好 3 个。
check_true("一段正好是 3 天（前后各 ±5 天里落进本段的有 %d 天）"
           % len(same_period_offsets), len(same_period_offsets) == PERIOD,
           same_period_offsets)
check_true("「这段还剩几天」落在 1~3",
           1 <= activation.period_last_day(0) <= PERIOD,
           activation.period_last_day(0))

# ==========================================================================
section("2 校验：认本段、认相邻段（容忍时间偏差）、更早的一律不认")
# ==========================================================================

usable = activation.accepted_passwords()
p_now = activation.period_index(0)
expected_codes = {code_for_period(activation.period_index(-1)),
                  code_for_period(p_now),
                  code_for_period(activation.period_index(1))}
check_true("本段的口令：认", activation.check_password(today), today)
check_true("可用口令正好是「今天前后各一天所在的那段」那 1~3 个码",
           set(usable) == expected_codes, "、".join(usable))
mid_period = activation.period_index(-1) == activation.period_index(1)
check_true(
    "段中间时只有 1 个码能用（今天就是这种情形）" if mid_period
    else "靠近换段时会同时认 2 个码（免得有人电脑时间偏一点就卡住）",
    len(usable) == (1 if mid_period else 2),
    "今天可用 %d 个：%s" % (len(usable), "、".join(usable)))

check("两段以前的口令：不认（这就是「过期」）",
      activation.check_password(code_for_period(activation.period_index(0) - 2)),
      False)
check("三段以前的口令：不认",
      activation.check_password(code_for_period(activation.period_index(0) - 3)),
      False)
check("随便一个错口令：不认", activation.check_password("AAAAAA"), False)
check("空口令：不认", activation.check_password(""), False)
check("None 不炸", activation.check_password(None), False)
check("小写也认（用户懒得切大写）", activation.check_password(today.lower()), True)
check("前后带空格也认", activation.check_password("  " + today + " "), True)
check("中间空格不认", activation.check_password(today[:3] + " " + today[3:]),
      False)

# ==========================================================================
section("3 版本绑定：旧 exe 拿着新口令也不好使（「旧版崩坏」的原理）")
# ==========================================================================

newer = code_for_offset(0, "9.9.9")
check_true("用 9.9.9 版算出的口令和本版不一样", newer != today, newer)
check("本版拒绝 9.9.9 版的口令", activation.check_password(newer), False)
check_true("也就是说：作者换版本号发新口令，旧版自然失效（不需要服务器）",
           activation.check_password(newer) is False)

# ==========================================================================
section("4 服务器：能连上才听它的，连不上绝不影响使用")
# ==========================================================================

real_endpoint = activation.CONFIG.get("endpoint")


def with_endpoint(value):
    activation.CONFIG["endpoint"] = value


with_endpoint("http://127.0.0.1:9/check")     # 必然被拒，秒失败
check("连不上服务器时，server_verdict 返回空（＝当没这回事）",
      activation.server_verdict(today), "")
ok, why = activation.verify(today)
check_true("连不上服务器时，正确口令照样放行（这条最关键）", ok, why)

with_endpoint("")
check("没配服务器时不请求（返回空）", activation.server_verdict(today), "")
ok, _ = activation.verify(today)
check_true("没配服务器时正确口令放行", ok)

original_check = activation.check_password
original_verdict = activation.server_verdict
try:
    activation.check_password = lambda typed: True
    activation.server_verdict = lambda typed: "deny:这一版已停用，找作者要新版"
    ok, why = activation.verify("WHATEVER")
    check("服务器说停用时：拒绝", ok, False)
    check_true("并且把服务器的原话告诉用户", "停用" in why, why)
finally:
    activation.check_password = original_check
    activation.server_verdict = original_verdict
    if real_endpoint is not None:
        with_endpoint(real_endpoint)

# ==========================================================================
section("5 本机记录：安装号稳定、缓存文件写得出、不存明文口令")
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
section("6 「自己用」的那一份：不该问口令")
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

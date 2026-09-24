# -*- coding: utf-8 -*-
"""自检一：凭证识别 + 结果翻译 + 限速退避。

跑法：python selftest_protocol.py

这组测试盯的是「新手最容易栽的地方」——从浏览器复制出来的一大段文字，
到底能不能被正确认成学号 / Cookie / token / 批次码。共覆盖 7 种真实复制格式、
中文标签写法、只复制载荷、以及无关文字干扰。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from szu_grabber import (classify, missing_fields, next_delay, parse_credentials,
                         plain_result, status_of)

SID = "2023150047"
BATCH = "04a79c9569de4ac09f6826f6324a644a"
TOKEN = "6e912f8e-a3b4-4ef5-8a0b-ca8358420b1c"
COOKIE = ("_WEU=rfhjF4PaYINuCCd_kqfaHvohaBAqdm4TgJ6RtIMKpLduDy1Ef2pMdvxDBRgFba2r; "
          "JSESSIONID=2CD85D58A90AA87245C9051B1E7976B5; "
          "b-user-id=c571adeb-8c51-f97f-3375-58c09fcab4df")

ENC = ("querySetting=%7B%22data%22%3A%7B%22studentCode%22%3A%22" + SID +
       "%22%2C%22campus%22%3A%2201%22%2C%22electiveBatchCode%22%3A%22" + BATCH +
       "%22%7D%7D")

CASES = {}

CASES["curl-bash"] = (
    "curl 'http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do' \\\n"
    "  -H 'accept: application/json, text/javascript, */*; q=0.01' \\\n"
    "  -H 'accept-language: zh-CN,zh;q=0.9' \\\n"
    "  -H 'content-type: application/x-www-form-urlencoded; charset=UTF-8' \\\n"
    "  -H 'cookie: " + COOKIE + "' \\\n"
    "  -H 'token: " + TOKEN + "' \\\n"
    "  -H 'user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' \\\n"
    "  --data-raw '" + ENC + "' \\\n"
    "  --compressed"
)

CASES["curl-cmd"] = (
    'curl "http://bkxk.szu.edu.cn/x/xsxkapp/elective/recommendedCourse.do" ^\n'
    '  -H "accept: application/json, text/javascript, */*; q=0.01" ^\n'
    '  -H "cookie: ' + COOKIE + '" ^\n'
    '  -H "token: ' + TOKEN + '" ^\n'
    '  --data-raw "' + ENC + '" ^\n'
    '  --compressed'
)

CASES["curl-powershell"] = (
    'curl.exe "http://bkxk.szu.edu.cn/x/xsxkapp/elective/recommendedCourse.do" `\n'
    '  -H "cookie: ' + COOKIE + '" `\n'
    '  -H "token: ' + TOKEN + '" `\n'
    '  --data-raw "' + ENC + '"'
)

CASES["copy-as-fetch"] = (
    'fetch("http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do", {\n'
    '  "headers": {\n'
    '    "accept": "application/json, text/javascript, */*; q=0.01",\n'
    '    "cookie": "' + COOKIE + '",\n'
    '    "token": "' + TOKEN + '"\n'
    '  },\n'
    '  "body": "querySetting={\\"data\\":{\\"studentCode\\":\\"' + SID +
    '\\",\\"campus\\":\\"01\\",\\"electiveBatchCode\\":\\"' + BATCH + '\\"}}",\n'
    '  "method": "POST"\n'
    '});'
)

CASES["raw-headers"] = (
    "Cookie: " + COOKIE + "\n"
    "token: " + TOKEN + "\n"
    "studentCode: " + SID + "\n"
    "electiveBatchCode: " + BATCH
)

CASES["chinese-labels"] = (
    "学号：" + SID + "\n"
    "Cookie：" + COOKIE + "\n"
    "token：" + TOKEN + "\n"
    "批次码：" + BATCH
)

CASES["payload-only"] = (
    '{"data":{"studentCode":"' + SID + '","campus":"01",'
    '"electiveBatchCode":"' + BATCH + '"}}'
)

CASES["devtools-headers-panel"] = (
    "accept: application/json, text/javascript, */*; q=0.01\n"
    "accept-language: zh-CN,zh;q=0.9\n"
    "content-type: application/x-www-form-urlencoded; charset=UTF-8\n"
    "cookie: " + COOKIE + "\n"
    "token: " + TOKEN + "\n"
    "user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\n"
    + ENC
)

EXPECT_PARTIAL = {
    "payload-only": ["Cookie", "token"],
}

failures = []

for name, blob in CASES.items():
    creds = parse_credentials(blob)
    missing = missing_fields(creds)
    expect_missing = EXPECT_PARTIAL.get(name, [])
    got = {"student_code": creds["student_code"], "token": creds["token"],
           "batch": creds["batch"], "cookie_ok": creds["cookie"] == COOKIE}
    # 只检查「本来就应该认出来」的字段
    checks = [("学号", "student_code", SID), ("token", "token", TOKEN),
              ("批次码", "batch", BATCH), ("Cookie", "cookie", COOKIE)]
    problems = []
    if expect_missing:
        if sorted(missing) != sorted(expect_missing):
            problems.append("缺项应为 %s，实际 %s" % (expect_missing, missing))
    else:
        if missing:
            problems.append("还缺 %s" % missing)
    for label, key, want in checks:
        if label in expect_missing:
            continue
        if creds[key] != want:
            problems.append("%s = %r" % (label, creds[key][:70]))
    print(("PASS " if not problems else "FAIL ") + name +
          ("" if not problems else "  → " + " | ".join(problems)))
    if problems:
        failures.append(name)

# 干扰项：毫不相干的内容不能硬凑出凭证
noise = parse_credentials("今天天气不错，去食堂吃了个饭。")
if missing_fields(noise) != ["学号", "Cookie", "token", "批次码"]:
    failures.append("noise")
    print("FAIL noise → 不该认出任何东西：", noise)
else:
    print("PASS noise（空内容不误判）")

print("\n--- 结果翻译 ---")
RESULTS = [
    ('{"code":"1","msg":"添加选课志愿成功"}', "success", "抢到了！"),
    ('{"msg":"该课程超过课容量"}', "full", None),
    ('操作过于频繁，请稍后再试', "throttle", None),
    ('{"msg":"不在选课时间内"}', "closed", None),
    ('{"msg":"该课程与已选课程时间冲突"}', "conflict", None),
    ('{"msg":"你已选该课程，不可重复选课"}', "dup", None),
    ('', "server_error", None),
    ('{"msg":"选课批次不正确"}', "batch", None),
    # 真实服务器在会话失效时用 HTTP 200 回登录页，页面里还带着「选课时间」
    # 字样。这条必须判成 auth，否则会退化成「傻等」。
    ('<!DOCTYPE html><html lang="zh-CN"><head><title>统一身份认证</title>'
     '</head><body><p>请登录后查看选课时间安排</p></body></html>', "auth", None),
    ('<html><body>系统维护中</body></html>', "auth", None),
]
for text, want, want_plain in RESULTS:
    kind = classify(text)
    ok = kind == want
    if not ok:
        failures.append("classify:%s" % text[:20])
    line = "PASS " if ok else "FAIL "
    print("%s%-14s → %-13s %s" % (line, (text[:14] or "<空>"), kind,
                                  plain_result(kind, text)))
    if want_plain and plain_result(kind, text) != want_plain:
        failures.append("plain:" + text[:20])

# 关键判断：哪些结果要继续抢，哪些要放弃
from szu_grabber import FATAL_RESULTS, STOPALL_RESULTS
assert "full" not in FATAL_RESULTS and "full" not in STOPALL_RESULTS, "名额满必须继续蹲"
assert "closed" not in FATAL_RESULTS and "closed" not in STOPALL_RESULTS, "没到时间必须继续等"
assert "throttle" not in FATAL_RESULTS, "太频繁必须继续"
assert "auth" in STOPALL_RESULTS and "batch" in STOPALL_RESULTS
print("PASS 继续蹲/放弃的判断（名额满、没到时间、太频繁 都继续）")

print("\n--- 限速退避 ---")
base = (500, 900)
slow = next_delay(base, "throttle")
normal = next_delay(base, "full")
wait = next_delay(base, "closed")
print("throttle=%.2fs  normal=%.2fs  closed=%.2fs" % (slow, normal, wait))
if not (slow >= 0.9 and normal <= 0.9 and wait >= 2.4):
    failures.append("next_delay")
    print("FAIL 退避时间不对")
else:
    print("PASS 被限速会放慢、没到时间会等更久")

print("\n--- 状态标签 ---")
sample = {"chosen": False, "conflict": "", "full": False}
assert status_of(sample) == "有名额"
assert status_of({"chosen": True, "conflict": "", "full": False}) == "已选"
assert status_of({"chosen": False, "conflict": "时间冲突", "full": False}) == "时间冲突"
assert status_of({"chosen": False, "conflict": "", "full": True}) == "名额已满"
print("PASS 状态标签")

print("\n" + ("全部通过 ✅" if not failures else "有失败 ❌ %s" % failures))
sys.exit(1 if failures else 0)

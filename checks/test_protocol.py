# -*- coding: utf-8 -*-
"""第二、三层（协议半）：分支穷举 + 故障注入。

跑法： python checks/test_protocol.py
不联网——所有请求都打到本机的假服务器（checks/fake_server.py）。

覆盖：
  A 凭证识别：各种粘贴形态
  B 结果归类：每条规则的代表句，以及容易互相抢的句子
  C 时间解析与倒计时：边界、跨零点
  D 间隔退避
  E 真实请求路径：分页、页大小回退、编码、格式切换
  F 故障注入：500 / 超时 / 连接被掐 / 空回复 / 非 JSON 非 HTML / 缺 Date 头
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

# 本机回环别让代理拦截
os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

import requests  # noqa: E402
from urllib.parse import parse_qs  # noqa: E402

import szu_grabber as g  # noqa: E402
from fake_server import FakeServer  # noqa: E402


def form_of(request):
    """把一次请求的表单体解成字典（requests 会做百分号编码）。"""
    return {k: v[0] for k, v in parse_qs(request["body"]).items()}


def header_of(grabber, name):
    """按名字取请求头，大小写不敏感。

    程序内部把头的名字统一成小写了（避免 User-Agent 和 user-agent
    两条同时发出去），所以测试不能再假定大小写。
    """
    for key, value in grabber.headers.items():
        if key.lower() == name.lower():
            return value
    return None


def page_number_of(request):
    import json as _json
    return _json.loads(form_of(request)["querySetting"])["pageNumber"]


def page_size_of(request):
    import json as _json
    return _json.loads(form_of(request)["querySetting"])["pageSize"]

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


CREDS = {"student_code": "2023123456", "cookie": "_WEU=abc; JSESSIONID=xyz",
         "token": "6e912f8e-1234-5678-9abc-def012345678", "batch": "2026A1B2C3D4"}


# ==========================================================================
section("A 凭证识别：用户会怎么粘，就得怎么认")
# ==========================================================================

CASES = [
    ("bash 单引号 + 反斜杠续行",
     "curl 'http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do' \\\n"
     "  -H 'cookie: _WEU=abc; JSESSIONID=xyz' \\\n"
     "  -H 'token: 6e912f8e-1234-5678-9abc-def012345678' \\\n"
     "  --data-raw 'querySetting=%7B%22studentCode%22%3A%222023123456%22%7D'"),
    ("cmd 双引号 + 尖号续行",
     'curl "http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do" ^\n'
     '  -H "cookie: _WEU=abc; JSESSIONID=xyz" ^\n'
     '  -H "token: 6e912f8e-1234-5678-9abc-def012345678" ^\n'
     '  --data-raw "querySetting={\\"studentCode\\":\\"2023123456\\"}"'),
    ("powershell 反引号续行",
     "curl.exe 'http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do' `\n"
     "  -H 'cookie: _WEU=abc; JSESSIONID=xyz' `\n"
     "  -H 'token: 6e912f8e-1234-5678-9abc-def012345678' `\n"
     "  --data-raw 'querySetting={\"studentCode\":\"2023123456\"}'"),
    ("Copy as fetch（带 \\\" 转义）",
     'fetch("http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do", {\n'
     '  "headers": {"cookie": "_WEU=abc; JSESSIONID=xyz",\n'
     '    "token": "6e912f8e-1234-5678-9abc-def012345678"},\n'
     '  "body": "querySetting={\\"studentCode\\":\\"2023123456\\"}",\n'
     '  "method": "POST"});'),
    ("--data-raw= 等号写法",
     "curl http://bkxk.szu.edu.cn/x --data-raw='querySetting=%7B%22studentCode%22%3A%222023123456%22%7D' "
     "-H 'cookie: _WEU=abc' -H 'token: 6e912f8e-1234-5678-9abc-def012345678'"),
    ("-b 短选项传 Cookie",
     "curl http://bkxk.szu.edu.cn/x -b '_WEU=abc; JSESSIONID=xyz' "
     "-H 'token: 6e912f8e-1234-5678-9abc-def012345678' "
     "--data 'querySetting=%7B%22studentCode%22%3A%222023123456%22%7D'"),
    ("整段 URL 编码过",
     "curl%20http%3A%2F%2Fbkxk.szu.edu.cn%2Fx%20"
     "-H%20%27cookie%3A%20_WEU%3Dabc%27%20"
     "-H%20%27token%3A%206e912f8e-1234-5678-9abc-def012345678%27%20"
     "--data%20%27querySetting%3D%7B%22studentCode%22%3A%222023123456%22%7D%27"),
]

for label, text in CASES:
    parsed = g.parse_credentials(text)
    check("%s → 学号" % label, parsed["student_code"], "2023123456")
    check("%s → token" % label, parsed["token"], "6e912f8e-1234-5678-9abc-def012345678")
    check("%s → cookie 非空" % label, bool(parsed["cookie"]), True)

print()
check("空文本不炸（四个凭证字段都为空）",
      {k: g.parse_credentials("")[k]
       for k in ("student_code", "cookie", "token", "batch")},
      {"student_code": "", "cookie": "", "token": "", "batch": ""})
check("垃圾文本不炸", g.missing_fields(g.parse_credentials("你好世界")),
      ["学号", "Cookie", "token", "批次码"])
check("中文标签也认",
      g.parse_credentials("学号：2023123456\n批次码：2026A1B2C3D4")["student_code"],
      "2023123456")
_check_batch = g.parse_credentials("curl http://x --data 'querySetting=%7B%22electiveBatchCode%22%3A%222026A1B2C3D4%22%7D'")
check("批次码从百分号编码里捞出来", _check_batch["batch"], "2026A1B2C3D4")


# ==========================================================================
section("B 结果归类：容易互相抢的句子")
# ==========================================================================

EXPECT = [
    ('{"code":"1","msg":"添加选课志愿成功"}', "success"),
    ('{"code":"0","msg":"该课程超过课容量"}', "full"),
    ('{"code":"0","msg":"余量不足"}', "full"),
    ('{"code":"0","msg":"操作过于频繁，请稍后重试"}', "throttle"),
    ('{"code":"0","msg":"当前不在选课时间内"}', "closed"),
    ('{"code":"0","msg":"该课程与已选课程时间冲突"}', "conflict"),
    ('{"code":"0","msg":"该课程与你已选课程冲突"}', "conflict"),
    ('<!DOCTYPE html><html><body>请登录</body></html>', "auth"),
    ('<!DOCTYPE html><html><body>选课时间安排</body></html>', "auth"),
    ("", "server_error"),
]
for text, want in EXPECT:
    check("归类 %s" % (text[:26] or "(空)"), g.classify(text), want)

print("\n-- 这两条以前会归错，单独盯住 --")
# 登录页 HTML 里也写着「选课时间」，不能被当成「还没到时间」而一直傻等
check("登录页优先认成凭证失效，而不是没到时间",
      g.classify('<!DOCTYPE html><html><head><title>选课时间</title></head>'
                 '<body>请登录</body></html>'), "auth")

# ==========================================================================
section("C 开抢时刻：怎么填都得读对，填错就明确报错")
# ==========================================================================

TIME_CASES = [
    ("12:30", 12 * 3600 + 30 * 60),
    ("12:30:00", 12 * 3600 + 30 * 60),
    ("12:30:45", 12 * 3600 + 30 * 60 + 45),
    ("0:00", 0),
    ("00:00:00", 0),
    ("23:59:59", 23 * 3600 + 59 * 60 + 59),
    ("12：30", 12 * 3600 + 30 * 60),          # 全角冒号
    ("12点30分", 12 * 3600 + 30 * 60),
    ("12时30分", 12 * 3600 + 30 * 60),
    ("930", 9 * 3600 + 30 * 60),              # 紧凑写法
    ("1230", 12 * 3600 + 30 * 60),
    ("  15 : 00  ", 15 * 3600),
]
for text, want in TIME_CASES:
    check("解析 %r" % text, g.parse_start_time(text), want)

BAD_TIMES = ["", "12", "abc", "25:00", "12:65", "12:30:99", "-1:00", "12345",
             "12:30:45:00", "::"]
for text in BAD_TIMES:
    check("拒绝 %r" % text, g.parse_start_time(text), None)

print("\n-- 倒计时：跨零点不能算反 --")
# 服务器 23:55，用户填 00:00 → 应该还有 5 分钟，而不是「已经过去 23 小时 55 分」
_now_2355 = time.mktime(time.struct_time((2026, 9, 21, 23, 55, 0, 0, 0, -1)))
_left = g.seconds_until_start(0, 0.0, now=_now_2355)
check_true("23:55 时填 00:00 → 还有约 300 秒（不是 -86100）", 290 < _left < 310,
           "实际 %.1f" % _left)

# 服务器 00:05，用户填 23:59 → 应该还有约 23 小时 54 分
_now_0005 = time.mktime(time.struct_time((2026, 9, 21, 0, 5, 0, 0, 0, -1)))
_left2 = g.seconds_until_start(23 * 3600 + 59 * 60, 0.0, now=_now_0005)
check_true("00:05 时填 23:59 → 还有约 23.9 小时", _left2 > 85000, "实际 %.0f" % _left2)

# 已经过去 5 分钟 → 负数，表示错过
_now_2030 = time.mktime(time.struct_time((2026, 9, 21, 20, 30, 0, 0, 0, -1)))
_left3 = g.seconds_until_start(20 * 3600 + 25 * 60, 0.0, now=_now_2030)
check_true("20:30 时填 20:25 → 负数（已经过了）", _left3 < 0, "实际 %.0f" % _left3)

print("\n-- 高频窗口的截止时刻：跨零点不能永远退不出高频 --")
# 这是本轮修的 bug：截止时刻按「当天第几秒」算，23:59:50 开始 +15 秒
# 会得到 86405 > 86400，而服务器秒数永远在 0~86399，条件永远不成立。
_start = 23 * 3600 + 59 * 60 + 50
_bad = _start + 15
check_true("旧算法确实会溢出一天（%d > 86400）" % _bad, _bad > 86400,
           "这是 bug 的成因，用于固定证据")


# ==========================================================================
section("D 间隔退避：不能越撞越猛，也不能一次被限速就再也快不起来")
# ==========================================================================

for kind in ("full", "throttle", "network", "closed"):
    delays = [g.next_delay((200, 400), kind) for _ in range(50)]
    check_true("间隔 %s 恒在下限之上" % kind, min(delays) >= 0.2,
               "最小 %.3f" % min(delays))
    check_true("间隔 %s 恒在上限之下" % kind, max(delays) <= 5.0,
               "最大 %.3f" % max(delays))

_th = [g.next_delay((500, 900), "throttle") for _ in range(200)]
_no = [g.next_delay((500, 900), "full") for _ in range(200)]
check_true("被限速后确实变慢（%.2f > %.2f）" % (min(_th), max(_no)),
           min(_th) > max(_no))
_notes = []
g.next_delay((500, 900), "throttle", on_note=_notes.append)
check_true("被限速时会告诉用户", len(_notes) == 1, "notes=%r" % _notes)


# ==========================================================================
section("E/F 真实请求路径与故障注入（打到本机假服务器）")
# ==========================================================================

server = FakeServer().start()
g.BASE_URL = server.url
print("假服务器:", server.url)

try:
    grabber = g.CourseGrabber(CREDS, timeout=2)

    # ---- E1 正常翻页：第一页有数据、第二页空 ----
    server.reset()
    server.push_json({"dataList": [
        {"courseName": "篮球", "tcList": [
            {"teachingClassID": "C1", "teacherName": "张老师",
             "teachingPlace": "南区球场", "classCapacity": "50",
             "numberOfSelected": "12"}]}]})
    server.push_json({"dataList": []})
    rows = grabber.search("篮球", ["TYKC"])
    check("搜到 1 条", len(rows), 1)
    check("状态是「有名额」", g.status_of(rows[0]), "有名额")
    check("提交的是 POST", server.requests[0]["method"], "POST")
    # 接口按类型分：TJKC（本班）走 recommendedCourse.do，其余类型走 programCourse.do
    check_true("体育课走 programCourse 接口",
               "programCourse.do" in server.requests[0]["path"],
               server.requests[0]["path"])

    # ---- E1b 本班课程走 recommendedCourse.do（说明书里让用户复制的那一行）----
    server.reset()
    server.push_json({"dataList": [{"courseName": "高等数学", "tcList": [
        {"teachingClassID": "C9", "classCapacity": "80", "numberOfSelected": "3"}]}]})
    server.push_json({"dataList": []})
    rows_tj = grabber.search("高等数学", ["TJKC"])
    check("本班课程搜到 1 条", len(rows_tj), 1)
    check_true("本班课程走 recommendedCourse 接口",
               "recommendedCourse.do" in server.requests[0]["path"],
               server.requests[0]["path"])

    # ---- E2 第一页是第 0 页（照浏览器抄的），以及两条回退 ----
    # 用户报「搜索好像不完整」就是这里：浏览器发的 pageNumber 是 "0"，
    # 我们原来发 1，等于每次从第二页开始，最前面那页的课全被跳过。
    server.reset()
    grabber2 = g.CourseGrabber(CREDS, timeout=2)
    server.push_json({"dataList": [
        {"courseName": "网球", "tcList": [
            {"teachingClassID": "C2", "classCapacity": "30",
             "numberOfSelected": "30"}]}]})
    server.push_json({"dataList": []})
    rows2 = grabber2.search("网球", ["TYKC"])
    check("第一页就拿到了课", len(rows2), 1)
    check("满员被识别出来", g.status_of(rows2[0]), "名额已满")
    check("第一个请求发的是第 0 页（和浏览器一致）",
          page_number_of(server.requests[0]), "0")
    check("之后翻第 1 页", page_number_of(server.requests[1]), "1")

    # 回退一：第 0 页空、第 1 页有数据 → 说明这个部署是按 1 起算的
    server.reset()
    grabber2b = g.CourseGrabber(CREDS, timeout=2)
    server.push_json({"dataList": []})
    server.push_json({"dataList": [
        {"courseName": "足球", "tcList": [
            {"teachingClassID": "C3", "classCapacity": "20",
             "numberOfSelected": "1"}]}]})
    server.push_json({"dataList": []})
    rows2b = grabber2b.search("足球", ["TYKC"])
    check("第 0 页空时自动改用 1 起算", grabber2b._page_base, 1)
    check("并且拿到了课", len(rows2b), 1)

    # 回退二：两种页码都空 → 再怀疑每页条数（系统不认 50 条一页）
    server.reset()
    grabber2c = g.CourseGrabber(CREDS, timeout=2)
    server.push_json({"dataList": []})
    server.push_json({"dataList": []})
    server.push_json({"dataList": [
        {"courseName": "排球", "tcList": [
            {"teachingClassID": "C4", "classCapacity": "20",
             "numberOfSelected": "2"}]}]})
    server.push_json({"dataList": []})
    rows2c = grabber2c.search("排球", ["TYKC"])
    check("两条回退都试过之后拿到了课", len(rows2c), 1)
    check("确实先试了 50 条一页", page_size_of(server.requests[0]), "50")
    check("最后退到 10 条一页", page_size_of(server.requests[2]), "10")

    # ---- E3 gb18030 编码的回复 ----
    server.reset()
    server.push(body='{"code":"0","msg":"该课程超过课容量"}', encoding="gb18030")
    grabber3 = g.CourseGrabber(CREDS, timeout=2)
    text = grabber3.choose("C1", "TYKC")
    check("gb18030 回复能解出来", g.classify(text), "full")

    # ---- E4 默认发的是哪一种格式（有实战记录的那种），以及格式切换的规矩 ----
    server.reset()
    grabber4 = g.CourseGrabber(CREDS, timeout=2)
    check("默认用 legacy（裸数字）写法——原稿/v1 都用它",
          grabber4.add_param_style, "legacy")
    server.push(body='{"code":"1","msg":"添加选课志愿成功"}')
    grabber4.choose("C1", "TYKC")
    sent = form_of(server.requests[0])["addParam"]
    check_true("实发出去的是裸数字（studentCode 后面不是引号）",
               '"studentCode":2023123456' in sent,
               sent[:100])
    check_true("字段齐全（和原稿一致）",
               all(k in sent for k in ("operationType", "studentCode",
                                       "electiveBatchCode", "teachingClassId",
                                       "isMajor", "campus", "teachingClassType",
                                       "chooseVolunteer")), sent[:160])

    # ---- E4b 第一种格式被退回时，自动换另一种，而且只探一次 ----
    server.reset()
    grabber4b = g.CourseGrabber(CREDS, timeout=2)
    server.push(body='{"code":"0","msg":"请求参数格式错误"}')      # legacy 被退回
    server.push(body='{"code":"1","msg":"添加选课志愿成功"}')      # json 成功
    server.push(body='{"code":"1","msg":"添加选课志愿成功"}')
    server.push(body='{"code":"1","msg":"添加选课志愿成功"}')
    grabber4b.choose("C1", "TYKC")
    before = len(server.requests)
    grabber4b.choose("C1", "TYKC")
    grabber4b.choose("C1", "TYKC")
    after = len(server.requests)
    check("切换格式那一次用了 2 个请求", before, 2)
    check("换用成功的那种之后，每次只发 1 个请求", after - before, 2)
    check("记住了换过来的格式", grabber4b.add_param_style, "json")
    check_true("第二次发的是带引号的那种",
               '"studentCode":"2023123456"' in form_of(server.requests[1])["addParam"],
               form_of(server.requests[1])["addParam"][:100])

    # ---- E4c 回了一句「读不懂」也要试另一种（代价不对称：宁可多试一次）----
    server.reset()
    grabber4c = g.CourseGrabber(CREDS, timeout=2)
    server.push(body='{"code":"999","msg":"系统繁忙"}')            # 读不懂，且没提参数
    server.push(body='{"code":"1","msg":"添加选课志愿成功"}')
    grabber4c.choose("C1", "TYKC")
    check("读不懂的回复会触发一次换格式试探（共 2 个请求）", len(server.requests), 2)
    check("试探成功后记住的是能用的那种", grabber4c.add_param_style, "json")

    # ---- E4d 服务器自己 5xx 时不要试格式（那种回复说明不了格式对不对）----
    server.reset()
    grabber4d = g.CourseGrabber(CREDS, timeout=2)
    server.push(status=500, body="500 Internal Server Error")
    grabber4d.choose("C1", "TYKC")
    check("5xx 不触发换格式（只发 1 个请求）", len(server.requests), 1)
    check_true("5xx 之后格式还没被确认，下次仍然可以探",
               not grabber4d.style_confirmed)

    # ---- E5 正常业务回复不能被当成「参数错误」而多发一遍 ----
    server.reset()
    grabber5 = g.CourseGrabber(CREDS, timeout=2)
    server.push_json({"code": "1", "msg": "选课失败，原因：课容量已满"})
    server.push_json({"code": "1", "msg": "选课失败，原因：课容量已满"})
    grabber5.choose("C1", "TYKC")
    grabber5.choose("C1", "TYKC")
    check("「选课失败，原因：课容量已满」只发 1 次请求", len(server.requests), 2)
    check("这回复被正确归成「名额满」",
          g.classify('{"code":"1","msg":"选课失败，原因：课容量已满"}'), "full")

    # ---- E6 连接地址跟着粘进来的 cURL 走（校内直连 / WebVPN 都能用）----
    # 为什么要有这一条：选课系统只在校内网里，校外要么用 SecureLink 客户端，
    # 要么用学校的 WebVPN（网页代理，域名和路径前缀都不一样）。写死 bkxk.szu.edu.cn
    # 就没法支持后一种，所以按用户粘的那条网址走。
    check("校内直连的网址 → 根地址就是 bkxk",
          g._derive_base("http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/"
                         "recommendedCourse.do"),
          "http://bkxk.szu.edu.cn/")
    check("WebVPN 的网址 → 连 webvpn，并且保住中间那段路径前缀",
          g._derive_base("https://webvpn.szu.edu.cn/http/77726476706e6974/"
                         "xsxkapp/sys/xsxkapp/elective/volunteer.do"),
          "https://webvpn.szu.edu.cn/http/77726476706e6974/")
    check("认不出网址时返回空（外层会退回默认地址）",
          g._derive_base("这不是网址"), "")
    check("真实 cURL 里能把网址捞出来",
          g.parse_credentials(
              "curl 'http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/"
              "recommendedCourse.do' -H 'cookie: _WEU=a' "
              "-H 'token: 6e912f8e-1234-5678-9abc-def012345678'")["base_url"],
          "http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do")

    # 用假服务器验证「creds 里带网址时真的打到那儿」
    server.reset()
    vpn_base = server.url + "http/77726476706e6974/"
    creds_vpn = dict(CREDS, base_url=vpn_base + "xsxkapp/sys/xsxkapp/"
                                            "elective/recommendedCourse.do")
    grabber_vpn = g.CourseGrabber(creds_vpn, timeout=2)
    check("连接地址来自粘进来的网址", grabber_vpn.base, vpn_base)
    check("Host 头跟着变（原来写死 bkxk 会连错）",
          header_of(grabber_vpn, "Host"), server.url.split("//")[1].rstrip("/"))
    server.push_json({"dataList": []})
    grabber_vpn.query_selected()
    check_true("请求真的打到了那个地址",
               server.requests[-1]["path"].startswith("/http/77726476706e6974/"),
               server.requests[-1]["path"][:80])

    # 连接失败自动重试的配置：只重试「连接」这一步（请求还没发出去，不会重复提交），
    # 读取超时（请求可能已经到了服务器）不自动重发。
    _retry = g.CourseGrabber(CREDS, timeout=2).session.get_adapter(
        "http://x").max_retries
    check("连接失败会重试（connect=2）", _retry.connect, 2)
    check("读取超时不自动重发（read=0）", _retry.read, 0)

    # ---- E8 网络抖一下就整轮失败太苛刻：只读请求要自动重试 ----
    # 这是用户报「很容易掉」之后加的：校园 VPN 抖一下，一次请求失败，
    # 原来整轮搜索就直接报错、让他重贴凭证。
    server.reset()
    grabber_ry = g.CourseGrabber(CREDS, timeout=2)
    server.push(mode="reset")                       # 第 1 次：连接被掐断
    server.push_json({"dataList": [                 # 第 2 次：正常
        {"courseName": "篮球", "tcList": [
            {"teachingClassID": "CR1", "classCapacity": "50",
             "numberOfSelected": "3"}]}]})
    server.push_json({"dataList": []})
    rows_ry = grabber_ry.search("篮球", ["TYKC"])
    check("抖一下（连接被掐断）之后自动重试拿到了结果", len(rows_ry), 1)
    check_true("确实重试过（请求数 > 1）", len(server.requests) >= 2,
               "%d 个请求" % len(server.requests))

    # 会话问题（服务器回登录页）不该重试——重试也没用，早报错早让用户处理
    server.reset()
    grabber_ry2 = g.CourseGrabber(CREDS, timeout=2)
    server.push(body="<!DOCTYPE html><html><body>请登录</body></html>")
    server.push(body="<!DOCTYPE html><html><body>请登录</body></html>")
    server.push(body="<!DOCTYPE html><html><body>请登录</body></html>")
    server.push_json({"dataList": []})
    try:
        grabber_ry2.query_selected()
        FAILURES.append("会话失效却当成成功返回了")
        print("  FAIL 会话失效没报错")
    except g.CredentialError:
        check("会话失效（登录页）只试 1 次就报错，不浪费时间重试",
              len(server.requests), 1)

    # ---- E10 冲刺的提前量按实测延迟算（写死 2 秒对慢链路不够）----
    # 实测：直连 0.16 秒、WebVPN 10 秒。10 秒的路提前 2 秒发出去，
    # 要等到开抢后 3 秒才到，前面一大截冲刺白冲。
    check("延迟很小（直连）时用下限 2 秒", g.burst_lead_for(0.16), 2.0)
    check("延迟 10 秒（WebVPN）时提前 5 秒", g.burst_lead_for(10.0), 5.0)
    check("量不出延迟时用下限", g.burst_lead_for(0), 2.0)
    check("延迟再大也不会超过上限（否则把冲刺窗口吃掉）",
          g.burst_lead_for(60.0), g.BURST_LEAD_MAX)
    check_true("上限比下限大", g.BURST_LEAD_MAX > g.BURST_LEAD)

    # ---- E9 浏览器实际会发的两个头，我们不能漏 ----
    # 用户报「马上搞了新的凭证，点搜索还是提示过期」之后加的：页面是 jQuery 写的，
    # jQuery 的 ajax 默认带 X-Requested-With；很多 Java 后端靠它区分
    # "接口请求" 和 "页面跳转"，当成页面跳转时未登录就回登录页 HTML。
    server.reset()
    grabber_hd = g.CourseGrabber(CREDS, timeout=2)
    check("带上了 X-Requested-With（浏览器就是这么发的）",
          header_of(grabber_hd, "X-Requested-With"), "XMLHttpRequest")
    # Referer 指向「用户实际所在的那个页面」：浏览器里抓到的真实值是
    # .../*default/grablessons.do?token=<token>，就照这个造。
    _ref = header_of(grabber_hd, "Referer")
    check_true("带上了 Referer，指向抢课页面并带上 token",
               _ref.endswith("/xsxkapp/sys/xsxkapp/*default/grablessons.do"
                             "?token=" + CREDS["token"]), _ref)
    server.push_json({"dataList": []})
    grabber_hd.query_selected()
    _sent = server.requests[-1]["headers"]
    check("这两个头真的发出去了（不只是存在字典里）",
          (_sent.get("x-requested-with"), bool(_sent.get("referer"))),
          ("XMLHttpRequest", True))

    # ---- E7 提交格式默认是有实战记录的那种（原稿/v1 都用裸数字）----
    check("默认用 legacy（裸数字）写法", g.CourseGrabber(CREDS, timeout=2).add_param_style,
          "legacy")

    # ---- F1 500 ----
    server.reset()
    server.push(status=500, body="<html>500 Internal Server Error</html>")
    grabber6 = g.CourseGrabber(CREDS, timeout=2)
    try:
        text = grabber6.choose("C1", "TYKC")
        print("  ok   500 没有抛异常，正文长度 %d" % len(text))
    except Exception as error:
        FAILURES.append("500 把客户端炸了：%r" % error)
        print("  FAIL 500 抛异常：%r" % error)

    # ---- F2 连接被掐断 ----
    server.reset()
    server.push(mode="reset")
    grabber7 = g.CourseGrabber(CREDS, timeout=2)
    try:
        grabber7.choose("C1", "TYKC")
        FAILURES.append("连接被掐断却没有抛 RequestException——界面会当成普通回复")
        print("  FAIL 连接掐断没抛异常")
    except requests.RequestException as error:
        print("  ok   连接被掐断 → RequestException（界面会归成「网络不通」）：%s"
              % type(error).__name__)
    except Exception as error:
        FAILURES.append("连接掐断抛的不是 RequestException：%r" % error)
        print("  FAIL 抛了别的异常：%r" % error)

    # ---- F3 超时 ----
    server.reset()
    server.push(delay=1.5, body='{"code":"0","msg":"迟到"}')
    grabber8 = g.CourseGrabber(CREDS, timeout=0.4)
    started = time.time()
    try:
        grabber8.choose("C1", "TYKC")
        FAILURES.append("超时却没有抛异常")
        print("  FAIL 超时没抛异常")
    except requests.RequestException as error:
        print("  ok   超时 %.1fs 后抛出 %s" % (time.time() - started,
                                              type(error).__name__))

    # ---- F4 空回复 ----
    server.reset()
    # 推两条空的：第一次空回复会触发一次「换格式再试」（每个会话只探这一次），
    # 两条都空时拿到的就是空回复本身。
    server.push_many(2, body="")
    grabber9 = g.CourseGrabber(CREDS, timeout=2)
    check("空回复归成 server_error", g.classify(grabber9.choose("C1", "TYKC")),
          "server_error")

    # ---- F5 既不是 JSON 也不是 HTML（比如网关返回的纯文本）----
    server.reset()
    server.push(body="Bad Gateway")
    server.push(body="Bad Gateway")
    grabber10 = g.CourseGrabber(CREDS, timeout=2)
    kind5 = g.classify(grabber10.choose("C1", "TYKC"))
    check_true("纯文本异常回复归成「看不懂/异常」而不是「凭证失效」",
               kind5 in ("unknown", "server_error"), kind5)

    # ---- F6 对时：缺 Date 头 ----
    server.reset()
    server.push(body="{}", headers={"_no_date": "1"})
    grabber11 = g.CourseGrabber(CREDS, timeout=2)
    try:
        grabber11.server_clock_offset()
        FAILURES.append("缺 Date 头时对时居然成功了")
        print("  FAIL 缺 Date 头没有报错")
    except g.CredentialError as error:
        print("  ok   缺 Date 头 → CredentialError（界面会提示可不用该功能）：%s"
              % error)

    # ---- F7 对时：正常 ----
    server.reset()
    server.push_json({"code": "0"})
    grabber12 = g.CourseGrabber(CREDS, timeout=2)
    offset = grabber12.server_clock_offset()
    check_true("正常对时得到的偏差应该很小（<2 秒）", abs(offset) < 2.0,
               "实际 %.3f" % offset)

    # ---- F8 登录页 HTML → 明确的「要重贴凭证」而不是「看不懂」 ----
    server.reset()
    server.push(status=200, body="<!DOCTYPE html><html><body>请登录</body></html>")
    grabber13 = g.CourseGrabber(CREDS, timeout=2)
    try:
        grabber13.query_selected()
        FAILURES.append("会话失效时 query_selected 居然没报错")
        print("  FAIL 登录页没有报错")
    except g.CredentialError as error:
        check_true("登录页 → 提示重新复制凭证",
                   "凭证" in str(error) or "登录" in str(error), str(error))

    # ---- F9 自检 preflight：批次码不对时要说清楚 ----
    server.reset()
    server.push_json({"dataList": []})          # courseResult.do 空（没选到课也不算错）
    server.push_many(12, body='{"dataList":[]}')  # 四个类型各试两页都空
    grabber14 = g.CourseGrabber(CREDS, timeout=2)
    report = grabber14.preflight()
    check("自检通过（凭证可用）", report["ok"], True)
    check("批次码判定为不可用", report["batch_ok"], False)
    check_true("给了人话解释", "批次码" in report["note"], report["note"])

    # ---- F10 凭证不全就不该建对象 ----
    try:
        g.CourseGrabber({"student_code": "2023123456", "cookie": "x",
                         "token": "", "batch": ""})
        FAILURES.append("凭证不全却能建出 CourseGrabber")
        print("  FAIL 凭证不全没拦住")
    except g.CredentialError as error:
        check_true("凭证不全 → CredentialError 且点名缺什么",
                   "token" in str(error) and "批次码" in str(error), str(error))

finally:
    server.stop()
    g.BASE_URL = "http://bkxk.szu.edu.cn/"


print("\n" + "=" * 72)
print("跑了 %d 项检查，失败 %d 项" % (CHECKS[0], len(FAILURES)))
if FAILURES:
    for item in FAILURES:
        print("  · " + item)
print("=" * 72)
sys.exit(1 if FAILURES else 0)

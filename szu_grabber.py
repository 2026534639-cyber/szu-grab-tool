# -*- coding: utf-8 -*-
# 版权所有 © 2026 理不尽（本版）。
# 上游原作 © Lewin671/YourLesson；维护版 © guiyi886/szu_grab_course。
# 详见同目录 LICENSE 与 RELEASES.md（谁做了什么、哪次发布了哪个文件）。
"""深大抢课助手 · 协议核心

只做一件事：和深圳大学本科选课系统（bkxk.szu.edu.cn）说话——
认凭证、查课程、提交选课、查已选结果。界面在 szu_grab_app.py。

━━━━━━━━━━━━ 署名与来源 ━━━━━━━━━━━━
这个工具是站在别人肩膀上做的，所以把谁做了什么写清楚：

  上游原作 · Lewin671（昵称 qingyingliu）「深圳大学抢课系统」
      https://github.com/Lewin671/YourLesson

  本版所依据的维护版 · guiyi886（显示名 guyi_ac）
      https://github.com/guiyi886/szu_grab_course
      该仓库 README 写明「复刻于 Lewin671/YourLesson 后进行维护和更新」。
      接口用法、四个凭证字段从哪来，都出自这里，但本文件是按这些公开
      信息重写的，不是原脚本本身。
      该仓库的其他提交者：qingyingliu、Red_Hairy_Mouse

  本版 · 理不尽
      重新实现协议层、重新设计界面、打包成 exe

  注：上面两个仓库都没有标注开源许可证。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

仅供个人选课辅助，请遵守《深圳大学本科生选课管理规定》。
本文件不依赖任何界面库，可以单独 import 使用。
"""

from __future__ import annotations

import json
import random
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.parse import unquote, unquote_plus, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "http://bkxk.szu.edu.cn/"

# 请求超时：(连接超时, 读取超时) 秒。
# 连接单独给短一点：连不上时（比如 VPN 没把路由装好）能快点报错、快点重试，
# 而不是干等 15 秒。配合下面的「连接失败自动重试 2 次」，
# 在校园 VPN 丢包/抖动的情况下成功率会高不少。
REQUEST_TIMEOUT = (6, 20)
CONNECT_RETRIES = 2

# 系统里的课程类型代码 → 学生看得懂的名字
COURSE_TYPES = {
    "TJKC": "本班课程",
    "FANKC": "方案内课程",
    "FAWKC": "方案外课程",
    "XGXK": "校公选课",
    "TYKC": "体育课程",
    "FXKC": "辅修课程",
    "MOOC": "慕课",
}

# 搜课默认覆盖的范围：新生真正会去抢的几类
COMMON_SEARCH_TYPES = ("TYKC", "XGXK", "TJKC", "FANKC")

# 抢课速度预设，(名字, 最小间隔毫秒, 最大间隔毫秒)，从上到下由慢到快。
# 名字里必须带上间隔秒数：原来叫「稳妥 / 标准 / 快速」，光看词分不出谁快谁慢。
SPEED_PRESETS = (
    ("慢　　每 0.5~0.9 秒提交一次", 500, 900),
    ("中　　每 0.35~0.6 秒提交一次", 350, 600),
    ("快　　每 0.2~0.4 秒提交一次", 200, 400),
)

# ── 「开抢那一瞬间」用的参数 ──────────────────────────────────────────
# 名额是统一时间点释放的，所以真正决定成败的是「释放后的第一瞬间」。
# 做法：先跟服务器对时，提前一点开始高频提交，冲一小段时间就收手——
# 而不是长时间高频（那样容易被风控，反而更慢）。
BURST_LEAD = 2.0          # 提前量的下限（具体见 burst_lead_for）
BURST_LEAD_MAX = 8.0      # 提前量的上限：再多就把冲刺窗口本身吃掉了
BURST_WINDOW = 15.0       # 开抢时刻之后还要冲多少秒
BURST_INTERVAL = (100, 180)   # 高频期两次提交之间的毫秒区间


def burst_lead_for(rtt_seconds: float) -> float:
    """冲刺该提前多少秒开始？**按这条路的往返延迟算**，不是写死 2 秒。

    为什么要算：提前发出去，是希望"它正好在名额释放那一刻到达服务器"。
    请求单程要花 RTT 的一半，所以——

      直连（实测 0.16 秒）：单程 0.08 秒，提前 2 秒绰绰有余；
      WebVPN（实测 10 秒）：单程 5 秒，提前 2 秒发出去的请求
                           要等到开抢后 3 秒才到，前面一大截冲刺全白冲。

    取「RTT 的一半」和「下限 2 秒」里大的那个，再封一个上限——提前太多
    会把冲刺窗口本身吃掉（冲刺总时长 = 提前量 + BURST_WINDOW）。
    量不出延迟（rtt 为 0）时用下限。
    """
    if not rtt_seconds or rtt_seconds <= 0:
        return BURST_LEAD
    return min(BURST_LEAD_MAX, max(BURST_LEAD, rtt_seconds / 2.0))

SPEED_HINTS = (
    "推荐。最不容易被系统盯上，第三轮抢课也够用了。",
    "比「慢」快一些，仍然比较稳。",
    "抢得更快，但可能被提示「操作过于频繁」——程序检测到会自动放慢，不会硬撞。",
)

BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Pragma": "no-cache",
    # Host 不写死：按用户粘进来的那条 cURL 里的网址自动填（见 CourseGrabber）。
    # 校内直连是 bkxk.szu.edu.cn，走 WebVPN 时是别的域名，写死就会连错地方。
}


class CredentialError(Exception):
    """凭证不全或不可用。界面直接把这句话显示给用户。"""


# --------------------------------------------------------------------------
# 一、凭证识别
#
# 新手最容易被卡住的地方是从开发者工具里抠 Cookie、token、学号、批次码这四个值。
# 所以这里不要求用户逐个填写，而是让他把「Copy as cURL」的结果整个粘进来，
# 再由下面这些函数把四个值捞出来。为了保证怎么粘都能认，识别分三层：
#   1. 按 cURL 参数解析；
#   2. 在原文、原文解一层 URL 编码后的文本里正则匹配；
#   3. 兜底认中文标签（学号 / 批次码）。
# --------------------------------------------------------------------------

_RE_COOKIE_HEADER = r'(?:^|[\s"\'])cookie["\']?\s*[:=：]\s*["\']?([^"\'\\\r\n]+)'
_RE_COOKIE_ARG = r'--cookie[=\s]+["\']?([^"\'\\\r\n]+)'
_RE_TOKEN = r'(?<![A-Za-z])token["\']?\s*[:=：]\s*["\']?([A-Za-z0-9._\-]{8,})'
_RE_STUDENT = r'(?:studentCode|学号)["\']?\s*[:=：]?\s*["\']?(\d{6,})'
_RE_BATCH = (r'(?:electiveBatchCode|批次码?|批次)["\']?\s*[:=：]?\s*'
             r'["\']?([A-Za-z0-9._\-]{8,})')


# 请求网址：用来判断到底该连哪个域名（校内直连 vs 学校 WebVPN）
_RE_URL = r'(https?://[^\s\'"\\<>]+)'


def _derive_base(url: str) -> str:
    """从请求网址推导出「接口根地址」，返回带结尾斜杠的前缀；推不出来返回空串。

    为什么按网址走、不写死 `http://bkxk.szu.edu.cn/`：这个系统有两种访问形态，
    域名和路径前缀都不一样——

      校内直连： http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/volunteer.do
      WebVPN　： https://webvpn.szu.edu.cn/http/<一串令牌>/xsxkapp/sys/.../volunteer.do

    后者是学校给校外访问准备的网页代理（浏览器里就能用，不必装客户端）。
    取「第一个 /xsxkapp 之前的部分」当根地址，两种形态就都对得上；
    找不到 /xsxkapp 时退一步只取 `协议://域名/`。
    """
    if not url:
        return ""
    marker = url.find("/xsxkapp")
    if marker > 0:
        return url[:marker] + "/"
    match = re.match(r'(https?://[^/\s\'"\\]+)(?:/|$)', url)
    if match:
        return match.group(1) + "/"
    return ""


def _split_curl(text: str) -> list:
    """把一条 cURL 命令拆成参数列表。

    Chrome / Edge 的「Copy as cURL」在三种 shell 下格式不同，这里都认：
      bash       单引号，行尾是反斜杠续行
      cmd        双引号，行尾是 ^ 续行
      powershell 双引号，行尾是反引号续行
    """
    args, buf, quote = [], [], None
    i, n = 0, len(text)
    while i < n:
        ch = text[i]

        if quote:
            # 双引号里 \" \\ 是转义；单引号里一切都是字面量
            if ch == "\\" and quote == '"' and i + 1 < n and text[i + 1] in '"\\$`':
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue

        if ch in "'\"":
            quote = ch
            i += 1
            continue

        if ch in "\\^" and i + 1 < n and text[i + 1] in "\r\n":
            i += 2
            if i <= n and i - 2 >= 0 and text[i - 2] == "\r" and i < n and text[i] == "\n":
                i += 1
            continue

        if ch.isspace():
            if buf:
                args.append("".join(buf))
                buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    if buf:
        args.append("".join(buf))
    return args


def _curl_parts(text: str):
    """从 cURL 命令里取出请求头和请求体。"""
    args = _split_curl(text)
    headers, body = {}, ""
    i = 0
    while i < len(args):
        arg = args[i]
        low = arg.lower()

        if low in ("-h", "--header") and i + 1 < len(args):
            _put_header(headers, args[i + 1])
            i += 2
            continue
        if low.startswith("--header="):
            _put_header(headers, arg[9:])
            i += 1
            continue
        if low in ("-b", "--cookie") and i + 1 < len(args):
            headers.setdefault("cookie", args[i + 1])
            i += 2
            continue
        if low.startswith("--cookie="):
            headers.setdefault("cookie", arg[9:])
            i += 1
            continue
        if low in ("-d", "--data", "--data-raw", "--data-binary",
                   "--data-urlencode") and i + 1 < len(args):
            body = args[i + 1]
            i += 2
            continue
        if low.startswith(("--data-raw=", "--data=", "--data-binary=",
                           "--data-urlencode=")):
            body = arg.split("=", 1)[1]
            i += 1
            continue
        i += 1

    return headers, body


def _put_header(headers: dict, line: str) -> None:
    if ":" not in line:
        return
    key, value = line.split(":", 1)
    key = key.strip().lower()
    if key:
        headers.setdefault(key, value.strip())


def _first_match(candidates, pattern: str) -> str:
    """在若干候选文本里依次找第一个匹配。"""
    for text in candidates:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return ""


def _clean_cookie(value: str) -> str:
    """把 Cookie 头那一串收拾干净。

    这里有两个方向相反的坑，必须都躲开：

    1. **有的复制格式会把 cookie 和 token 挤成一行**（例如
       `cookie: a=b' -H 'token: xxxxx`），截断成只留 cookie 那半截是对的；
    2. **但 cookie 本身可能带引号**，那种情况下在第一个引号处无脑切开，
       就会把后半段（往往正是 JSESSIONID 那种关键的那一段）**悄悄丢掉**，
       结果就是服务器认为你没登录、回一个登录页——而用户看着手里明明是新凭证，
       只会以为"凭证又过期了"。

    所以只在「引号后面明显接着另一个头」时才截断。判断不出来就原样保留。
    """
    text = (value or "").strip()
    if not text:
        return ""
    if text.lower().startswith("token:"):
        return ""          # 整段就是 token，那这个字段本来就是空的
    parts = re.split(r'["\']', text)
    if len(parts) > 1 and re.match(r"\s*(--?\w|token\b|cookie\b)",
                                   "".join(parts[1:])):
        return parts[0].strip()
    return text


def cookie_pairs(cookie: str) -> list:
    """把 Cookie 拆成 [名字, ...]（只取名字，不含值）——给界面显示用。

    为什么要给用户看这个：粘进来的 Cookie 少一段，光看"✅ Cookie（120 字符）"
    是看不出来的，但少一段就会导致服务器回登录页。把名字列出来，
    用户能直接跟浏览器里那几段对照。
    """
    names = []
    for item in (cookie or "").split(";"):
        item = item.strip()
        if not item:
            continue
        names.append(item.split("=", 1)[0].strip())
    return names


def parse_credentials(text: str) -> dict:
    """从用户粘贴的任何内容里尽力认出四个凭证字段。

    认得出来就有值，认不出来的留空字符串，由界面提示用户补。
    返回 {"student_code", "cookie", "token", "batch"}。
    """
    raw = text or ""
    result = {"student_code": "", "cookie": "", "token": "", "batch": "",
              "base_url": ""}
    if not raw.strip():
        return result

    headers, body = _curl_parts(raw)

    # 同一段文字可能有几种编码形态，每种都当候选：
    #   · 原样
    #   · 把 JS 字符串里的 \" 还原成 "（「Copy as fetch」是这种）
    #   · 解一层百分号编码（cURL 的表单体是这种）
    candidates = []
    for source in ((body, raw) if body else (raw,)):
        candidates.append(source)
        candidates.append(source.replace('\\"', '"').replace("\\'", "'"))
        candidates.append(unquote(source))
        candidates.append(unquote_plus(source))

    cookie = headers.get("cookie", "")
    if not cookie:
        cookie = (_first_match(candidates, _RE_COOKIE_HEADER)
                  or _first_match(candidates, _RE_COOKIE_ARG))
    cookie = _clean_cookie(cookie)

    token = headers.get("token", "") or _first_match(candidates, _RE_TOKEN)

    result["cookie"] = cookie
    result["token"] = token
    result["student_code"] = _first_match(candidates, _RE_STUDENT)
    result["batch"] = _first_match(candidates, _RE_BATCH)
    # 请求网址：决定程序连哪个域名（校内直连 / WebVPN 都靠它）
    result["base_url"] = _first_match(candidates, _RE_URL)
    # 请求头：原样带上（浏览器发过什么，我们就发什么）
    result["headers"] = {k: v for k, v in headers.items()
                         if k.lower() not in _HEADERS_WE_REBUILD}
    return result


MISSING_LABELS = (
    ("student_code", "学号"),
    ("cookie", "Cookie"),
    ("token", "token"),
    ("batch", "批次码"),
)


def missing_fields(creds: dict) -> list:
    """返回还没认出来的字段的中文名。"""
    return [label for key, label in MISSING_LABELS if not creds.get(key)]


# --------------------------------------------------------------------------
# 二、结果翻译
#
# 系统回的是接口消息，五花八门。这里统一翻译成学生看得懂的一句话，
# 并给出「还要不要继续抢」的判断。
# --------------------------------------------------------------------------

# 结果归类规则。顺序有讲究：**越具体的越靠前**。
#
# 踩过的坑：原来「已满」这条（名额满）排在「学分」前面，于是系统回一句
# 「学分已满」会被读成「名额满」——名额满是要一直蹲的，结果这门课永远
# 停在"继续试"，而它其实根本选不上（学分上限到了）。所以「学分 / 限选 /
# 冲突 / 重复」这些能被判定为「再试也没用」的说法，一律排在「已满」前面。
RESULT_RULES = (
    ("success", ("添加选课志愿成功", "选课成功", "添加成功", "提交成功")),
    ("throttle", ("操作过于频繁", "频繁", "请稍后")),
    # 凭证失效。注意**不要**把「超时」「失效」单独放进来：系统回一句
    # 「请求超时」时，那是网络慢，不是凭证废了，判错会让整轮白停。
    ("auth", ("未登录", "请登录", "登录已", "登录状态", "会话", "凭证", "token")),
    ("batch", ("批次",)),
    ("dup", ("重复选课", "已经选", "已选中", "已选该", "已选择该", "不可重复")),
    ("credit", ("学分",)),
    ("limit", ("限选", "限制")),
    ("conflict", ("冲突",)),
    ("perm", ("不属于", "无权限", "不允许", "非本", "没有权限")),
    ("full", ("超过课容量", "课容量已满", "名额已满", "已达上限", "人数已满",
              "已满", "余量不足")),
    ("closed", ("不在选课时间", "选课时间", "选课已结束", "未开始", "尚未开放",
                "不在开放")),
    ("server_error", ("错误", "异常", "失败", "error", "exception")),
)

RESULT_MESSAGES = {
    "success": "抢到了！",
    "full": "名额满了，继续蹲",
    "throttle": "请求太密，自动放慢",
    "closed": "还没到选课时间，等一下再试",
    "conflict": "和已选课程时间冲突",
    "credit": "学分已满，选不了更多",
    "perm": "这门课你没有选课权限",
    "dup": "这门课你本来就选上了",
    "auth": "登录已失效，需要重新粘贴凭证",
    "batch": "批次码不对，需要重新获取凭证",
    "limit": "有人数或类别限制",
    "network": "网络不通",
    "busy_server": "选课系统自己出错了，稍后自动重试",
    "server_error": "系统返回了异常",
    "unknown": "系统回复",
}

# 抢下去也没用的结果：不再重试这门课
FATAL_RESULTS = {"conflict", "credit", "perm", "limit"}
# 整轮都要停下来的结果：凭证出了问题
STOPALL_RESULTS = {"auth", "batch"}
# 不是这门课的问题、也不是用户的问题：服务器/网络自己抽风，不算这门课的账
TRANSIENT_RESULTS = {"network", "busy_server"}


# 从用户粘的 cURL 里抄请求头时，这几个不要抄：
#   content-length 会变（要按实际发的体重算）；host 要跟实际连的域名一致；
#   connection / accept-encoding 交给 requests 自己管（照抄 "br" 我们解不开）；
#   cookie / token 用我们解析出来的那两个字段，避免两处不一致。
_HEADERS_WE_REBUILD = {"content-length", "host", "connection", "accept-encoding",
                       "cookie", "token"}

READ_ATTEMPTS = 3


def _with_retry(do, attempts: int = READ_ATTEMPTS, delay: float = 0.7):
    """给「只读」的请求自动重试几次。

    为什么只给读操作加：校园 VPN 抖一下就会让一次请求失败，而读操作（查课程、
    查已选、对时）重发没有任何副作用。**提交选课不能在这里重试**——重发有可能
    造成重复提交，那个由抢课循环自己控制节奏。

    只抓传输层的错（requests.RequestException）；像"服务器回登录页"这种
    会话问题会抛 CredentialError，重试没用，直接往上抛。
    """
    last = None
    for index in range(max(1, attempts)):
        try:
            return do()
        except requests.RequestException as error:
            last = error
            if index < attempts - 1:
                time.sleep(delay * (index + 1))
    raise last


def _looks_like_html(text: str) -> bool:
    """服务器在会话失效时会用 HTTP 200 回一个登录页，而不是报错。"""
    head = text[:2000].lower()
    return "<html" in head or "<!doctype" in head or "<body" in head


def classify(text: str) -> str:
    """把接口回复归类成一个代号。认得出来就返回代号，否则 unknown。"""
    if not text:
        return "server_error"
    # 这一步必须排在关键词前面：登录页 HTML 里通常也写着「选课时间」之类的
    # 字样，先跑关键词就会把「凭证过期」误判成「还没到选课时间」，
    # 于是脚本一直傻等，用户却不知道要重新贴凭证。
    if _looks_like_html(text):
        return "auth"
    blob = text
    try:
        parsed = json.loads(text)
        blob = text + " " + json.dumps(parsed, ensure_ascii=False)
    except Exception:
        pass
    low = blob.lower()
    for kind, keywords in RESULT_RULES:
        for word in keywords:
            if word.lower() in low:
                return kind
    return "unknown"


def plain_result(kind: str, text: str = "", limit: int = 60) -> str:
    """给用户看的一句话。翻译不了就把原文截断显示。"""
    label = RESULT_MESSAGES.get(kind, "系统回复")
    if kind in ("unknown", "server_error"):
        raw = _readable_message(text)
        if raw:
            return "%s：%s" % (label, raw[:limit])
    return label


def _readable_message(text: str) -> str:
    """尽量从接口回复里摘出给人看的那句话。"""
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except Exception:
        stripped = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", stripped).strip()[:200]
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and value.strip():
                    found.append(value.strip())
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(parsed)
    return " / ".join(found)[:200]


# --------------------------------------------------------------------------
# 三、抢课客户端
# --------------------------------------------------------------------------

def _text_of(response) -> str:
    """选课系统的编码偶尔不写对，这里硬解一次。"""
    for encoding in ("utf-8", "gb18030"):
        try:
            return response.content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return response.text


def _as_text(value) -> str:
    """接口字段有时是列表，统一成一行字符串。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


class CourseGrabber:
    """一个登录会话。四个凭证齐了才能建。"""

    def __init__(self, creds: dict, timeout: int = REQUEST_TIMEOUT):
        self.student_code = (creds.get("student_code") or "").strip()
        self.cookie = (creds.get("cookie") or "").strip()
        self.token = (creds.get("token") or "").strip()
        self.batch = (creds.get("batch") or "").strip()
        self.timeout = timeout

        missing = missing_fields(creds)
        if missing:
            raise CredentialError("凭证还缺：%s" % "、".join(missing))

        # 连哪里，跟着用户粘进来的那条 cURL 走（校内直连 / WebVPN 都支持）。
        # 推不出来就用默认的校内地址。
        self.base = _derive_base(creds.get("base_url") or "") or BASE_URL
        self.host = urlparse(self.base).netloc or "bkxk.szu.edu.cn"

        self.session = requests.session()
        # 连接失败自动重试（只重试「连接」这一步：那是在请求真正发出去之前失败的，
        # 不会造成重复提交）。校园 VPN 丢包/抖动时，这一层能救回不少请求。
        retry = Retry(total=CONNECT_RETRIES, connect=CONNECT_RETRIES, read=0,
                      redirect=0, status=0, backoff_factor=0.5,
                      allowed_methods=None)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # 请求头以「用户粘进来的那条 cURL 里的头」为底——浏览器发过什么，
        # 我们就发什么。之前是自己拼一套（少了 Origin / Referer / Sec-Fetch-* /
        # sec-ch-ua* 这些），服务器有可能因此把我们当成"不是页面里发出来的请求"，
        # 未登录状态下就直接回**登录页 HTML**（HTTP 200），
        # 表现就是「明明刚拿的凭证却说已失效」。
        # 键统一用小写，避免出现 User-Agent 和 user-agent 两条重复。
        headers = {k.lower(): v for k, v in BASE_HEADERS.items()}
        for key, value in (creds.get("headers") or {}).items():
            headers[key.lower()] = value
        # 这三个必须由我们决定：Cookie/token 用解析出来的字段，
        # Host 按实际连的域名（走 WebVPN 时是 bkxk.webvpn.szu.edu.cn）
        headers["cookie"] = self.cookie
        headers["token"] = self.token
        headers["host"] = self.host
        # 粘进来的那条 cURL 里没有的话，补上浏览器一定会发的两个
        if "referer" not in headers:
            headers["referer"] = (self.base
                                  + "xsxkapp/sys/xsxkapp/*default/grablessons.do"
                                  + ("?token=" + self.token if self.token else ""))
        if "x-requested-with" not in headers:
            headers["x-requested-with"] = "XMLHttpRequest"
        if "origin" not in headers:
            parsed = urlparse(self.base)
            headers["origin"] = "%s://%s" % (parsed.scheme, parsed.netloc)
        self.headers = headers

        # 提交选课时的参数格式。两种写法字段一样，区别只在几个值带不带引号。
        # 默认用 legacy（裸数字）：上游原稿、维护版、以及本项目依据的 v1
        # **全都用它**，是有实战记录的那一种；带引号的 json 当兜底，
        # 被系统退回（或回了一句读不懂的话）时自动换过去，只探一次。
        self.add_param_style = "legacy"
        self.style_switched = False
        self.style_confirmed = False
        self.last_status = 200      # 最近一次提交的 HTTP 状态码
        self.last_rtt = 0.0         # 最近一次对时的往返延迟（秒）

        # 页码起点：照用户浏览器里的真实请求，第一页是 **0**（不是 1）。
        # 如果这个部署是按 1 起算的，_page_one 会自动发现并改过来。
        self._page_base = 0
        self._page_size = 50        # 先按一页 50 条试，系统不认就退回 10
        self._saw_data = False      # 是否已经从服务器拿到过课程

    # ---------------- 底层请求 ----------------

    def _get(self, path: str):
        return self.session.get(self.base + path, headers=self.headers,
                                timeout=self.timeout)

    def _read_server_time(self):
        """发一次请求，读回「服务器时间」和这次请求的本机起止时刻。"""
        before = time.time()
        response = _with_retry(
            lambda: self._get("xsxkapp/sys/xsxkapp/*default/index.do"))
        after = time.time()
        if response.status_code != 200:
            raise CredentialError("服务器返回 %s，对时中止" % response.status_code)
        raw = response.headers.get("Date")
        if not raw:
            raise CredentialError("服务器没返回时间，无法对时（可以不用这个功能）")
        try:
            stamp = parsedate_to_datetime(raw)
        except Exception:
            raise CredentialError("服务器时间读不出来，无法对时")
        if stamp.tzinfo is None:
            # HTTP 头里的日期按 RFC 就是 GMT。万一哪台机器/代理没写时区，
            # datetime.timestamp() 会按本机时区去解释，中国这边就直接偏 8 小时——
            # 那意味着到点冲了个寂寞。所以缺时区时一律当 UTC。
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp(), before, after

    def server_clock_offset(self) -> float:
        """粗对时：一条请求，精度大约 ±0.5 秒（受 Date 只到整秒的限制）。

        顺便把这次请求的往返延迟记在 self.last_rtt 上——冲刺的提前量要按它算
        （见 burst_lead_for：网络越慢，越要更早出发，否则请求到得太晚）。
        """
        server, before, after = self._read_server_time()
        self.last_rtt = max(0.0, after - before)
        return server - (before + after) / 2.0

    def _post(self, path: str, data=None):
        return self.session.post(self.base + path, data=data or {},
                                 headers=self.headers, timeout=self.timeout)

    def _fetch_page(self, ctype: str, page: int, page_size: int) -> dict:
        if ctype == "TJKC":
            path = "xsxkapp/sys/xsxkapp/elective/recommendedCourse.do"
        else:
            path = "xsxkapp/sys/xsxkapp/elective/programCourse.do"
        query = {
            "data": {
                "studentCode": self.student_code,
                "campus": "01",
                "electiveBatchCode": self.batch,
                "isMajor": "1",
                "teachingClassType": ctype,
                "checkConflict": "2",
                "checkCapacity": "2",
                "queryContent": "YCJX:2,MOOC:2,",   # 照浏览器实际发的抄
            },
            "pageSize": str(page_size),
            "pageNumber": str(page),
            "order": "",
            "orderBy": "courseNumber",
        }
        payload = {"querySetting": json.dumps(query, ensure_ascii=False)}
        # 翻页时网络抖一下就整轮搜索失败太苛刻了，这里自动重试几次
        return _with_retry(lambda: self._load_json(self._post(path, payload)))

    def _load_json(self, response) -> dict:
        text = _text_of(response)
        try:
            return json.loads(text)
        except Exception:
            status = getattr(response, "status_code", 200)
            if status >= 500:
                # 服务器/网关自己故障时也常回一个 HTML 错误页。不能把它当成
                # 「登录页」去让用户重贴凭证——凭证是好的，是服务器在打嗝。
                raise CredentialError(
                    "选课系统自己出错了（HTTP %d），过一会儿再试" % status)
            if "<html" in text.lower() or "login" in text.lower():
                raise CredentialError(
                    "登录状态已失效（服务器返回的是登录页）。请重新复制一次凭证。"
                    "若你刚重连过学校 VPN，先在浏览器刷新一下选课页面确认自己还登录着"
                    "——VPN 掉线时服务器回的也是登录页，那种情况重贴凭证也没用")
            raise CredentialError("服务器返回了看不懂的内容，请检查凭证是否完整")

    # ---------------- 查课程 ----------------

    def _page_one(self, ctype: str) -> list:
        """拉某个类型的第一页，顺便确认系统认不认我们用的每页条数。

        官网页面是一页 10 条，这里先试 50 条（少发几次请求）。只有在一个
        课程都还没拿到过的情况下才怀疑是页大小的问题，避免把「这个类型本来
        就是空的」误判成系统不认。
        """
        data = self._fetch_page(ctype, self._page_base,
                               self._page_size).get("dataList") or []
        if data:
            self._saw_data = True
            return data

        if not self._saw_data and self._page_base == 0:
            alt = self._fetch_page(ctype, 1, self._page_size).get("dataList") or []
            if alt:
                # 这个部署是按 1 起算的，后面都跟着改
                self._page_base = 1
                self._saw_data = True
                return alt

        if not self._saw_data and self._page_size != 10:
            data = self._fetch_page(ctype, self._page_base,
                                    10).get("dataList") or []
            if data:
                self._saw_data = True
        return data

    def _iter_type(self, ctype, on_page=None, should_stop=None):
        """按页拉完一个课程类型，翻到没有数据为止。"""
        rows, page = [], self._page_base
        while page < self._page_base + 200:      # 最多翻 200 页，别翻到天荒地老
            if should_stop and should_stop():
                break
            if page == self._page_base:
                data = self._page_one(ctype)
            else:
                data = self._fetch_page(ctype, page, self._page_size).get("dataList") or []
            if not data:
                break

            for course in data:
                rows.extend(self._rows_of(course, ctype))
            if on_page:
                on_page(ctype, page, len(rows))
            page += 1
            time.sleep(0.25)
        return rows

    def _rows_of(self, course, ctype) -> list:
        name = _as_text(course.get("courseName"))
        rows = []
        for teaching_class in (course.get("tcList") or []):
            class_id = _as_text(
                teaching_class.get("teachingClassID")
                or teaching_class.get("teachingClassId")
                or teaching_class.get("id"))
            if not class_id:
                continue
            capacity = teaching_class.get("classCapacity")
            selected = teaching_class.get("numberOfSelected")
            try:
                is_full = int(selected) >= int(capacity)
            except (TypeError, ValueError):
                is_full = False
            rows.append({
                "id": class_id,
                "name": name,
                "teacher": _as_text(teaching_class.get("teacherName")),
                "place": _as_text(teaching_class.get("teachingPlace")
                                  or teaching_class.get("teachingTime")),
                "selected_count": _as_text(selected),
                "capacity": _as_text(capacity),
                "chosen": bool(teaching_class.get("selected")),
                "conflict": _as_text(teaching_class.get("conflictDesc")),
                "full": is_full,
                "type": ctype,
                "type_name": COURSE_TYPES.get(ctype, ctype),
            })
        return rows

    def search(self, keyword: str, types, on_progress=None, should_stop=None) -> list:
        """按关键词搜课。关键词为空就是列出全部。

        同一条教学班可能同时属于多个类型，按教学班号去重。
        """
        key = (keyword or "").strip().lower()
        rows, seen = [], set()
        for ctype in types:
            if should_stop and should_stop():
                break
            for row in self._iter_type(ctype, on_page=(
                    (lambda c, p, n, _c=ctype: on_progress(
                        COURSE_TYPES.get(_c, _c), p, n)) if on_progress else None),
                    should_stop=should_stop):
                if row["id"] in seen:
                    continue
                seen.add(row["id"])
                if key and key not in (row["name"] + row["teacher"]).lower():
                    continue
                rows.append(row)
        rows.sort(key=_display_order)
        return rows

    # ---------------- 抢课 ----------------

    def _add_param(self, class_id: str, ctype: str, style: str) -> str:
        if style == "json":
            return json.dumps({"data": {
                "operationType": "1",
                "studentCode": self.student_code,
                "electiveBatchCode": self.batch,
                "teachingClassId": class_id,
                "isMajor": "1",
                "campus": "01",
                "teachingClassType": ctype,
                "chooseVolunteer": "1",
            }}, ensure_ascii=False, separators=(",", ":"))

        # 兼容写法：值和官网一样，但不加引号，和早期开源脚本一致
        return ('{"data":{"operationType":"1","studentCode":%s,'
                '"electiveBatchCode":%s,"teachingClassId":%s,'
                '"isMajor":"1","campus":"01","teachingClassType":%s,'
                '"chooseVolunteer":"1"}}'
                % (self.student_code, self.batch, class_id, ctype))

    def _submit(self, class_id: str, ctype: str, style: str):
        """提交一次，返回 (正文, HTTP 状态码)。"""
        response = self._post("xsxkapp/sys/xsxkapp/elective/volunteer.do",
                              {"addParam": self._add_param(class_id, ctype, style)})
        return _text_of(response), response.status_code

    def choose(self, class_id: str, ctype: str) -> str:
        """提交一次选课，返回系统原文。

        关于「参数格式」：这个接口的 addParam 有两种写法，字段完全一样，
        区别只在几个值带不带引号——
          legacy（裸数字）："studentCode":2023123456
          json（带引号）　："studentCode":"2023123456"
        上游原稿（Lewin671/YourLesson）和维护版（guiyi886/szu_grab_course）
        **都发裸数字那种**，本项目所依据的 v1 也是——所以默认用它，
        因为它是有实战记录的那一种；带引号的那种当兜底。

        第一次提交如果**没能得到一个能读懂的答复**，就换另一种再试一次
        （只试这一次：style_confirmed）。为什么放宽到"读不懂就试"而不是
        "提到参数/格式才试"：这次试探最多多花一个请求，而选错格式的代价是
        这门课整轮抢不到——代价不对称，宁可多试一次。确认之后每次只发一次，
        否则遇到正常业务回复里的「失败」字样就会每次都发两遍、请求量翻倍。
        服务器自己 5xx 时不试：那种回复说明不了格式对不对。
        """
        text, status = self._submit(class_id, ctype, self.add_param_style)

        # 只有"服务器真的回话了"才算把格式这件事问清楚：
        #   · 回话能读懂        → 格式没问题，确认
        #   · 回话读不懂        → 换另一种试一次，试完也算问过（再试就会每次都发两遍）
        #   · 服务器 5xx        → 它自己坏了，回话说明不了格式对不对，
        #                        这次不算问过，保持未确认，下次还有机会探
        if not self.style_confirmed and status < 500:
            if _looks_broken(text) or classify(text) in ("unknown", "server_error"):
                other = "legacy" if self.add_param_style == "json" else "json"
                text2, status2 = self._submit(class_id, ctype, other)
                if (not _looks_broken(text2)
                        and classify(text2) not in ("unknown", "server_error")):
                    if other != self.add_param_style:
                        self.add_param_style = other
                        self.style_switched = True
                    text, status = text2, status2
            self.style_confirmed = True

        self.last_status = status
        return text

    # ---------------- 查结果与自检 ----------------

    def query_selected(self) -> list:
        """查已经选上的课。"""
        path = ("xsxkapp/sys/xsxkapp/elective/courseResult.do"
                "?timestamp=%s&studentCode=%s" % (_timestamp(), self.student_code))
        payload = _with_retry(lambda: self._load_json(self._post(path)))
        rows = []
        for item in (payload.get("dataList") or []):
            rows.append({
                "name": _as_text(item.get("courseName")),
                "teacher": _as_text(item.get("teacherName")),
                "place": _as_text(item.get("teachingPlace")),
            })
        return rows

    def preflight(self) -> dict:
        """抢课前自检：凭证能不能用、批次码对不对、现在选上了几门。

        这一步的价值在于把「粘错了」当场暴露出来，而不是等到开抢那几秒才发现。
        """
        report = {"ok": False, "selected": [], "batch_ok": False,
                  "courses_visible": 0, "note": ""}
        report["selected"] = self.query_selected()
        report["ok"] = True

        # 拉一页课，验证批次码；批次码不对时接口会返回空列表
        for ctype in COMMON_SEARCH_TYPES:
            count = len(self._page_one(ctype))
            if count:
                report["batch_ok"] = True
                report["courses_visible"] = count
                break
        if not report["batch_ok"]:
            report["note"] = ("拉不到任何课程，批次码可能不对或现在已经过了选课时间，"
                              "建议重新复制一次凭证")
        return report


def _looks_broken(text: str) -> bool:
    """这次提交是不是被系统当成「参数格式不对」退回来了。

    这个判断的代价是不对称的：判成「格式不对」就会换一种格式再发一遍，
    也就是多发一次请求。原来只要回复里有「错误 / 失败」就算，于是系统正常
    回一句「选课失败，原因：课容量已满」也会被当成格式问题——每次提交都发
    两遍请求，抢课时的实际频率翻倍，反而更容易被限速。

    所以现在的规矩是：**只要这句回复能被读懂（成功 / 名额满 / 太频繁 / …），
    就说明格式没问题**；只有读不懂、而且明确在说参数/格式，才算格式不对。
    登录页 HTML 不算——那是凭证过期，换格式也救不回来。
    """
    if not text or not text.strip():
        return True
    if _looks_like_html(text):
        return False
    if classify(text) not in ("unknown", "server_error"):
        return False
    low = text.lower()
    return any(word in low for word in (
        "参数", "格式", "解析", "parameter", "parse", "malformed", "无法识别",
    ))


def _timestamp() -> str:
    return str(int(time.time() * 1000))


def _display_order(row: dict):
    """排序：还能抢的排最前面，其次已选，再其次冲突，最后是满的。"""
    if row["chosen"]:
        rank = 1
    elif row["conflict"]:
        rank = 2
    elif row["full"]:
        rank = 3
    else:
        rank = 0
    return rank, row["name"], row["teacher"]


def status_of(row: dict) -> str:
    """一行课程的状态标签。"""
    if row["chosen"]:
        return "已选"
    if row["conflict"]:
        return "时间冲突"
    if row["full"]:
        return "名额已满"
    return "有名额"


def parse_start_time(text: str):
    """把「12:30」「12:30:00」解析成"当天过了多少秒"；认不出来返回 None。

    顺手容忍中文写法：全角冒号、以及「12点30分」这种。填错就返回 None，
    由界面提示用户，而不是猜一个时间出来。
    """
    cleaned = (text or "").strip()
    for ch in ("：", "点", "时", "分"):
        cleaned = cleaned.replace(ch, ":")
    parts = [part.strip() for part in cleaned.split(":") if part.strip() != ""]
    if not parts or len(parts) > 3:
        return None
    if len(parts) == 1:
        # 只写了一个数字：只认「930」「1230」这种紧凑写法，别的当填错。
        # 不能把「12」当成 12:00——那会让程序在错误的时间开冲，还不如报错。
        digits = parts[0]
        if not digits.isdigit() or len(digits) not in (3, 4):
            return None
        nums = [int(digits[:-2]), int(digits[-2:]), 0]
    else:
        try:
            nums = [int(part) for part in parts]
        except ValueError:
            return None
        while len(nums) < 3:
            nums.append(0)
    hour, minute, second = nums
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        return None
    return hour * 3600 + minute * 60 + second


def seconds_until_start(start_seconds: int, clock_offset: float, now=None) -> float:
    """距离「开抢时刻」还有多少秒，跨零点的情况也处理。

    坑在哪：如果选课在 00:00 开放，用户 23:55 就把工具挂上，按今天算
    「00:00」已经过去 23 小时 55 分，程序会以为时间早过了、直接不冲，
    正好错过最要紧的那一刻。所以「按今天算已经过去超过 12 小时」时，
    一律理解成「再过一天的那个时刻」。
    """
    left = seconds_until(start_seconds, clock_offset, now)
    if left < -43200:          # 12 小时
        left += 86400
    return left


def server_seconds_now(clock_offset: float, now=None) -> float:
    """按「服务器的钟」，现在是一天中的第几秒。

    高频窗口的起止都用这个量纲，别拿 time.time()（1970 年起的秒数）去比——
    两者差着几十亿，比出来永远是"已经结束"。
    """
    t = time.localtime((now if now is not None else time.time()) + clock_offset)
    return float(t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)


def seconds_until(start_seconds: int, clock_offset: float, now=None) -> float:
    """按「服务器的钟」算距离今天这个时刻还有多少秒（可能为负，表示已经过了）。"""
    return float(start_seconds) - server_seconds_now(clock_offset, now)


def next_delay(delay_range, last_kind: str, on_note=None):
    """决定下一次提交前等多久。

    被系统嫌弃「太频繁」就成倍放慢，回到正常结果后再自动降回来，
    这样既不会越撞越猛，也不会因为一次限速就再也抢不到。
    """
    low, high = delay_range
    if last_kind == "throttle":
        low, high = low * 1.8, high * 1.8
    elif last_kind in ("network", "busy_server"):
        low, high = low * 1.3, high * 1.3
    elif last_kind == "closed":
        low, high = 2500, 3500
    low = int(max(200, min(low, 4000)))
    high = int(max(low, min(high, 5000)))
    if on_note and last_kind == "throttle":
        on_note("被提示操作过于频繁，本次放慢到 %d~%dms" % (low, high))
    return random.uniform(low, high) / 1000.0

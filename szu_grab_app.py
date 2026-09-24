# -*- coding: utf-8 -*-
# 版权所有 © 2026 理不尽（本版）。
# 上游原作 © Lewin671/YourLesson；维护版 © guiyi886/szu_grab_course。
# 详见同目录 LICENSE 与 RELEASES.md（谁做了什么、哪次发布了哪个文件）。
"""深大抢课助手 · 界面

━━━━━━━━━━━━ 署名与来源 ━━━━━━━━━━━━
这个工具是站在别人肩膀上做的，所以把谁做了什么写清楚：

  上游原作 · Lewin671（昵称 qingyingliu）「深圳大学抢课系统」
      https://github.com/Lewin671/YourLesson

  本版所依据的维护版 · guiyi886（显示名 guyi_ac）
      https://github.com/guiyi886/szu_grab_course
      该仓库 README 写明「复刻于 Lewin671/YourLesson 后进行维护和更新」
      该仓库的其他提交者：qingyingliu、Red_Hairy_Mouse

  本版 · 理不尽
      重新实现协议层、重新设计界面、打包成 exe

  注：上面两个仓库都没有标注开源许可证。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

界面只做三件事，按 ①②③ 的顺序走就行：
  ① 把从浏览器复制到的凭证粘进来（自动识别，不用逐项填）
  ② 搜课程，双击加入抢课清单
  ③ 点开始抢课

仅供个人选课辅助，请遵守《深圳大学本科生选课管理规定》。
"""

from __future__ import annotations

import ctypes
import os
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from tkinter import messagebox, scrolledtext, ttk

import requests

import activation

from szu_grabber import (
    BASE_URL,
    burst_lead_for,
    BURST_INTERVAL,
    BURST_LEAD,
    BURST_WINDOW,
    COMMON_SEARCH_TYPES,
    COURSE_TYPES,
    FATAL_RESULTS,
    SPEED_HINTS,
    SPEED_PRESETS,
    STOPALL_RESULTS,
    CourseGrabber,
    CredentialError,
    classify,
    missing_fields,
    next_delay,
    cookie_pairs,
    parse_credentials,
    parse_start_time,
    plain_result,
    seconds_until_start,
    server_seconds_now,
    status_of,
)

APP_TITLE = "深大抢课助手"
MAINTAINED_URL = "https://github.com/guiyi886/szu_grab_course"
CREDIT_LINE = ("原作 Lewin671/YourLesson（上游）　·　维护 guiyi886/szu_grab_course"
               "　·　本版整合：理不尽")
CONFIG_NAME = "szu_grab_config.json"

# 同一门课连续这么多次都收到「看不懂/异常」的回复，就停下这门课。
# 不然遇到一个坏条目（比如课程已被学校删掉、编号失效）会无限重试下去。
# 注意只对「异常」计数：名额满是要一直蹲的，不能算。
MAX_CONSECUTIVE_ERRORS = 40

# 深圳大学的品牌色，取自学校官网自己的样式表 https://www.szu.edu.cn/css/style.css
# 主色 #930A41（出现 32 次），辅色 #CE9C44（出现 32 次，图标里的金闪电用它）。
# 教程和界面里的红色高亮统一用这个主色，跟图标呼应。
SZU_RED = "#930A41"

TYPE_ORDER = ("TJKC", "FANKC", "XGXK", "TYKC", "FAWKC", "FXKC", "MOOC")
SCOPE_CHOICES = ["常用（推荐）", "全部"] + [COURSE_TYPES[key] for key in TYPE_ORDER]

FONT = ("微软雅黑", 10)
FONT_SMALL = ("微软雅黑", 9)
FONT_BOLD = ("微软雅黑", 10, "bold")
FONT_TITLE = ("微软雅黑", 15, "bold")


def resource_path(name: str) -> str:
    """打包成 exe 之后资源在临时解包目录里，没打包时就在脚本旁边。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def app_dir() -> str:
    """配置写在 exe（或脚本）旁边，卸载时一起删掉就行。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CRASH_NAME = "深大抢课助手_出错记录.txt"


def _looks_like_cmd_curl(text: str) -> bool:
    """这串是不是「Copy as cURL (cmd)」那种格式（行尾用 ^ 续行、或用 curl.exe）。

    用途只是**把提示说得更准**：cmd / powershell 那两种复制格式实测会少掉 Cookie
    那一行，用户自己看不出区别，被点破一句"你这串就是 cmd 格式"最容易懂。
    判定不出来也没关系——反正提示里都会让他改用 bash。
    """
    if not text:
        return False
    if re.search(r"\^\s*$", text, re.M):
        return True
    return bool(re.search(r"\bcurl\.exe\b", text, re.I))


def network_advice(detail: str) -> str:
    """把网络异常的原文翻成"人能照着做"的几句话（原文附在最后，截断）。

    为什么值得单独写一个函数：连不上时 Python 抛出来的是一串
    `HTTPConnectionPool(host=...): Max retries exceeded ... ConnectTimeoutError(<HTTPConnection...>)`，
    对新用户来说这等于什么都没说，只会让人以为"软件坏了"。
    而这件事最常见的原因其实很单一——**选课系统只对校内网/学校 VPN 开放**，
    从校外直连就是会超时。所以直接把这句话和两个排查动作告诉他。
    """
    text = str(detail)
    low = text.lower()
    if "timed out" in low or "timeout" in low:
        head = [
            "连不上选课系统（等回应超时）。这不是软件的问题，多半是网络通道的事：",
            "　· 选课系统必须走学校的 VPN（就是 SecureLink 那个客户端），先把连上；",
            "　· 已经连上 SecureLink 还是不通？在它的资源列表里把「选课系统」打开一次——",
            "　　 客户端要认得这个资源，才会给选课服务器装上走 VPN 的那条路；",
            "　· 连上后刷新一下选课页面确认能打开，再回到这里点「检查凭证」。",
        ]
    elif "refused" in low:
        head = ["选课系统拒绝了连接（它可能正在维护，过一会儿再试）。"]
    elif "getaddrinfo" in low or "name or service not known" in low:
        head = ["选课系统的网址解析不出来（DNS 的问题，检查一下网络设置）。"]
    else:
        head = ["连接选课系统时出错。"]
    head.append("　（技术细节：%s）" % text[:160])
    return "\n".join(head)


def write_crash_log(exc_type, exc_value, exc_tb) -> str:
    """把一次崩溃写成文件，返回文件路径（写不了就返回空串）。

    为什么需要它：打包成 exe 用的是 --windowed，**没有控制台**，Python 的
    报错信息打在 stderr 上等于直接扔掉。别人拿到的如果是个会闪退的 exe，
    除了"它闪了一下"什么线索都给不出来，没法排查也没法反馈。
    落到文件里至少能看一眼、能把文件发过来。
    """
    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        path = os.path.join(app_dir(), CRASH_NAME)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n===== %s =====\n%s" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                                  text))
        return path
    except Exception:
        return ""


def _main_thread_excepthook(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    path = write_crash_log(exc_type, exc_value, exc_tb)
    try:
        messagebox.showerror(
            "程序出错了",
            "出了个没想到的错误，程序可能会不正常。\n\n"
            "%s: %s\n\n%s" % (exc_type.__name__, exc_value,
                              ("错误记录写在：\n" + path) if path
                              else "（错误记录没能写出来）"))
    except Exception:
        pass


def _worker_thread_excepthook(args):
    if issubclass(args.exc_type, KeyboardInterrupt):
        return
    write_crash_log(args.exc_type, args.exc_value, args.exc_traceback)


def enable_dpi_awareness() -> None:
    """声明本程序是「DPI 感知」的——这一步直接决定字清不清楚。

    默认情况下 Windows 认为程序只懂 96dpi：它先把窗口按 96dpi 画好，
    再整体拉伸到实际缩放比例（常见 125% / 150%）。字被放大插值，就发虚。
    声明之后 Windows 不再拉伸，程序按屏幕真实分辨率绘制，字才是锐利的。
    代价是布局尺寸要自己跟着放大——见 App.s()。

    必须在创建 Tk 窗口之前调用，否则不生效。
    """
    if not sys.platform.startswith("win"):
        return
    try:
        # 1 = PROCESS_SYSTEM_DPI_AWARE，兼容性最好（Win8.1+）
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()   # Win7 的老接口
    except Exception:
        pass


# ==========================================================================
# 使用说明的全部内容
#
# 界面上的「使用说明」按钮和导出的 使用说明.txt 都从这一个地方生成。
# 之前「怎么拿凭证」分了两份写（说明书里一份纯文字、图文窗口里一份图解），
# 说法容易走岔，现在只有一份。
#
# 每一项是 (小标题, 正文, 配图)。配图填 None 就是纯文字段落，
# 填名字就去调 Sketch 里同名的画法。
# ==========================================================================

GUIDE_SECTIONS = (
    ("三步：粘贴凭证 → 搜课 → 开抢",
     "第一次用，照着下面六步走就行。前面四步只是为了拿到「凭证」，\n"
     "你实际只做三件事：点两下标签、右键复制、回来粘一下。\n"
     "不用打字、不用手抄、不用改任何东西。\n"
     "\n"
     "（图里画的是要点，不是浏览器截图。浏览器是中文版的话，\n"
     "「Network」会显示成「网络」，位置一样。）",
     None),
    ("第 1 步　登录，打开开发者工具",
     "用 Chrome 或 Edge 打开 http://bkxk.szu.edu.cn\n"
     "它自己就是登录页，用学号 + 密码 + 验证码登进去。\n"
     "因为有验证码，这一步必须你自己登，程序替不了你。\n"
     "\n"
     "登进去之后打开开发者工具，两种办法都行：\n"
     "　　· 按 F12（有的笔记本要按 Fn + F12）\n"
     "　　· 或者在页面上点右键 →「检查」\n"
     "\n"
     "面板会出现在浏览器右侧或下方，点一下「网络」（Network）那个标签。\n"
     "（要是打开后停在「元素」面板，就得手动切到「网络」。）",
     "step1_f12"),
    ("第 2 步　点两下标签，让那一行出现",
     "在选课页面上点一下「方案内课程」，再点一下「本班课程」。\n"
     "\n"
     "你每点一下，页面就在发请求，「网络」面板的列表里会实时多出一行：\n"
     "　　点「方案内课程」→ 多出一行 programCourse.do\n"
     "　　点「本班课程」　→ 多出一行 recommendedCourse.do\n"
     "\n"
     "★ 要找的就是 recommendedCourse.do 这一行——它自己会冒出来，\n"
     "　不需要在过滤框里搜任何东西，那个框你一个字都不用填。\n"
     "\n"
     "列表里东西太多？点一下「Fetch/XHR」，就只剩接口请求了。\n"
     "要是列表一直是空的：确认地址栏是 bkxk.szu.edu.cn 开头，\n"
     "并且你真的已经登进去了（不是停在登录页）。",
     "step2_tabs"),
    ("第 3 步　右键那一行，复制成 cURL（必须选 bash 那个）",
     "在 recommendedCourse.do 那一行上点右键（是右键，不是左键）：\n"
     "　　弹出的菜单里选 Copy → Copy as cURL → 再点 bash 那一个。\n"
     "\n"
     "★ 这三个子选项里只能选 bash（在 Chrome 里通常写作「Copy as cURL (bash)」）。\n"
     "　 cmd 和 powershell 那两种复制出来的内容会不全（实测会少掉 Cookie 那一行），\n"
     "　 粘进来就会显示「还缺 Cookie」。选错了不要紧：重新复制一次、这次选 bash 就好。\n"
     "\n"
     "找不到 recommendedCourse.do 这一行的话，右键 programCourse.do 也一样能用。\n"
     "复制到的是一长串浏览器自己拼出来的命令，你一个字都不用敲、也不用看懂。",
     "step3_menu"),
    ("第 4 步　回到本软件，整段粘进来",
     "把刚才复制到的那一整段，粘到「① 粘贴凭证」下面的框里：\n"
     "　　按 Ctrl+V，或者点「从剪贴板读取」按钮。\n"
     "\n"
     "不用挑、不用删、不用改，连命令带参数整段粘进来就行。\n"
     "粘好之后框下面会自动显示四个 ✅，看到「✅ 检查通过，可以开始抢课了」\n"
     "就可以往下走了。\n"
     "\n"
     "★ 每次重新登录选课系统，Cookie 都会变，这四步就得重做一遍。\n"
     "　 抢课那天提前 10 分钟做一次。",
     "step4_paste"),
    ("第 5 步　搜课、双击加进清单",
     "在「② 找课」的搜索框里输入课程名或老师名的一部分（两三个字就够，\n"
     "比如「篮球」「心理学」），点「搜索课程」。\n"
     "搜出来之后，在想要的那一行上双击，它就进了「③ 抢课清单」。\n"
     "\n"
     "「范围」默认搜最常见的四类（体育、校公选、本班、方案内）；\n"
     "想搜辅修或慕课，把范围改成「全部」。\n"
     "结果表里「状态」一栏：有名额 / 已选 / 时间冲突 / 名额已满。",
     None),
    ("第 6 步　点开始抢课",
     "点「▶ 开始抢课」，剩下的交给它：抢到一门就从清单里划掉，\n"
     "全部抢到会自动停下并弹窗。\n"
     "\n"
     "速度有三档，从上到下由慢到快，默认「慢」：\n"
     "　　慢　每 0.5~0.9 秒提交一次　　推荐。最不容易被系统盯上\n"
     "　　中　每 0.35~0.6 秒提交一次　　比「慢」快一些\n"
     "　　快　每 0.2~0.4 秒提交一次　　更快，但更可能被提示「操作过于频繁」\n"
     "\n"
     "平时用「慢」就够了，不用调激进——名额是统一时间点放的那种，\n"
     "勾上「等到开抢时刻自动开抢」比调速度有用得多，见下面第 3 节。",
     None),
    ("——— 补充说明（第一次用可以先不看）———",
     "上面六步做完就能抢课了。下面是抢课当天可能用得上的几件事。",
     None),
    ("1. 名额是统一时间点放的？勾上「等到开抢时刻自动开抢」",
     "很多轮次是「一个时间点统一放名额」，这时候比的是谁的第一个请求最先到达，\n"
     "把速度档调小反而不如把起跑时机对准。勾上之后会有三个小框：\n"
     "　　下午三点 → 时填 15、分填 00、秒填 00\n"
     "　　上午九点半 → 时填 09、分填 30、秒留空\n"
     "\n"
     "三个框后面分别写着单位：时、分、秒，直接填数字就行；冒号是画好的，\n"
     "填满两位会自动跳到下一格，「秒」留空按 00 算，填错了下面会告诉你哪里不对。\n"
     "★ 用 24 小时制！下午三点是 15，不是 3（那是凌晨三点）。\n"
     "\n"
     "然后程序会：\n"
     "　　1. 先跟服务器对一次时（名额是按服务器的钟放的，\n"
     "　　　 你电脑的钟快几秒慢几秒都会让你错过）；\n"
     "　　2. 待机到开抢前 2 秒，开始以每 0.1~0.18 秒一次的高频提交冲刺；\n"
     "　　3. 冲满「提前量 + 15 秒」就收手（网络正常时就是提前的 2 秒加上开抢\n"
     "　　　 之后的 15 秒，共约 17 秒），然后自动降回上面选的速度继续蹲；\n"
     "　　4. 冲刺期间一旦被提示「操作过于频繁」，立刻退出高频改用慢速。\n"
     "\n"
     "★ 那个「2 秒」是最小值，程序会自己调：它先量一次到服务器要多久，\n"
     "　 网慢就提前更多（最多 8 秒），让第一个请求正好在开抢那一刻到达。\n"
     "\n"
     "开始之后日志里会写出「服务器现在是几点、你填的是几点」，\n"
     "★ 请看一眼这两个时刻对不对——本想设下午三点却填成 3 的话，\n"
     "　程序会提醒你「目标落在凌晨 3:00」。等待期间每半小时会自动重新对一次时。\n"
     "\n"
     "★ 点「开始抢课」之后就不能再搜课、改清单了（想改先点停止），\n"
     "　 所以开抢前先把要抢的课都加好。",
     None),
    ("2. 抢课当天的准备清单",
     "照着过一遍，能把大部分「白等一场」挡在门外：\n"
     "　　1. 提前 10 分钟重取一次凭证，点「检查凭证」，确认看到\n"
     "　　　 「凭证有效」和「批次码可用（能看到 N 门课）」。\n"
     "　　2. 搜课、把要抢的课加进清单。\n"
     "　　3. 勾上「等到开抢时刻自动开抢」，填准开抢时间。\n"
     "　　4. 速度档保持「慢」就行——开抢那几秒的冲刺是自动的。\n"
     "　　5. ★ 把电源设置里的「睡眠」改成「从不」（控制面板 → 电源选项）。\n"
     "　　6. 点「开始抢课」，让它待机；界面会显示还剩多少时间。\n"
     "　　7. 浏览器也开着选课页面当备胎，万一这边出问题你还能手点。\n"
     "\n"
     "★ 为什么第 5 条最关键：电脑一旦睡着，进程会被冻结，\n"
     "　 到点既不会发请求、也不会叫醒你，正好错过那一瞬间。\n"
     "\n"
     "两个容易白等的坑：\n"
     "　· 会话会过期：别提前太久挂上（挂一夜可能 Cookie 就失效了）。\n"
     "　· 批次码可能随轮次变：如果开抢那一刻选课批次也换了，你粘的批次码就过期。\n"
     "　　 所以抢课前务必用「检查凭证」确认它是当前这一轮的。",
     None),
    ("3. 它会怎么抢、以及抢不到时你会看到什么",
     "正常速度下：\n"
     "　· 按你选的速度反复提交，抢到一门就从清单里划掉\n"
     "　· 遇到「名额满了」会继续蹲着，有人退课就能被你捡到\n"
     "　· 遇到「操作过于频繁」会自动放慢，不会越撞越猛\n"
     "　· 遇到「时间冲突 / 学分已满 / 没权限」会停下这门课并说明原因\n"
     "　· 遇到「凭证失效 / 批次码不对」会整轮停下，让你重新贴凭证\n"
     "　· 网络断了、或者选课系统自己报错，会一直重试，不会把账算到这门课上\n"
     "　· 同一门课连续几十次都收到看不懂的回复（比如这门课已被学校删掉、编号失效），\n"
     "　　 会停下这门课，状态栏写「连续异常，已停下」，不会对着它一直死磕\n"
     "　· 一轮结束时会顺手查一次「已选课程」跟清单核对，\n"
     "　　 万一系统用别的说法回了个「其实选上了」，也会被认出来\n"
     "\n"
     "结束时按结果分三种口径，不会含糊：全部抢到（响铃 + 祝贺）、\n"
     "抢到一部分（如实报数字并点名没抢到的）、一门没抢到（弹警告）。",
     None),
    ("4. 常见问题",
     "Q：提示「连不上选课系统（超时）」？\n"
     "A：选课系统在校内网里，从校外直连是进不去的。两步：\n"
     "　 ① 先连学校的 VPN（SecureLink），并在它的资源列表里把「选课系统」打开一次\n"
     "　　 （客户端认得这个资源，才会给选课服务器装上网关）；\n"
     "　 ② 连上后刷新一下选课页面，确认浏览器能打开，再回来点「检查凭证」。\n"
     "　 要是 SecureLink 里找不到「选课系统」这一项，可以再试试学校的 WebVPN\n"
     "　 （浏览器访问 webvpn.szu.edu.cn，在里面打开选课系统）——本程序会自动跟着\n"
     "　 你复制的那条网址走，不需要改任何设置。\n\n"
     "Q：提示「登录已失效」？\n"
     "A：Cookie 过期了。把第 1~4 步重做一遍，再粘一次。\n\n"
     "Q：提示「拉不到任何课程 / 批次码可能不对」？\n"
     "A：选课的批次（轮次）换了，或者现在不在选课时间。重新复制一次 cURL 粘进来。\n\n"
     "Q：搜不到我想上的课？\n"
     "A：换成更短的词（只留两个字），或者把「范围」改成「全部」。\n\n"
     "Q：一直显示「名额满了」，是不是白挂着？\n"
     "A：不是（前提是那一轮先到先得）。有人退课就会立刻空出名额，脚本就是在等这一下。\n\n"
     "Q：能不能同时开好几个？\n"
     "A：不建议。同一个账号并发请求很容易被风控，反而拖慢自己。\n\n"
     "Q：程序弹了个「程序出错了」，或者窗口突然没了？\n"
     "A：程序旁边会生成一个「深大抢课助手_出错记录.txt」，里面写着出错的位置。\n"
     "　 把它发给我就能查原因；删掉它不影响使用。\n\n"
     "Q：我的凭证会被存下来吗？\n"
     "A：会。程序旁边有个 szu_grab_config.json，里面存着你粘的那段内容（含 Cookie）、\n"
     "　 抢课清单和速度设置，这样下次打开不用重贴。它是「明文」文件——\n"
     "　 别把这个文件夹连同它一起发给别人。想抹掉：点「清空」再关掉程序，\n"
     "　 或者直接把那个文件删掉。",
     None),
    ("5. 它保证什么、不保证什么",
     "保证——到点那一刻你的请求已经在路上，不会因为手慢、看错表而错过。\n"
     "不保证——先到的请求一定拿到名额。\n"
     "\n"
     "· 如果那一轮是「抽签」（看运气、不看先后），速度再快也没用，\n"
     "　 只有「先到先得」那种轮次才用得上它。哪一轮是哪种，以学校当轮的通知为准。\n"
     "· 对时精度只到秒级：HTTP 的时间头只给到整秒，所以你的起跑有可能比\n"
     "　 正确的那一瞬间晚半秒。这是这套做法的天花板，改不了。\n"
     "· 提交是「发一个、等回应、再发下一个」。开抢那一刻如果服务器被挤到\n"
     "　 每次响应要 1 秒，提交频率会跟着掉下来——这是这种做法的固有代价。\n"
     "· 别一天到晚挂着不关，用完就收。请遵守《深圳大学本科生选课管理规定》，\n"
     "　 不要干扰选课系统的正常秩序。",
     None),
    ("署名与来源",
     "这个工具是站在别人肩膀上做的，把谁做了什么写清楚：\n\n"
     "【上游原作】Lewin671（昵称 qingyingliu）「深圳大学抢课系统」\n"
     "　　https://github.com/Lewin671/YourLesson\n"
     "　　最早的脚本，2019 年就在了。\n\n"
     "【本版所依据的维护版】guiyi886（显示名 guyi_ac）\n"
     "　　https://github.com/guiyi886/szu_grab_course\n"
     "　　本说明前四步的做法（F12 → 网络 → 点两下标签 → 找 recommendedCourse.do）\n"
     "　　就是照这个仓库的说明写的，它的 README 写明「复刻于 Lewin671/YourLesson\n"
     "　　后进行维护和更新」。抢课的接口用法、四个凭证字段从哪来，都出自这里。\n"
     "　　该仓库的其他提交者：qingyingliu、Red_Hairy_Mouse\n\n"
     "【本版】理不尽 —— 重新实现协议层、重新设计界面、打包成 exe。\n"
     "　　★ 本版的作者不是上面任何一位原作者。★\n\n"
     "上面两个仓库都没有标注开源许可证，这里只做署名与来源说明。\n\n"
     "本版代码与界面为独立重写（没有把上游代码复制过来改），\n"
     "版权归本版作者：© 2026 理不尽。",
     None),
)


# 每张示意图画布的高度（设计尺寸，宽度统一 620）
DIAGRAM_HEIGHT = {"step1_f12": 176, "step2_tabs": 184,
                  "step3_menu": 168, "step4_paste": 168}


def help_text():
    """把上面的内容导出成纯文本（不带图），给 使用说明.txt 用。"""
    out = ["深大抢课助手 · 使用说明",
           "（在软件里点「使用说明 · 图文」按钮，能看到「怎么拿凭证」的分步示意图）", ""]
    for title, body, _diagram in GUIDE_SECTIONS:
        out.append("━━━━━ %s ━━━━━" % title.strip())
        out.append(body)
        out.append("")
    return "\n".join(out)


HELP_TEXT = help_text()


def _fmt_clock(seconds_of_day) -> str:
    """把「当天第几秒」格式化成 24 小时制的 HH:MM:SS。"""
    total = int(seconds_of_day) % 86400
    return "%02d:%02d:%02d" % (total // 3600, total % 3600 // 60, total % 60)


class Sketch:
    """示意图画笔。

    坐标一律按「设计稿」给（就是下面那些小数字），内部乘屏幕缩放系数。
    这样在高分屏上画出来的线和字都是原生的锐利像素，不是拉伸出来的糊图。
    用画的而不是贴截图，一是随手能改，二是不用带图片资源。
    """

    def __init__(self, canvas, factor):
        self.c = canvas
        self.k = factor

    def _p(self, value):
        return value * self.k

    def box(self, x, y, w, h, fill="", outline="#C4C4C4", width=1):
        self.c.create_rectangle(self._p(x), self._p(y), self._p(x + w), self._p(y + h),
                                fill=fill, outline=outline, width=width)

    def bar(self, x, y, w, h, fill="#E4E4E4"):
        """一条灰杠，用来示意「这里有一行文字」。"""
        self.box(x, y, w, h, fill=fill, outline=fill)

    def label(self, x, y, text, size=8, fill="#333333", anchor="nw", bold=False):
        self.c.create_text(self._p(x), self._p(y), text=text, anchor=anchor, fill=fill,
                           font=("微软雅黑", size, "bold") if bold else ("微软雅黑", size))

    def line(self, x1, y1, x2, y2, fill="#C4C4C4", width=1, dash=None):
        self.c.create_line(self._p(x1), self._p(y1), self._p(x2), self._p(y2),
                           fill=fill, width=width, dash=dash)

    def dot(self, x, y, r=3, fill="#C8C8C8"):
        self.c.create_oval(self._p(x - r), self._p(y - r), self._p(x + r), self._p(y + r),
                           fill=fill, outline=fill)

    def key(self, x, y, text, w=30, h=24):
        """画一个键帽，比如 F12 / F5。"""
        self.box(x, y, w, h, fill="#FFFFFF", outline="#AFAFAF")
        self.label(x + w / 2, y + h / 2, text, 8, "#333333", anchor="center", bold=True)

    def arrow(self, x1, y1, x2, y2, fill=SZU_RED):
        self.c.create_line(self._p(x1), self._p(y1), self._p(x2), self._p(y2),
                           fill=fill, width=2, arrow="last", arrowshape=(9, 11, 4))

    # ---------------- 四张示意图 ----------------

    def step1_f12(self):
        """浏览器 + 右侧开发者工具面板，Network 标签高亮。"""
        self.box(10, 8, 580, 118, fill="#FFFFFF", outline="#B8B8B8")
        self.box(10, 8, 580, 20, fill="#EFEFEF", outline="#B8B8B8")
        for i in range(3):
            self.dot(24 + i * 14, 18, 3.2, "#CFCFCF")
        self.box(78, 32, 512, 16, fill="#F8F8F8", outline="#DCDCDC")
        self.label(88, 40, "bkxk.szu.edu.cn   （选课系统，自己就是登录页）", 7, "#666666", anchor="w")

        # 左：选课页面
        self.box(16, 56, 300, 64, fill="#FBFBFB", outline="#E4E4E4")
        for i in range(3):
            self.bar(28, 68 + i * 16, 276 - i * 44, 7)

        # 右：开发者工具
        self.box(328, 56, 256, 64, fill="#FFFFFF", outline="#B8B8B8")
        self.box(328, 56, 256, 18, fill="#ECECEC", outline="#B8B8B8")
        self.label(334, 65, "Elements", 7, "#8A8A8A", anchor="w")
        self.label(402, 65, "Console", 7, "#8A8A8A", anchor="w")
        self.box(462, 58, 112, 14, fill=SZU_RED, outline=SZU_RED)
        self.label(518, 65, "Network / 网络", 7, "#FFFFFF", anchor="center", bold=True)
        # 标签行最右边的折叠符号：面板窄的时候，多余的标签就收在这里
        self.label(583, 64, "+", 9, "#666666", anchor="e")
        for i in range(2):
            self.bar(338, 84 + i * 16, 236, 7, "#EDEDED")

        # 说明
        self.key(20, 138, "F12", 34, 26)
        self.label(64, 148, "按 F12 打开右边这块面板", 8, "#333333", anchor="w")
        self.arrow(408, 134, 512, 80)
        self.label(300, 139, "点这个标签", 8, SZU_RED, anchor="nw", bold=True)

    def step2_tabs(self):
        """在选课页面上点两下标签，网络面板里就会自己多出那一行。

        这张图以前是画错的：它把「recommendedCourse」写在了过滤框里，
        等于在教用户"去过滤框里搜这个词"——而正确的做法是**一个字都不用填**，
        那一行是点标签之后自己冒出来的。用户就是被这张图带偏的，所以重画成
        「左边点两下标签 → 右边列表里多出一行」。
        """
        # 左：选课页面上的两个标签
        self.box(10, 8, 214, 168, fill="#FBFBFB", outline="#C8C8C8")
        self.label(20, 18, "选课页面", 7, "#8A8A8A", anchor="w")
        self.box(20, 36, 194, 22, fill="#F2F2F2", outline="#D8D8D8")
        self.label(32, 47, "方案内课程", 8, "#444444", anchor="w")
        self.box(20, 66, 194, 22, fill=SZU_RED, outline=SZU_RED)
        self.label(32, 77, "本班课程", 8, "#FFFFFF", anchor="w", bold=True)
        self.label(20, 100, "① 点一下「方案内课程」\n② 再点一下「本班课程」", 8,
                   "#333333", anchor="nw")
        self.label(20, 158, "（这两下点完就够了）", 7, "#A0A0A0", anchor="w")

        # 右：网络面板里冒出来的两行
        self.box(236, 8, 374, 168, fill="#FFFFFF", outline="#B8B8B8")
        self.box(236, 8, 374, 20, fill="#ECECEC", outline="#B8B8B8")
        self.box(546, 10, 56, 14, fill=SZU_RED, outline=SZU_RED)
        self.label(574, 17, "网络", 7, "#FFFFFF", anchor="center", bold=True)
        # 工具栏：类型筛选按钮 + 一个空着的过滤框（明确写"不用填"）
        self.box(246, 34, 62, 16, fill=SZU_RED, outline=SZU_RED)
        self.label(277, 42, "Fetch/XHR", 7, "#FFFFFF", anchor="center", bold=True)
        self.box(316, 34, 150, 16, fill="#F6F6F6", outline="#C8C8C8")
        self.label(324, 42, "⌕ 过滤框（不用填）", 7, "#A0A0A0", anchor="w")

        # 请求列表：灰的两行 + 高亮的那一行
        self.line(246, 58, 600, 58, "#E0E0E0")
        self.bar(254, 66, 150, 8, "#EDEDED")
        self.bar(254, 82, 120, 8, "#EDEDED")
        self.box(246, 98, 354, 22, fill="#FBE9EF", outline=SZU_RED)
        self.label(256, 109, "programCourse.do", 8, "#8A6A75", anchor="w")
        self.box(246, 124, 354, 24, fill="#FBE9EF", outline=SZU_RED)
        self.label(256, 136, "recommendedCourse.do", 8, SZU_RED, anchor="w", bold=True)
        self.label(470, 136, "← 右键点它", 8, SZU_RED, anchor="w", bold=True)
        self.label(246, 156, "★ 这一行是自己冒出来的，不用在过滤框里搜", 7,
                   SZU_RED, anchor="w", bold=True)

    def step3_menu(self):
        """右键 → Copy → Copy as cURL → **bash**（只有这个格式是全的）。

        这张图原来在右下角写着「bash / cmd / powershell 都行」——用户实测**不行**：
        cmd 那两种复制出来的内容会少掉 Cookie 那一行，粘进软件就是「还缺 Cookie」。
        所以现在把三个子选项都画出来，bash 高亮、另外两个标上「会缺 Cookie」。
        """
        # 左边：被右键的那一行
        self.box(10, 30, 220, 24, fill="#FBE9EF", outline=SZU_RED)
        self.label(22, 42, "recommendedCourse.do", 8, SZU_RED, anchor="w", bold=True)

        # 右键菜单
        self.box(238, 22, 168, 96, fill="#FFFFFF", outline="#B0B0B0")
        self.label(250, 34, "Open in new tab", 8, "#444444", anchor="w")
        self.box(238, 48, 168, 22, fill="#F0F0F0", outline="#F0F0F0")
        self.label(250, 59, "Copy", 8, "#111111", anchor="w", bold=True)
        self.label(392, 59, "▸", 9, "#111111", anchor="e")
        self.label(250, 84, "Save as…", 8, "#444444", anchor="w")
        self.label(250, 104, "Inspect", 8, "#444444", anchor="w")

        # 子菜单：bash 高亮，另两个划掉
        self.box(406, 48, 204, 74, fill="#FFFFFF", outline="#B0B0B0")
        self.box(406, 52, 204, 22, fill=SZU_RED, outline=SZU_RED)
        self.label(416, 63, "Copy as cURL (bash)", 8, "#FFFFFF", anchor="w", bold=True)
        self.label(416, 82, "Copy as cURL (cmd)", 8, "#AAAAAA", anchor="w")
        self.label(416, 100, "(powershell)", 8, "#AAAAAA", anchor="w")
        self.label(586, 82, "✗", 9, "#B03030", anchor="e")
        self.label(586, 100, "✗", 9, "#B03030", anchor="e")

        self.label(14, 66, "先点 Copy，\n再选 Copy as cURL", 8, "#333333", anchor="nw")
        self.label(14, 108, "★ 只有 bash 那个是全的", 8, SZU_RED, anchor="nw", bold=True)
        self.label(14, 126, "cmd / powershell 会少掉 Cookie，", 7, "#8A8A8A", anchor="nw")
        self.label(14, 140, "粘进去就是「还缺 Cookie」", 7, "#8A8A8A", anchor="nw")

    def step4_paste(self):
        """粘回本软件，四个值自动认出来。"""
        self.box(10, 8, 600, 92, fill="#FFFFFF", outline="#C8C8C8")
        self.label(20, 20, "curl 'http://bkxk.szu.edu.cn/xsxkapp/…/recommendedCourse.do' \\", 7, "#555555", anchor="w")
        self.label(20, 36, "  -H 'cookie: _WEU=…; JSESSIONID=…' \\", 7, "#555555", anchor="w")
        self.label(20, 52, "  -H 'token: 6e912f8e-…' \\", 7, "#555555", anchor="w")
        self.label(20, 68, "  --data-raw 'querySetting=%7B%22studentCode%22…'", 7, "#555555", anchor="w")
        self.label(20, 86, "（整段都粘进来，不用挑）", 7, "#A0A0A0", anchor="w")

        self.label(10, 112, "粘好之后这里会显示四个 ✅：", 8, "#333333", anchor="nw")
        for i, name in enumerate(("学号", "Cookie", "token", "批次码")):
            x = 10 + i * 152
            self.box(x, 130, 142, 24, fill="#F2F7F2", outline="#BFD8BF")
            self.label(x + 16, 142, "✅ " + name, 8, "#2A6E2A", anchor="w")




class App(tk.Tk):
    # 运行日志最多留这么多行。抢课要挂几个小时，不设上限会越拖越慢。
    LOG_MAX_LINES = 800

    def __init__(self):
        super().__init__()

        # 屏幕缩放系数（100% 时是 1.0，150% 时是 1.5）。
        # 字体是按「点」给的，Tk 会自己按缩放画；但下面那些写死的像素值
        # （窗口尺寸、列宽、间距）不会自己变大，所以统一用 s() 换算一遍。
        self.dpi = self.winfo_fpixels("1i")
        self.scale = max(1.0, self.dpi / 96.0)
        self.tk.call("tk", "scaling", self.dpi / 72.0)

        self.title(APP_TITLE)
        self._apply_window_size()

        self.msg_q = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker = None

        self.grabber = None
        self.creds = {}
        self.checked_signature = None
        self.results = {}          # 结果表 iid → 课程行
        self.all_rows = []         # 本次搜索的全部结果
        self.grab_items = {}       # 清单 iid → {id,name,teacher,type,status}
        self.attempt_counts = {}   # 清单 iid → 已尝试次数（用来给日志节流）
        self.help_win = None
        self._auto_parse_job = None   # 「粘贴后自动识别」那个延时任务的句柄

        self.cfg = self._load_config()
        self._build_ui()
        self._restore_config()
        self.after(120, self._poll_queue)

        self._set_window_icon()
        self.log("欢迎使用。第一步：按 F12 → Network → 右键 recommendedCourse.do "
                 "→ Copy as cURL → 粘到左边。")
        self.log(CREDIT_LINE)

    # ==================== 界面 ====================

    def s(self, value):
        """把设计尺寸换算成当前屏幕缩放下该用的像素值。"""
        return int(round(value * self.scale))

    def _apply_window_size(self):
        """按缩放定窗口大小，并保证不会超出屏幕。"""
        width, height = self.s(1240), self.s(900)
        # 只在屏幕尺寸看起来可信时才用它收口。万一读到异常的小值，
        # 下面这些 min() 会算出负数，窗口就会变成一个空壳（只剩标题栏）。
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        if screen_w > self.s(500):
            width = min(width, screen_w - self.s(40))
        if screen_h > self.s(400):
            height = min(height, screen_h - self.s(80))
        width = max(width, self.s(860))
        height = max(height, self.s(560))
        self.geometry("%dx%d" % (width, height))
        self.minsize(min(self.s(1100), width), min(self.s(720), height))

    def _build_ui(self):
        self.columnconfigure(0, weight=0, minsize=self.s(440))
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=6)
        self.rowconfigure(2, weight=1)

        # 表格行高不跟着字走，得自己设，否则放大后字会顶到行线上
        ttk.Style(self).configure("Treeview", rowheight=self.s(23))

        self._build_header()
        self._build_left()
        self._build_right()
        self._build_log()

    def _build_header(self):
        bar = ttk.Frame(self, padding=(self.s(16), self.s(12), self.s(16), self.s(6)))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text=APP_TITLE, font=FONT_TITLE).grid(row=0, column=0, sticky="w")
        ttk.Label(bar, text="粘贴一次凭证 → 搜课 → 开抢", foreground="#777777",
                  font=FONT_SMALL).grid(row=1, column=0, sticky="w", pady=(self.s(2), 0))

        # 署名放在最显眼处，点一下能打开来源仓库
        credit = ttk.Label(bar, text=CREDIT_LINE, foreground="#777777",
                           font=FONT_SMALL, cursor="hand2")
        credit.grid(row=0, column=1, rowspan=2, sticky="e")
        credit.bind("<Button-1>", lambda event: webbrowser.open(MAINTAINED_URL))

        ttk.Button(bar, text="使用说明 · 图文", command=self.show_help).grid(
            row=0, column=2, rowspan=2, sticky="e", padx=(self.s(14), 0))

    def _build_left(self):
        left = ttk.Frame(self, padding=(self.s(16), self.s(4), self.s(8), self.s(12)))
        left.grid(row=1, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        # ---- ① 凭证 ----
        box = ttk.LabelFrame(left, text=" ① 粘贴凭证 ", padding=self.s(10))
        box.grid(row=0, column=0, sticky="ew")
        box.columnconfigure(0, weight=1)

        ttk.Label(box, foreground="#555555", font=FONT_SMALL, justify="left",
                  text="在浏览器里右键 recommendedCourse.do → Copy → Copy as cURL，\n"
                       "把复制到的内容整个粘在下面，四个值软件自己认。\n"
                       "第一次用不知道从哪下手？点右上角「使用说明」，有分步示意图。").grid(
            row=0, column=0, sticky="w", pady=(0, self.s(6)))

        holder = ttk.Frame(box)
        holder.grid(row=1, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        # width=1 是故意的：Text 默认按 80 字符索要宽度，会把左栏撑肥，
        # 挤掉右边结果表的「名额 / 状态」两列。设成 1 之后由 grid 拉伸决定宽度。
        self.txt_creds = tk.Text(holder, height=6, width=1, wrap="char",
                                 font=("Consolas", 9), relief="solid",
                                 borderwidth=1, undo=True)
        self.txt_creds.grid(row=0, column=0, sticky="ew")
        bar = ttk.Scrollbar(holder, orient="vertical", command=self.txt_creds.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.txt_creds.configure(yscrollcommand=bar.set)
        self.txt_creds.bind("<<Modified>>", self._on_creds_modified)

        row = ttk.Frame(box)
        row.grid(row=2, column=0, sticky="ew", pady=(self.s(6), 0))
        ttk.Button(row, text="从剪贴板读取", command=self._paste_from_clipboard).pack(side="left")
        ttk.Button(row, text="清空", command=self._clear_creds).pack(
            side="left", padx=(self.s(6), 0))
        ttk.Button(row, text="检查凭证", command=self._check_creds).pack(
            side="left", padx=(self.s(6), 0))

        self.var_creds = tk.StringVar(value="还没有粘贴内容")
        ttk.Label(box, textvariable=self.var_creds, justify="left",
                  foreground="#555555", font=FONT_SMALL).grid(
            row=3, column=0, sticky="w", pady=(self.s(6), 0))

        # 检查结果单独一行，和上面的识别结果分开：重复点「检查凭证」也不会越叠越长
        self.var_check = tk.StringVar(value="")
        ttk.Label(box, textvariable=self.var_check, justify="left",
                  foreground="#2A6E2A", font=FONT_SMALL).grid(
            row=4, column=0, sticky="w", pady=(self.s(2), 0))

        # ---- ② 抢课清单 ----
        box2 = ttk.LabelFrame(left, text=" ③ 抢课清单与开抢 ", padding=self.s(10))
        box2.grid(row=1, column=0, sticky="nsew", pady=(self.s(12), 0))
        box2.columnconfigure(0, weight=1)
        # minsize 是必须的：左栏竖直空间紧张时，表格是唯一可压缩的控件，
        # 不给下限就会被新加的行挤到看不见。
        box2.rowconfigure(0, weight=1, minsize=self.s(84))

        cols = ("name", "teacher", "status")
        self.tree_grab = ttk.Treeview(box2, columns=cols, show="headings", height=6)
        for key, title, width in (("name", "课程", 175), ("teacher", "老师", 80),
                                  ("status", "状态", 110)):
            self.tree_grab.heading(key, text=title)
            self.tree_grab.column(key, width=self.s(width), anchor="w")
        self.tree_grab.grid(row=0, column=0, sticky="nsew")
        grab_bar = ttk.Scrollbar(box2, orient="vertical", command=self.tree_grab.yview)
        grab_bar.grid(row=0, column=1, sticky="ns")
        grab_hbar = ttk.Scrollbar(box2, orient="horizontal", command=self.tree_grab.xview)
        grab_hbar.grid(row=1, column=0, sticky="ew")
        self.tree_grab.configure(yscrollcommand=grab_bar.set, xscrollcommand=grab_hbar.set)

        row2 = ttk.Frame(box2)
        row2.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(self.s(6), 0))
        ttk.Button(row2, text="移除选中", command=self._remove_grab_item).pack(side="left")
        ttk.Button(row2, text="清空清单", command=self._clear_grab_list).pack(
            side="left", padx=(self.s(6), 0))

        row3 = ttk.Frame(box2)
        row3.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(self.s(10), 0))
        ttk.Label(row3, text="抢课速度").pack(anchor="w")
        # 用单选按钮而不是下拉框：三档一次全看得见，不用点开才知道有什么，
        # 而且名字里直接写着「每多少秒提交一次」，谁快谁慢一目了然。
        self.var_speed = tk.IntVar(value=0)
        for index, (name, _, _) in enumerate(SPEED_PRESETS):
            ttk.Radiobutton(row3, text=name, value=index, variable=self.var_speed,
                            command=self._on_speed_change).pack(anchor="w")

        self.var_speed_hint = tk.StringVar()
        ttk.Label(box2, textvariable=self.var_speed_hint, foreground="#555555",
                  font=FONT_SMALL, wraplength=self.s(370), justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(self.s(4), 0))

        # ---- 开抢时刻：名额是统一时间点释放的，这一栏就是为那一刻准备的 ----
        # 勾选框单独一行、时间框另一行：三个框后面要标「时 / 分 / 秒」，
        # 挤在同一行会超出左栏宽度（左栏就这么宽，超了会把别的控件顶出去）。
        row_burst = ttk.Frame(box2)
        row_burst.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(self.s(10), 0))
        self.var_burst = tk.BooleanVar(value=False)
        ttk.Checkbutton(row_burst, text="等到开抢时刻自动开抢", variable=self.var_burst,
                        command=self._on_burst_toggle).pack(side="left")

        row_time = ttk.Frame(box2)
        row_time.grid(row=6, column=0, columnspan=2, sticky="w",
                      pady=(self.s(4), 0), padx=(self.s(18), 0))
        # 时 / 分 / 秒 三个小框，单位跟在各自框后面（_time_box 里画），
        # 冒号也是画好的，用户只管填数字。
        self.entry_burst_h = self._time_box(row_time, "时")
        ttk.Label(row_time, text=":", font=FONT).pack(side="left")
        self.entry_burst_m = self._time_box(row_time, "分")
        ttk.Label(row_time, text=":", font=FONT).pack(side="left")
        self.entry_burst_s = self._time_box(row_time, "秒")
        ttk.Label(row_time, text="24 小时制", font=FONT_SMALL,
                  foreground="#555555").pack(side="left", padx=(self.s(10), 0))

        self.var_burst_hint = tk.StringVar()
        ttk.Label(box2, textvariable=self.var_burst_hint, foreground="#555555",
                  font=FONT_SMALL, wraplength=self.s(370), justify="left").grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(self.s(2), 0))

        row4 = ttk.Frame(box2)
        row4.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(self.s(10), 0))
        self.btn_start = ttk.Button(row4, text="▶  开始抢课", command=self.start_grab)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(row4, text="停止", command=self.stop_grab, state="disabled")
        self.btn_stop.pack(side="left", padx=(self.s(8), 0))

        self.var_progress = tk.StringVar(value="清单是空的：先在右边搜课，双击一行加入")
        ttk.Label(box2, textvariable=self.var_progress, foreground="#555555",
                  font=FONT_SMALL, wraplength=self.s(370), justify="left").grid(
            row=9, column=0, columnspan=2, sticky="w", pady=(self.s(6), 0))

    def _build_right(self):
        right = ttk.Frame(self, padding=(self.s(8), self.s(4), self.s(16), self.s(12)))
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        box = ttk.LabelFrame(right, text=" ② 找课（双击一行加入抢课清单） ",
                             padding=self.s(10))
        box.grid(row=0, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)

        search_bar = ttk.Frame(box)
        search_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, self.s(6)))
        search_bar.columnconfigure(0, weight=1)
        self.entry_kw = ttk.Entry(search_bar, font=FONT)
        self.entry_kw.grid(row=0, column=0, sticky="ew")
        self.entry_kw.bind("<Return>", lambda event: self.search_courses())
        ttk.Label(search_bar, text="范围").grid(row=0, column=1, padx=(self.s(8), self.s(4)))
        self.cb_scope = ttk.Combobox(search_bar, width=12, state="readonly",
                                     values=SCOPE_CHOICES)
        self.cb_scope.current(0)
        self.cb_scope.grid(row=0, column=2)
        ttk.Button(search_bar, text="搜索课程", command=self.search_courses).grid(
            row=0, column=3, padx=(self.s(8), 0))

        cols = ("name", "teacher", "place", "seat", "status")
        self.tree_res = ttk.Treeview(box, columns=cols, show="headings", height=12)
        heads = {"name": ("课程", 180), "teacher": ("老师", 70), "place": ("上课时间 / 地点", 270),
                 "seat": ("名额 已选/总", 85), "status": ("状态", 75)}
        for key in cols:
            title, width = heads[key]
            self.tree_res.heading(key, text=title)
            self.tree_res.column(key, width=self.s(width), anchor="w")
        self.tree_res.grid(row=1, column=0, sticky="nsew")
        res_bar = ttk.Scrollbar(box, orient="vertical", command=self.tree_res.yview)
        res_bar.grid(row=1, column=1, sticky="ns")
        res_hbar = ttk.Scrollbar(box, orient="horizontal", command=self.tree_res.xview)
        res_hbar.grid(row=2, column=0, sticky="ew")
        self.tree_res.configure(yscrollcommand=res_bar.set, xscrollcommand=res_hbar.set)
        self.tree_res.tag_configure("odd", background="#F5F5F5")
        self.tree_res.bind("<Double-1>", self._add_from_results)

        foot = ttk.Frame(box)
        foot.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(self.s(6), 0))
        self.var_only_free = tk.BooleanVar(value=False)
        ttk.Checkbutton(foot, text="只看还有名额的", variable=self.var_only_free,
                        command=self._render_results).pack(side="left")
        self.var_count = tk.StringVar(value="还没有搜索")
        ttk.Label(foot, textvariable=self.var_count, foreground="#555555",
                  font=FONT_SMALL).pack(side="left", padx=(self.s(12), 0))

    def _build_log(self):
        box = ttk.LabelFrame(self, text=" 运行日志 ", padding=self.s(10))
        box.grid(row=2, column=0, columnspan=2, sticky="nsew",
                 padx=self.s(16), pady=(0, self.s(12)))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.txt_log = scrolledtext.ScrolledText(box, height=8, width=1, state="disabled",
                                                 font=("Consolas", 9), wrap="word",
                                                 relief="solid", borderwidth=1)
        self.txt_log.grid(row=0, column=0, sticky="nsew")

    # ==================== 配置 ====================

    @property
    def config_path(self):
        return os.path.join(app_dir(), CONFIG_NAME)

    def _load_config(self):
        """读配置。**任何**读不出来的情况都当没有配置，绝不让程序起不来。

        踩过的坑：如果配置文件里是合法 JSON 但不是一个对象（比如被写坏成
        `[]`、`5`、`"x"`），原来会把列表当字典用，`App()` 直接在启动时抛
        AttributeError——窗口都建不出来。打包成 exe 之后没有控制台，用户
        看到的现象就是"双击了没反应"，而且删了 exe 重下也一样（配置还在旁边）。
        """
        try:
            import json
            with open(self.config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save_config(self):
        import json
        data = {
            "raw": self.txt_creds.get("1.0", "end").strip(),
            "speed": self.var_speed.get(),
            "burst": bool(self.var_burst.get()),
            "burst_time": _fmt_clock(self._start_time_value() or 0),
            "scope": self.cb_scope.current(),
            "grab_list": [dict(item) for item in self._grab_in_order()],
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
        except Exception as error:
            self.log("配置没能保存：%s" % error)

    def _restore_config(self):
        """按配置恢复界面。每一项都当成不可信输入来读。"""
        raw = self.cfg.get("raw", "")
        if isinstance(raw, str) and raw:
            self.txt_creds.insert("1.0", raw)
        if isinstance(self.cfg.get("speed"), int):
            self.var_speed.set(min(max(self.cfg["speed"], 0), len(SPEED_PRESETS) - 1))
        burst_time = self.cfg.get("burst_time")
        if isinstance(burst_time, str) and burst_time:
            restored = parse_start_time(burst_time)
            if restored is not None:
                self._set_start_time(restored)
        self.var_burst.set(bool(self.cfg.get("burst")))
        if isinstance(self.cfg.get("scope"), int):
            self.cb_scope.current(min(max(self.cfg["scope"], 0),
                                      len(SCOPE_CHOICES) - 1))
        grab_list = self.cfg.get("grab_list")
        if isinstance(grab_list, list):
            for item in grab_list:
                # 只收形状对得上的条目：清单缺 id/type 时 start_grab 会拒绝启动，
                # 在这里挡掉坏数据，用户不用自己去清配置。
                if isinstance(item, dict) and item.get("id") and item.get("type"):
                    self._append_grab_item(item)
        self._on_speed_change()
        self._on_burst_toggle()

    def _on_speed_change(self):
        """选了哪一档，就在下面用一句话说清它的代价。"""
        self.var_speed_hint.set("提示：" + SPEED_HINTS[self.var_speed.get()])

    def _time_box(self, parent, tip):
        """造一个两位数的输入小框，**并在它后面标出单位**（时 / 分 / 秒）。

        tip 一定要显示出来：三个框长得一模一样、中间只夹两个冒号，
        不标单位用户根本不知道哪个是小时、哪个是秒——只能靠猜或者问。
        （这个参数原来收了却没画出来，界面上就是三个空框，纯靠猜。）
        """
        box = ttk.Entry(parent, width=3, font=FONT, justify="center")
        box.pack(side="left", padx=(self.s(4), 0))
        box.bind("<KeyRelease>", self._on_time_typed)
        ttk.Label(parent, text=tip, font=FONT_SMALL,
                  foreground="#555555").pack(side="left", padx=(self.s(2), self.s(4)))
        return box

    def _on_time_typed(self, event=None):
        """输入时的即时照顾：只留数字、补齐不够两位、填满两位自动跳到下一格。"""
        box = event.widget
        raw = "".join(ch for ch in box.get() if ch.isdigit())[:2]
        if raw != box.get():
            at_end = box.index("insert") >= len(box.get())
            box.delete(0, "end")
            box.insert(0, raw)
            if at_end:
                box.icursor("end")
        if len(raw) == 2:
            order = (self.entry_burst_h, self.entry_burst_m, self.entry_burst_s)
            try:
                nxt = order[order.index(box) + 1]
            except (ValueError, IndexError):
                nxt = None      # 已经在「秒」框了，没有下一格
            if nxt is not None:
                nxt.focus_set()
        # 每次敲完都要刷新提示。以前这行写在「跳到下一格」里面，于是在最后一个
        # 框（秒）里填完两位会提前 return，提示停在上一次的内容上不动。
        self._on_burst_toggle()

    def _read_start_time(self):
        """把「时 分 秒」三个框读成当天第几秒。返回 (秒数, 出错说明)。"""
        hour = self.entry_burst_h.get().strip()
        minute = self.entry_burst_m.get().strip()
        second = self.entry_burst_s.get().strip() or "0"
        for text in (hour, minute, second):
            if text and not text.isdigit():
                return None, "只能填数字（冒号已经给你放好了，不用自己打）"
        if not hour or not minute:
            return None, "至少把「时」和「分」填上，例如下午三点就填 15 : 00"
        if not (0 <= int(hour) <= 23):
            return None, "「时」要填 0~23（下午三点是 15）"
        if not (0 <= int(minute) <= 59):
            return None, "「分」要填 0~59"
        if not (0 <= int(second) <= 59):
            return None, "「秒」要填 0~59"
        return int(hour) * 3600 + int(minute) * 60 + int(second), ""

    def _set_start_time(self, seconds):
        """把秒数填回三个框（读配置时用）。"""
        total = max(0, int(seconds)) % 86400
        for box, value in ((self.entry_burst_h, total // 3600),
                           (self.entry_burst_m, total % 3600 // 60),
                           (self.entry_burst_s, total % 60)):
            box.delete(0, "end")
            box.insert(0, "%02d" % value)

    def _start_time_value(self):
        """给外面用：返回秒数或 None。"""
        return self._read_start_time()[0]

    def _on_burst_toggle(self):
        if not self.var_burst.get():
            self.var_burst_hint.set("")
            return
        if self._start_time_value() is None:
            self.var_burst_hint.set("还没有填好开抢时刻。" + self._read_start_time()[1])
            return
        self.var_burst_hint.set(
            "会在开抢前 %.0f 秒开始每秒约 7 次高频提交，冲 %.0f 秒后自动降回上面选的速度；"
            "中途收到「操作过于频繁」会立刻退出高频。" % (BURST_LEAD, BURST_WINDOW))

    # ==================== 日志与消息 ====================

    def _busy(self) -> bool:
        """现在是不是有一轮任务在跑（抢课、搜索或检查凭证）。"""
        return self.worker is not None

    def _refuse_if_busy(self, action: str) -> bool:
        """正在跑的时候，动手改东西的入口一律先挡住。

        为什么值得为它写一个函数：抢课线程是**照着清单在跑的**，
        清单被另一头改掉（清空 / 删条目 / 又加一条），它会在半路发现
        条目不见了，然后把没抢到的课当成「已完成」汇报——用户看到的是
        「全部都处理完了」，实际上什么都没抢。所以这里不是体验问题，
        是不挡住就会撒谎的问题。
        """
        if not self._busy():
            return False
        messagebox.showinfo(
            "正在跑，先等等",
            "现在正在%s，清单和课程都不能改。\n\n"
            "要改的话先点「停止」，改完再点「▶ 开始抢课」。" % action)
        return True

    def log(self, text):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", time.strftime("[%H:%M:%S] ") + str(text) + "\n")
        # 挂一晚上能写几万行，不设上限的话文本框会越拖越慢、内存一直涨。
        # 只留最近这些行，够回看，也不至于把程序拖死。
        lines = int(self.txt_log.index("end-1c").split(".")[0])
        if lines > self.LOG_MAX_LINES:
            self.txt_log.delete("1.0", "%d.0" % (lines - self.LOG_MAX_LINES + 1))
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _post(self, kind, payload=None):
        self.msg_q.put((kind, payload))

    def _poll_queue(self):
        try:
            self._drain_queue()
        except tk.TclError:
            return          # 窗口已经关了（after 回调比销毁晚一步到），收工
        except Exception:
            # 处理某一条消息时出错，不能让轮询从此停摆——那样界面看起来
            # 就是"卡死"：日志不动、按钮没反应，而且没有任何提示。
            self.report_callback_exception(*sys.exc_info())
        try:
            self.after(120, self._poll_queue)
        except tk.TclError:
            pass

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.msg_q.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "progress":
                    self.var_progress.set(payload)
                elif kind == "results":
                    self.all_rows = payload
                    self._render_results()
                elif kind == "count":
                    self.var_count.set(payload)
                elif kind == "grab_status":
                    iid, status = payload
                    if iid in self.grab_items:
                        self.tree_grab.set(iid, "status", status)
                elif kind == "busy":
                    # 任务结束后必须把 worker 置回 None。以前没有这一步，
                    # 于是「第一个任务跑完」之后，检查凭证 / 搜索 / 开始抢课
                    # 这三个入口全都会被"正在忙"永久挡住——程序等于废了。
                    # 在轮询里改（主线程），不在工作线程里改，避免两个线程同时碰它。
                    if not payload:
                        self.worker = None
                    state = "disabled" if payload else "normal"
                    self.btn_start.configure(state=state)
                    self.btn_stop.configure(state="normal" if payload else "disabled")
                elif kind == "finished":
                    self._on_grab_finished(payload)
                elif kind == "stopall":
                    self._on_stop_all(payload)
                elif kind == "preflight":
                    self._on_preflight(payload)
        except queue.Empty:
            pass

    # ==================== ① 凭证 ====================

    def _on_creds_modified(self, event=None):
        # Text 的 <<Modified>> 会因为复位标记再次触发，用标志位挡掉
        if getattr(self, "_muted", False):
            return
        self._muted = True
        self.txt_creds.edit_modified(False)
        self._muted = False
        # 只保留最后一次。原来每改一下都排一个任务，粘一大段 cURL 会一次堆上
        # 几百个待解析任务（都是同一份文本），白白占着事件循环。
        if self._auto_parse_job is not None:
            try:
                self.after_cancel(self._auto_parse_job)
            except tk.TclError:
                pass
        self._auto_parse_job = self.after(400, self._auto_parse)

    def _paste_from_clipboard(self):
        try:
            data = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo("提示", "剪贴板里没有文字。请先在浏览器里右键 → Copy as cURL。")
            return
        self.txt_creds.delete("1.0", "end")
        self.txt_creds.insert("1.0", data)

    def _clear_creds(self):
        self.txt_creds.delete("1.0", "end")
        # 顺手把存到磁盘上的那份也一起抹掉。不然用户以为点了「清空」就干净了，
        # 实际上程序旁边还留着一份明文凭证——说明书承诺了「点清空再关掉就抹掉」，
        # 代码就得真的做到。
        self._save_config()

    def _auto_parse(self):
        """粘贴后自动识别，认全了就自动验证一次——省掉两次点击。"""
        self._auto_parse_job = None
        self.var_check.set("")          # 内容变了，上次的检查结果作废
        pasted = self.txt_creds.get("1.0", "end")
        self.creds = parse_credentials(pasted)
        missing = missing_fields(self.creds)
        marks = {key: ("✅" if self.creds.get(key) else "❌")
                 for key in ("student_code", "cookie", "token", "batch")}
        if missing:
            # 缺东西时给「下一步怎么做」，而不是只报「还缺什么」。
            # 最常见的就是搜不到 Cookie——那基本只有一个原因：
            # 复制时选了 cmd / powershell 那两种格式（实测它们会少掉 Cookie 那一行）。
            hint = ""
            if "Cookie" in missing:
                hint = ("\n★ 少了 Cookie？多半是复制时选的不是 bash："
                        "回到浏览器重新复制一次，在 Copy as cURL 里选 bash 那个。")
                if _looks_like_cmd_curl(pasted):
                    hint += "（你这串看起来就是 cmd 那种格式。）"
            self.var_creds.set(
                "%s 学号　%s Cookie　%s token　%s 批次码\n还缺：%s%s"
                % (marks["student_code"], marks["cookie"], marks["token"],
                   marks["batch"], "、".join(missing), hint))
            return

        # Cookie 那一行把「有哪几段」也列出来（只要名字，不含值）：
        # 少了任何一段都会让服务器回登录页，光看字符数看不出来。
        # 用户可以直接跟浏览器里那几段对照，我这边也能据此判断是不是解析漏了。
        pairs = cookie_pairs(self.creds["cookie"])
        self.var_creds.set(
            "%s 学号 %s　%s Cookie（%d 字符 / %d 段：%s）\n%s token（%d 字符）"
            "　%s 批次码 %s"
            % (marks["student_code"], self.creds["student_code"], marks["cookie"],
               len(self.creds["cookie"]), len(pairs), "、".join(pairs[:6]),
               marks["token"], len(self.creds["token"]), marks["batch"],
               self.creds["batch"][:12] + "…"))

        # 认全了就顺手存一份：这样下次打开软件，凭证会自动填回来。
        # （原来只有"动过抢课清单"才会存，只粘贴没加课就关掉的话，重开是空的。）
        self._save_config()

        signature = tuple(self.creds[key] for key in
                          ("student_code", "cookie", "token", "batch"))
        if signature != self.checked_signature and self.worker is None:
            self.checked_signature = signature
            self._check_creds(silent=True)

    def _make_grabber(self, notify=True):
        try:
            self.grabber = CourseGrabber(self.creds)
            return self.grabber
        except CredentialError as error:
            if notify:
                messagebox.showwarning("凭证还没齐", str(error))
            return None

    def _check_creds(self, silent=False):
        if self._busy():
            if not silent:
                # 以前这里直接 return，按钮点了毫无反应，用户会以为程序坏了
                messagebox.showinfo(
                    "正在跑，先等等",
                    "现在正在抢课（或搜索），等这一轮结束再检查凭证。\n"
                    "想立刻检查就先点「停止」。")
            return
        self.creds = parse_credentials(self.txt_creds.get("1.0", "end"))
        missing = missing_fields(self.creds)
        if missing:
            if not silent:
                messagebox.showwarning(
                    "凭证还没齐",
                    "还缺：%s\n\n请在浏览器里右键 recommendedCourse.do → "
                    "Copy as cURL，把整段内容都复制过来。" % "、".join(missing))
            return
        grabber = self._make_grabber(notify=not silent)
        if grabber is None:
            return
        if grabber.base != BASE_URL:
            self.log("连接目标：%s（按你粘贴的那条网址走）" % grabber.base)
        self.log("正在检查凭证…")
        self.var_check.set("正在检查凭证…")
        self._start_worker(self._preflight_worker, grabber)

    def _preflight_worker(self, grabber):
        try:
            report = grabber.preflight()
        except CredentialError as error:
            self._post("preflight", {"ok": False, "reason": str(error)})
            return
        except requests.RequestException as error:
            # 单独把「网络问题」标出来：它跟凭证没关系，界面要给出不一样的提示
            self._post("preflight", {"ok": False, "network": str(error),
                                     "reason": "网络连不上选课系统：%s" % error})
            return
        except Exception as error:
            self._post("preflight", {"ok": False, "reason": "检查失败：%s" % error})
            return
        self._post("preflight", report)

    def _on_preflight(self, report):
        if not report.get("ok"):
            if report.get("network"):
                # 网络不通时，那一大串 Python 报错对新用户来说等于没有信息。
                # 日志里给人话（含该怎么办），标签上只留一句短的（长了会把左栏撑开）。
                for line in network_advice(report["network"]).splitlines():
                    self.log(line)
                self.var_check.set("❌ 连不上选课系统——看日志里的办法")
                return
            reason = report.get("reason", "未知原因")
            self.log("凭证检查没通过：" + reason)
            self.var_check.set("❌ 检查没通过：" + reason)
            return

        selected = report.get("selected") or []
        self.log("凭证有效，学号 %s，已选上 %d 门课。"
                 % (self.creds["student_code"], len(selected)))

        # 把这条路的往返延迟报出来。用户前几天就是这么吃亏的：
        # 他走 WebVPN，每次请求要 10 秒，速度和自动开抢在那条路上基本没用，
        # 而界面上完全看不出来——只能靠事后排查。
        rtt = float(getattr(self.grabber, "last_rtt", 0.0) or 0.0)
        if rtt > 0:
            self.log("这条路的往返延迟：约 %.2f 秒。" % rtt)
            if rtt > 2.0:
                self.log("★ 警告：这条路太慢（每次请求要 %.1f 秒）。"
                         "抢课那几秒靠的是「请求到得够快」，这条路上速度档和自动开抢"
                         "基本发挥不出来。建议改用直连地址（http://bkxk.szu.edu.cn"
                         "）重新复制一次凭证。" % rtt)
        for item in selected:
            self.log("   · 已选：%s｜%s｜%s"
                     % (item["name"], item["teacher"], item["place"]))

        if report.get("batch_ok"):
            self.log("批次码可用（能看到 %d 门课），可以开始抢课了。"
                     % report.get("courses_visible", 0))
            self.var_check.set("✅ 检查通过，可以开始抢课了")
        else:
            note = report.get("note", "批次码可能不对")
            self.log("⚠ " + note)
            self.var_check.set("⚠ " + note)

    # ==================== ② 找课 ====================

    def _scope_types(self):
        choice = self.cb_scope.get()
        if choice.startswith("常用"):
            return list(COMMON_SEARCH_TYPES)
        if choice == "全部":
            return list(TYPE_ORDER)
        for code, name in COURSE_TYPES.items():
            if name == choice:
                return [code]
        return list(COMMON_SEARCH_TYPES)

    def search_courses(self):
        # 以前这里弹了「不能再搜课」的提示却没 return，于是照着往下跑、
        # 又开了一个搜索线程，把正在抢课的那个 worker 引用顶掉——
        # 「忙」这道闸门就此失效，可以再开第二个抢课线程。
        if self._refuse_if_busy("抢课"):
            return
        self.creds = parse_credentials(self.txt_creds.get("1.0", "end"))
        if missing_fields(self.creds):
            messagebox.showwarning("先粘凭证", "还没粘贴凭证。请先完成 ① 的步骤。")
            return
        grabber = self._make_grabber()
        if grabber is None:
            return

        keyword = self.entry_kw.get().strip()
        types = self._scope_types()
        self.stop_flag.clear()
        self.log("开始搜索「%s」（范围：%s）…"
                 % (keyword or "全部", "、".join(COURSE_TYPES[t] for t in types)))
        self._start_worker(self._search_worker, grabber, keyword, types)

    def _search_worker(self, grabber, keyword, types):
        def on_progress(type_name, page, count):
            self._post("progress", "正在搜索 %s 第 %d 页，已找到 %d 条…"
                       % (type_name, page, count))

        try:
            rows = grabber.search(keyword, types, on_progress=on_progress,
                                  should_stop=self.stop_flag.is_set)
        except CredentialError as error:
            self._post("log", "搜索失败：" + str(error))
            return
        except requests.RequestException as error:
            for line in network_advice(str(error)).splitlines():
                self._post("log", line)
            return
        except Exception as error:
            self._post("log", "搜索失败：%s" % error)
            return
        self._post("results", rows)
        self._post("log", "搜索完成，共 %d 门课。" % len(rows))
        self._post("progress", "清单是空的：在右边双击一行加入" if not self.grab_items else "")

    def _render_results(self):
        self.tree_res.delete(*self.tree_res.get_children())
        self.results.clear()
        only_free = self.var_only_free.get()
        shown = 0
        for index, row in enumerate(self.all_rows):
            if only_free and (row["full"] or row["chosen"]):
                continue
            iid = self.tree_res.insert("", "end", tags=("odd",) if index % 2 else (), values=(
                row["name"], row["teacher"], row["place"],
                "%s/%s" % (row["selected_count"], row["capacity"]), status_of(row)))
            self.results[iid] = row
            shown += 1
        if not self.all_rows:
            self.var_count.set("还没有搜索")
        elif shown == len(self.all_rows):
            self.var_count.set("共 %d 门（双击加入抢课清单）" % shown)
        else:
            self.var_count.set("显示 %d / %d 门" % (shown, len(self.all_rows)))

    def _add_from_results(self, event=None):
        if self._refuse_if_busy("抢课"):
            return
        iid = self.tree_res.identify_row(event.y) if event else None
        iid = iid or (self.tree_res.selection() or [None])[0]
        row = self.results.get(iid)
        if not row:
            return
        for item in self.grab_items.values():
            if item["id"] == row["id"]:
                self.log("「%s」已经在抢课清单里了。" % row["name"])
                return
        self._append_grab_item({
            "id": row["id"], "name": row["name"], "teacher": row["teacher"],
            "type": row["type"], "status": "待抢",
        })
        self.log("已加入抢课清单：%s（%s）" % (row["name"], row["teacher"]))
        self._save_config()

    # ==================== 抢课清单 ====================

    def _append_grab_item(self, item):
        iid = self.tree_grab.insert("", "end", values=(
            item.get("name", ""), item.get("teacher", ""), item.get("status", "待抢")))
        self.grab_items[iid] = {
            "id": item.get("id", ""), "name": item.get("name", ""),
            "teacher": item.get("teacher", ""), "type": item.get("type", ""),
            "status": item.get("status", "待抢"),
        }
        self.var_progress.set("清单里有 %d 门课" % len(self.grab_items))

    def _grab_in_order(self):
        return [self.grab_items[iid] for iid in self.tree_grab.get_children()
                if iid in self.grab_items]

    def _remove_grab_item(self):
        if self._refuse_if_busy("抢课"):
            return
        for iid in self.tree_grab.selection():
            self.tree_grab.delete(iid)
            self.grab_items.pop(iid, None)
        self.var_progress.set("清单里有 %d 门课" % len(self.grab_items))
        self._save_config()

    def _clear_grab_list(self):
        if self._refuse_if_busy("抢课"):
            return
        if self.grab_items and not messagebox.askyesno("清空", "确定清空抢课清单？"):
            return
        self.tree_grab.delete(*self.tree_grab.get_children())
        self.grab_items.clear()
        self.var_progress.set("清单是空的：先在右边搜课，双击一行加入")
        self._save_config()

    # ==================== ③ 抢课 ====================

    def start_grab(self):
        if self._busy():
            messagebox.showinfo("提示", "已经在跑了，先点停止。")
            return
        if not self.grab_items:
            messagebox.showinfo("提示", "抢课清单是空的：先在右边搜课，双击一行加入。")
            return
        self.creds = parse_credentials(self.txt_creds.get("1.0", "end"))
        if missing_fields(self.creds):
            messagebox.showwarning("先粘凭证", "还没粘贴凭证。请先完成 ① 的步骤。")
            return
        grabber = self._make_grabber()
        if grabber is None:
            return

        broken = [item["name"] for item in self._grab_in_order()
                  if not item.get("id") or not item.get("type")]
        if broken:
            messagebox.showwarning(
                "清单里有不能用的条目",
                "这 %d 条缺少课程编号或类型，程序没法拿它们提交选课：\n\n%s\n\n"
                "请把它们从清单里移除，再到右边搜课重新加入。"
                % (len(broken), "、".join(broken)))
            return

        burst_plan = None
        if self.var_burst.get():
            start_sec, why = self._read_start_time()
            if start_sec is None:
                messagebox.showwarning("开抢时刻还没填好", why)
                return
            burst_plan = {"start": start_sec}

        _, low, high = SPEED_PRESETS[self.var_speed.get()]
        self.stop_flag.clear()
        for iid in self.grab_items:
            self.grab_items[iid]["status"] = "待抢"
            self.tree_grab.set(iid, "status", "待抢")
        self.attempt_counts.clear()
        self.log("开始抢课：%d 门，间隔 %d~%dms 随机。抢到会自动划掉。"
                 % (len(self.grab_items), low, high))
        # 清单在这里（主线程）读出来交给工作线程。工作线程不能自己去读 Tk 控件——
        # Tk 不是线程安全的，从别的线程调它轻则随机报错，重则整个界面卡死。
        self._start_worker(self._grab_worker, grabber, (low, high), burst_plan,
                           self._grab_in_order_iids())

    def _start_worker(self, target, *args):
        # 这两个按钮的状态必须在这里一起设：开始→禁用（防重复派发）、
        # 停止→启用（**不然用户根本没法让它停下来**）。
        # 这个 bug 存在了好几个版本：停止按钮初值是 disabled，而这里原来只
        # 禁用了「开始」，从来没启用过「停止」；唯一一条"忙"消息又是任务结束
        # 时才发的（busy=False），于是它只会把停止按钮再设成禁用。
        # 用户看到的现象就是「开抢了，暂停按钮按不了」。
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.worker = threading.Thread(target=self._run_worker, args=(target, args), daemon=True)
        self.worker.start()

    def _run_worker(self, target, args):
        try:
            target(*args)
        except Exception as error:  # 线程里出错不能让窗口无声卡住
            self._post("log", "出错：%s" % error)
        finally:
            self._post("busy", False)

    def _grab_worker(self, grabber, delay_range, burst_plan=None, pending=None):
        # pending 正常由 start_grab 在主线程里读好传进来；直接调用（比如自检脚本）
        # 时退回按 grab_items 的顺序来，那是普通字典，跨线程读没问题。
        pending = list(self.grab_items) if pending is None else list(pending)
        total = len(pending)
        got = 0
        rounds = 0
        last_kind = ""
        style_noted = False
        clock_offset = 0.0
        burst_deadline = None
        error_streak = {}       # 每门课连续收到「读不懂的回复」的次数

        # ---- 开抢时刻：先对时，再待机，到点前几秒开始高频冲 ----
        if burst_plan:
            try:
                clock_offset = grabber.server_clock_offset()
                # 如实描述：这个精度是"秒级"的（HTTP 的 Date 只到整秒），
                # 所以不要显示到小数点后——那会让人以为对得很准。
                if abs(clock_offset) < 0.5:
                    self._post("log", "已跟服务器对时：你的电脑和它基本一致"
                                      "（相差不到半秒）。")
                else:
                    self._post("log", "已跟服务器对时：你的电脑比它%s约 %.0f 秒。"
                               % ("快" if clock_offset < 0 else "慢", abs(clock_offset)))
            except Exception as error:
                self._post("log", "对时没成功（%s），改用你电脑的时钟算，"
                                  "请先确认系统时间准确。" % error)
            # 提前量按这条路的实测延迟算：慢链路要更早出发，
            # 否则"提前 2 秒"发出去的请求，等到开抢后几秒才到（白冲）。
            lead = burst_lead_for(getattr(grabber, "last_rtt", 0.0))
            if lead > BURST_LEAD + 0.01:
                self._post("log", "这条路往返要 %.1f 秒，所以提前 %.0f 秒开始冲"
                                  "（而不是默认的 %.0f 秒），保证第一个请求在开抢那一刻"
                                  "已经到达。" % (getattr(grabber, "last_rtt", 0.0),
                                                 lead, BURST_LEAD))
            now_s = server_seconds_now(clock_offset)
            left = seconds_until_start(burst_plan["start"], clock_offset)
            self._post("log", "★ 已校准服务器时间：它现在是 %s，你填的开抢时刻是 %s。"
                       % (_fmt_clock(now_s), _fmt_clock(burst_plan["start"])))
            target_hour = int(burst_plan["start"]) // 3600
            if 1 <= target_hour <= 11 and 3 * 3600 < left < 20 * 3600:
                self._post("log", "⚠ 留意：目标时刻落在凌晨 %s，而且要等 %.1f 小时。"
                                  "如果你其实是想设「下午」那个点，24 小时制要写成 %02d:00"
                                  "（下午三点 = 15:00）。现在点停止还来得及改。"
                           % (_fmt_clock(burst_plan["start"])[:5], left / 3600.0,
                              target_hour + 12))
            if left <= -BURST_WINDOW:
                self._post("log", "填的开抢时刻已经过去"
                                  "（服务器现在 %s，你填的是 %s），就不做高频了，"
                                  "直接按正常速度跑。"
                           % (_fmt_clock(now_s), _fmt_clock(burst_plan["start"])))
            else:
                if left > lead:
                    self._post("log", "开始待机，会在开抢前 %.0f 秒自动进入高频。" % lead)
                    next_resync = time.time() + 1800      # 每半小时重新对一次时
                    while not self.stop_flag.is_set():
                        left = seconds_until_start(burst_plan["start"], clock_offset)
                        if left <= lead:
                            break
                        if time.time() >= next_resync:
                            try:
                                clock_offset = grabber.server_clock_offset()
                                self._post("log", "重新对了一次时：你的电脑比服务器%s约 %.0f 秒。"
                                           % ("快" if clock_offset < 0 else "慢",
                                              max(0.5, abs(clock_offset))))
                            except Exception as error:
                                self._post("log", "重新对时失败（%s），继续用上次的结果。" % error)
                            next_resync = time.time() + 1800
                        self._post("progress", "等待开抢：服务器现在 %s → 目标 %s（还有 %d 分 %02d 秒）"
                                   % (_fmt_clock(server_seconds_now(clock_offset)),
                                      _fmt_clock(burst_plan["start"]),
                                      int(left) // 60, int(left) % 60))
                        if self.stop_flag.wait(max(0.05, min(0.5, left - lead))):
                            break
                if self.stop_flag.is_set():
                    # 等待期间用户按了停止：别再说"进入高频"，直接收尾
                    self._post("finished", {
                        "got": got, "total": total, "left": [], "stopped": True})
                    return
                burst_deadline = time.time() + lead + BURST_WINDOW
                self._post("log", "★ 进入高频：每 %d~%d 毫秒提交一次，冲 %.0f 秒，"
                                  "之后自动降回正常速度。"
                           % (BURST_INTERVAL[0], BURST_INTERVAL[1], BURST_WINDOW))

        while pending and not self.stop_flag.is_set():
            rounds += 1
            for iid in list(pending):
                if self.stop_flag.is_set():
                    break
                item = self.grab_items.get(iid)
                if item is None:
                    pending.remove(iid)
                    continue

                try:
                    text = grabber.choose(item["id"], item["type"])
                    status = getattr(grabber, "last_status", 200)
                    if status >= 500:
                        # 服务器自己故障时也会回一页 HTML，长得跟登录页很像。
                        # 不能据此认为凭证废了、更不能把账算到这门课头上。
                        kind = "busy_server"
                    else:
                        kind = classify(text)
                except CredentialError as error:
                    self._post("stopall", str(error))
                    return
                except requests.RequestException as error:
                    kind, text = "network", str(error)
                except Exception as error:
                    kind, text = "network", str(error)

                if grabber.style_switched and not style_noted:
                    style_noted = True
                    self._post("log", "提示：第一种参数格式没被接受，已自动换用另一种"
                                      "（之后一直用这种，不会再重复发送）。")

                counts = self.attempt_counts[iid] = self.attempt_counts.get(iid, 0) + 1

                # 「读不懂 / 异常」连续太多次，说明这个条目本身有问题（编号失效、
                # 课程被删等），停下这门课并说明，而不是一直重试。
                # 但网络断了、服务器 5xx 这类是**环境的**问题，不能算这门课的账——
                # 开抢那几秒钟服务器一抖就把课划掉，那才是真的亏。
                if kind in ("server_error", "unknown"):
                    error_streak[iid] = error_streak.get(iid, 0) + 1
                else:
                    error_streak[iid] = 0
                if error_streak.get(iid, 0) >= MAX_CONSECUTIVE_ERRORS:
                    pending.remove(iid)
                    self._set_grab_status(iid, "❌ 连续异常，已停下")
                    self._post("log", "「%s」连续 %d 次都收到看不懂的回复，先停下这门课。"
                                      "最后一次的回复是：%s"
                               % (item["name"], MAX_CONSECUTIVE_ERRORS,
                                  plain_result(kind, text, limit=80)))
                    continue

                if kind == "success":
                    got += 1
                    pending.remove(iid)
                    self._set_grab_status(iid, "✅ 抢到了")
                    self._post("log", "🎉 抢到了：%s（%s）" % (item["name"], item["teacher"]))
                elif kind == "dup":
                    got += 1
                    pending.remove(iid)
                    self._set_grab_status(iid, "✅ 之前已选上")
                    self._post("log", "这门课本来就已经选上了：%s" % item["name"])
                elif kind in STOPALL_RESULTS:
                    self._set_grab_status(iid, plain_result(kind))
                    self._post("stopall", "%s\n\n%s" % (
                        plain_result(kind, text),
                        "请在浏览器里重新复制一次 recommendedCourse.do 的 cURL，粘回 ① 里再开抢。"))
                    return
                elif kind in FATAL_RESULTS:
                    pending.remove(iid)
                    self._set_grab_status(iid, "❌ " + plain_result(kind))
                    self._post("log", "「%s」抢不到了：%s（已从清单划掉）"
                               % (item["name"], plain_result(kind, text)))
                else:
                    # 名额满 / 太频繁 / 还没到时间 —— 都属于「继续蹲」
                    if counts == 1 or counts % 20 == 0 or kind != last_kind:
                        self._post("log", "「%s」%s（第 %d 次）"
                                   % (item["name"], plain_result(kind, text), counts))

                self._post("progress", "正在抢：%s　·　第 %d 轮　·　已抢到 %d/%d　·　%s 已试 %d 次"
                           % (item["name"], rounds, got, total, item["name"], counts))

                last_kind = kind

                if burst_deadline is not None:
                    if kind == "throttle":
                        burst_deadline = None
                        self._post("log", "被提示操作过于频繁，立刻退出高频模式，改用正常速度。")
                    elif time.time() >= burst_deadline:
                        # 用「已经冲了多久」判断，不用「当天第几秒」——后者在
                        # 23:59:50 这种时刻会算出超过一天的值（86405），而服务器
                        # 秒数永远在 0~86399 之间，条件永远不成立，高频就退不出来了。
                        burst_deadline = None
                        self._post("log", "高频时段结束，回到你选的速度继续抢。")

                if burst_deadline is not None:
                    # 高频期不走 next_delay：它的下限是 200ms，盖不住我们要的间隔
                    seconds = random.uniform(BURST_INTERVAL[0], BURST_INTERVAL[1]) / 1000.0
                else:
                    seconds = next_delay(delay_range, kind,
                                         on_note=lambda note: self._post("log", note))
                if self.stop_flag.wait(seconds):
                    break

        # 收尾核对：系统的回复措辞是我们猜的，猜漏了就会把「其实抢到了」
        # 报成「没抢到」。这里直接去查一次「已选课程」，把对得上的补回来。
        if not self.stop_flag.is_set():
            got += self._verify_against_selected(grabber)

        self._post("finished", {
            "got": got, "total": total,
            "left": [self.grab_items[iid]["name"] for iid in pending
                     if iid in self.grab_items],
            "stopped": self.stop_flag.is_set(),
        })

    def _verify_against_selected(self, grabber) -> int:
        """跟服务器的「已选课程」核对一遍，把误判成失败的课改回来。

        返回补回来的门数。查不到就当没查，绝不因为核对失败去改状态。
        """
        doubtful = [iid for iid, item in self.grab_items.items()
                    if str(item.get("status", "")).startswith("❌")]
        if not doubtful:
            return 0
        try:
            selected = grabber.query_selected()
        except Exception as error:
            self._post("log", "（没能跟系统核对已选课程：%s）" % error)
            return 0
        names = set()
        for row in selected or []:
            if isinstance(row, dict) and row.get("name"):
                names.add(row["name"].strip())
        if not names:
            return 0
        fixed = []
        for iid in doubtful:
            name = str(self.grab_items[iid].get("name", "")).strip()
            if name and name in names:
                self._set_grab_status(iid, "✅ 已核对：选上了")
                fixed.append(name)
        if fixed:
            self._post("log", "核对「已选课程」后发现这几门其实已经选上了：%s"
                       % "、".join(fixed))
        return len(fixed)

    def _set_grab_status(self, iid, status):
        """改清单里一门课的状态。

        数据当场改（工作线程里就能改），表格的显示交给主线程的轮询去做——
        Tk 控件不能从别的线程碰。
        """
        if iid in self.grab_items:
            self.grab_items[iid]["status"] = status
        self._post("grab_status", (iid, status))

    def _grab_in_order_iids(self):
        return [iid for iid in self.tree_grab.get_children() if iid in self.grab_items]

    def stop_grab(self):
        self.stop_flag.set()
        self.btn_stop.configure(state="disabled")
        self.log("已按停止，当前这一次提交结束后就停。")

    def _on_grab_finished(self, info):
        """一轮结束后的汇报。

        必须分清「全部抢到」和「有的没抢到」——因为一门课被判定为抢不到
        （时间冲突 / 学分已满 / 没权限）时，也会从待办里移除、让循环结束。
        以前不管哪种情况都弹「全部抢到了」，会让人误以为成功。
        """
        total, got = info["total"], info["got"]
        if not total:
            # 不该走到这里（清单为空时 start_grab 就拦住了），但万一走到，
            # 也绝不能弹一句「清单里的 0 门课全部抢到了」。
            self.log("没有可抢的课。")
            self.var_progress.set("清单是空的")
            return
        failed = [item["name"] for item in self._grab_in_order()
                  if item["status"].startswith("❌")]

        if info["stopped"]:
            self.log("已停止。抢到 %d/%d 门。" % (got, total))
            self.var_progress.set("已停止：抢到 %d/%d 门" % (got, total))
            return

        if failed:
            names = "、".join(failed)
            self.log("跑完了：抢到 %d 门，另有 %d 门抢不到（%s）。" % (got, len(failed), names))
            self.var_progress.set("抢到 %d/%d 门；%d 门抢不到，原因见清单"
                                  % (got, total, len(failed)))
            if got == 0:
                messagebox.showwarning(
                    "这一轮没抢到",
                    "清单里的课都没抢到：\n\n%s\n\n"
                    "原因写在「③ 抢课清单」的状态一栏里"
                    "（常见的是时间冲突、学分已满、没权限）。" % names)
            else:
                messagebox.showinfo(
                    "抢到 %d 门，%d 门没抢到" % (got, len(failed)),
                    "抢到了 %d 门；\n有 %d 门抢不到：%s\n\n"
                    "原因写在「③ 抢课清单」的状态一栏里。" % (got, len(failed), names))
        else:
            self.log("全部搞定了，抢到 %d/%d 门。" % (got, total))
            self.var_progress.set("✅ 全部抢到了（%d 门）" % got)
            self.bell()
            messagebox.showinfo("抢到了", "清单里的 %d 门课全部抢到了。\n\n"
                                          "建议去选课系统里再核对一遍。" % got)

    def _on_stop_all(self, reason):
        self.log("停下来了：" + reason.splitlines()[0])
        self.var_progress.set("因凭证问题停下了，见日志")
        messagebox.showerror("需要重新拿一次凭证", reason)

    # ==================== 帮助 ====================

    def show_help(self):
        """使用说明：可选中复制的文本框 + 内嵌示意图 + 可点开的网址。

        这里特意用 tk.Text 而不是一堆 Label：Label 上的字选不中、复制不了，
        网址也点不动。之前为了把示意图塞进来改用 Label 排布，反而把「能复制」
        弄丢了——现在换成 Text 承载文字、示意图用 window_create 嵌进去，
        两种好处都留着。文字是只读的（state=disabled），但只读不影响选中和复制。
        """
        if self.help_win is not None:
            try:
                self.help_win.deiconify()
                self.help_win.lift()
                return
            except tk.TclError:
                self.help_win = None

        win = tk.Toplevel(self)
        self.help_win = win
        win.title("使用说明")
        win.geometry("%dx%d" % (self.s(740), min(self.s(700),
                                                 self.winfo_screenheight() - self.s(110))))

        holder = ttk.Frame(win)
        holder.pack(fill="both", expand=True)
        self.help_text = tk.Text(holder, wrap="word", font=FONT,
                                 padx=self.s(16), pady=self.s(12), relief="flat",
                                 borderwidth=0, highlightthickness=0, cursor="arrow",
                                 spacing1=self.s(2), spacing3=self.s(2))
        bar = ttk.Scrollbar(holder, orient="vertical", command=self.help_text.yview)
        self.help_text.configure(yscrollcommand=bar.set)
        self.help_text.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        t = self.help_text
        t.tag_configure("h1", font=FONT_TITLE, foreground=SZU_RED, spacing3=self.s(6))
        t.tag_configure("h2", font=FONT_BOLD, foreground="#111111",
                        spacing1=self.s(14), spacing2=self.s(2))
        t.tag_configure("note", font=FONT_SMALL, foreground="#666666")
        # 网址：蓝色带下划线，鼠标移上去变手型，点一下用系统浏览器打开
        t.tag_configure("link", foreground="#0B5FA5", underline=True)
        t.tag_bind("link", "<Enter>", lambda e: t.configure(cursor="hand2"))
        t.tag_bind("link", "<Leave>", lambda e: t.configure(cursor="arrow"))

        t.insert("end", "深大抢课助手 · 使用说明\n", "h1")
        t.insert("end", "三步：粘贴凭证 → 搜课 → 开抢。第一次用请从第一节往下看。\n", "note")
        t.insert("end", "下面的字可以直接选中复制（Ctrl+A 全选、Ctrl+C 复制，"
                        "或者在文字上点右键选「复制」）；蓝色的网址点一下就打开。\n", "note")

        for title, body, diagram in GUIDE_SECTIONS:
            t.insert("end", title + "\n", "h2")
            self._insert_with_links(t, body + "\n")
            if diagram:
                canvas = tk.Canvas(t, width=self.s(620),
                                   height=self.s(DIAGRAM_HEIGHT[diagram]),
                                   highlightthickness=0, borderwidth=0,
                                   background="#FCFCFC")
                # 示意图嵌进文本框，跟着文字一起滚动
                t.window_create("end", window=canvas, padx=self.s(4), pady=self.s(6))
                t.insert("end", "\n")
                getattr(Sketch(canvas, self.scale), diagram)()

        t.configure(state="disabled")
        t.yview_moveto(0)       # 重开时从顶上开始，别停在上次滚到的位置

        # 只读文本框默认没有 Ctrl+A；右键菜单也给新手留一条明路
        t.bind("<Control-a>", self._help_select_all)
        menu = tk.Menu(win, tearoff=0)
        menu.add_command(label="全选", command=self._help_select_all)
        menu.add_command(label="复制", command=lambda: t.event_generate("<<Copy>>"))
        t.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        # 点网址就打开。用 @x,y 反查位置，这样即使文本框只读也照样能点。
        t.bind("<Button-1>", self._on_help_click)

        # 滚轮统一在窗口这一层接管：四张示意图是以 Canvas 子窗口嵌进来的，
        # 而 Canvas 在 Tk 里默认不响应滚轮，指针压在图上就完全滚不动。
        # 事件会按 bindtags 冒泡到 toplevel，所以挂在这里能一次覆盖全部子控件。
        win.bind("<MouseWheel>", self._on_help_wheel)

    _URL_RE = re.compile(r"https?://[^\s，。、；：（）「」]+")

    def _on_help_wheel(self, event):
        """说明书窗口里滚轮滚动。

        指针压在示意图（Canvas）或边框上时，事件没有别的控件接手，
        就在这一层滚文本框；压在文字上时交给 Text 自己的默认绑定，
        这里必须让开，否则一次滚轮会滚两倍。
        """
        if event.widget is self.help_text:
            return None
        self.help_text.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _help_select_all(self, event=None):
        self.help_text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _insert_with_links(self, widget, text):
        """把正文写进文本框，其中的网址单独打上 link 标签。"""
        pos = 0
        for m in self._URL_RE.finditer(text):
            widget.insert("end", text[pos:m.start()])
            widget.insert("end", m.group(0), "link")
            pos = m.end()
        widget.insert("end", text[pos:])

    def _on_help_click(self, event):
        index = self.help_text.index("@%d,%d" % (event.x, event.y))
        if "link" in self.help_text.tag_names(index):
            line = self.help_text.get(index + " linestart", index + " lineend")
            hit = self._URL_RE.search(line)
            if hit:
                webbrowser.open(hit.group(0))

    def report_callback_exception(self, exc_type, exc_value, exc_tb):
        """Tk 回调里抛出的异常：默认只打到 stderr，打包后完全看不见。

        这里的处理是：写一份出错记录 + 在日志区留一行 + 弹一次框告诉用户
        记录在哪。弹框本身再出错也不能让程序跟着崩，所以整段包了 try。
        """
        path = write_crash_log(exc_type, exc_value, exc_tb)
        try:
            self.log("程序出错了：%s: %s" % (exc_type.__name__, exc_value))
        except Exception:
            pass
        try:
            messagebox.showerror(
                "程序出错了",
                "刚发生了一个没想到的错误：\n%s: %s\n\n"
                "%s\n\n这一轮抢课可能已经中断，建议点「停止」后重新开始。"
                % (exc_type.__name__, exc_value,
                   ("错误记录写在：\n" + path) if path else "（错误记录没能写出来）"))
        except Exception:
            pass

    def _set_window_icon(self):
        """给窗口设图标。

        分两条路走：先用 ico（能带多个尺寸，标题栏和任务栏都清楚），
        不行再用 PNG 兜底。以前这里只有一句 try/except: pass，
        一旦失败就悄悄退回 Tk 自带的羽毛图标，还不留任何痕迹——
        用户只会觉得「图标怎么是根羽毛」，查都没处查。
        """
        ico_problem = None
        try:
            self.iconbitmap(resource_path("szu_grab.ico"))
            return
        except Exception as error:
            ico_problem = error

        try:
            # PhotoImage 必须留个引用，否则会被回收掉，图标又没了
            self._icon_photo = tk.PhotoImage(file=resource_path("szu_grab.png"))
            self.iconphoto(True, self._icon_photo)
            self.log("提示：ico 图标加载失败，已改用 PNG 兜底（%s）" % ico_problem)
            return
        except Exception:
            pass

        self.log("提示：窗口图标没设置成功（%s）。不影响功能，只是标题栏会是默认图标。"
                 % ico_problem)


# ==========================================================================
# 启动口令门（只有「给大家用」那一份 exe 会有）
#
# 自己用的那份不带 activation.json，所以 activation.ENABLED 是 False，
# 这里直接放行——不弹窗、不联网、什么都不问。
# ==========================================================================

def activation_gate() -> bool:
    """要口令。返回 True 才继续开主窗口。"""
    if not activation.ENABLED:
        return True

    root = tk.Tk()
    root.title("深大抢课助手 · 口令")
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass
    root.resizable(False, False)
    state = {"ok": False, "fails": 0}

    frame = ttk.Frame(root, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="这一份需要口令才能打开", font=FONT_TITLE,
              foreground=SZU_RED).pack(anchor="w")
    ttk.Label(frame, justify="left", foreground="#555555", font=FONT_SMALL,
              text="口令找作者要。\n"
                   "（口令会定期更换；如果你手上是旧版，旧口令可能已经不管用了。）").pack(
        anchor="w", pady=(6, 10))

    entry = ttk.Entry(frame, width=18, font=FONT, justify="center")
    entry.pack(anchor="w")
    entry.focus_set()

    tip = tk.StringVar(value="")
    ttk.Label(frame, textvariable=tip, foreground="#B03030", font=FONT_SMALL,
              justify="left").pack(anchor="w", pady=(6, 0))

    button = ttk.Button(frame, text="进入")
    button.pack(anchor="w", pady=(10, 0))

    def unlock_after(seconds):
        """猜错太多次：按钮先禁用一会儿，挡一下暴力猜。"""
        left = {"n": int(seconds)}

        def tick():
            if left["n"] <= 0:
                button.configure(state="normal")
                tip.set("")
                return
            tip.set("试的次数太多了，等 %d 秒再试。" % left["n"])
            left["n"] -= 1
            root.after(1000, tick)

        button.configure(state="disabled")
        tick()

    def submit(event=None):
        ok, why = activation.verify(entry.get())
        if ok:
            state["ok"] = True
            root.destroy()
            return
        state["fails"] += 1
        tip.set("✗ " + why)
        entry.select_range(0, "end")
        entry.focus_set()
        if state["fails"] >= 5:
            state["fails"] = 0
            unlock_after(30)

    button.configure(command=submit)
    entry.bind("<Return>", submit)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.update_idletasks()
    # 放到屏幕中间
    width, height = root.winfo_reqwidth(), root.winfo_reqheight()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 3
    root.geometry("+%d+%d" % (max(0, x), max(0, y)))
    root.mainloop()
    return state["ok"]


def main():
    # 必须在建窗口之前声明，否则字会被 Windows 拉伸放大而发虚
    enable_dpi_awareness()
    # 打包后没有控制台，出错信息必须自己存下来，否则用户只会看到"闪了一下"
    sys.excepthook = _main_thread_excepthook
    threading.excepthook = _worker_thread_excepthook
    # 「给大家用」那一份要先过口令门；自己用的那份直接放行
    if not activation_gate():
        return
    App().mainloop()


if __name__ == "__main__":
    main()

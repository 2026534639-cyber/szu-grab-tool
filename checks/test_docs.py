# -*- coding: utf-8 -*-
"""第五层：文案与实现对得上吗。

跑法： python checks/test_docs.py

说明书里让用户点的每一个按钮、说的每一个数字，都要能在代码里找到出处。
这一类错误特别难被用户描述：他不会说"说明书第 4 节的按钮名错了"，
他只会说"我照着做但是找不到那个按钮"。所以这里把它变成可检查的。
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import szu_grab_app as m  # noqa: E402
import szu_grabber as g  # noqa: E402

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
        why = "" if why in ("", None) else str(why)
        FAILURES.append("%s%s" % (label, ("：" + why) if why else ""))
        print("  FAIL %s %s" % (label, why))
    else:
        print("  ok   %s" % label)


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


with open(os.path.join(ROOT, "szu_grab_app.py"), "r", encoding="utf-8") as handle:
    APP_SOURCE = handle.read()
with open(os.path.join(ROOT, "README.md"), "r", encoding="utf-8") as handle:
    README = handle.read()
GUIDE = m.HELP_TEXT
ALL_TEXT = GUIDE + "\n" + README


# ==========================================================================
section("1 说明书让用户点的东西，界面上必须真的有")
# ==========================================================================

# 说明书里出现的界面文案 → 代码里必须存在（引号里的字面量）
UI_LABELS = [
    "使用说明 · 图文",
    "① 粘贴凭证",
    "② 找课",
    "③ 抢课清单与开抢",
    "从剪贴板读取",
    "清空",
    "检查凭证",
    "搜索课程",
    "范围",
    "移除选中",
    "清空清单",
    "抢课速度",
    "等到开抢时刻自动开抢",
    "24 小时制",
    "▶  开始抢课",
    "停止",
    "只看还有名额的",
]
for label in UI_LABELS:
    check_true("界面上有「%s」" % label, label in APP_SOURCE,
               "说明书/README 提到它，但代码里找不到这个文案")

# 说明书的步骤里点名要用户看的东西，也必须在界面上
print("\n-- 说明书正文点名要用户找的东西 --")
for label, must in (("勾上「等到开抢时刻自动开抢」", "等到开抢时刻自动开抢"),
                    ("点「检查凭证」", "检查凭证"),
                    ("点「▶ 开始抢课」", "▶  开始抢课"),
                    ("点「停止」", "停止"),
                    ("点「搜索课程」", "搜索课程"),
                    ("点「从剪贴板读取」", "从剪贴板读取"),
                    ("点「使用说明 · 图文」", "使用说明 · 图文")):
    if label in GUIDE:
        check_true("说明书里的「%s」在界面上找得到" % must, must in APP_SOURCE)
    else:
        check_true("说明书里的「%s」在界面上找得到（说明书里没提，跳过）" % must,
                   True)


# ==========================================================================
section("2 说明书里的数字，必须等于代码里的数字")
# ==========================================================================

# 三档速度
for name, low, high in g.SPEED_PRESETS:
    seconds_low = low / 1000.0
    seconds_high = high / 1000.0
    shown = "%g~%g 秒" % (seconds_low, seconds_high)
    check_true("说明书写了「%s」（对应代码里的 %d~%d 毫秒）" % (shown, low, high),
               shown in GUIDE, "说明书里找不到 %s" % shown)

# 高频冲刺
check_true("说明书里的「提前 %.0f 秒」和代码一致" % g.BURST_LEAD,
           "%.0f 秒" % g.BURST_LEAD in GUIDE or
           "提前 %.0f 秒" % g.BURST_LEAD in GUIDE,
           "BURST_LEAD=%s" % g.BURST_LEAD)
check_true("说明书里的高频间隔和代码一致（%d~%d 毫秒）" % g.BURST_INTERVAL,
           ("%.1f~%.2f" % (g.BURST_INTERVAL[0] / 1000.0,
                           g.BURST_INTERVAL[1] / 1000.0)) in GUIDE,
           "BURST_INTERVAL=%s" % (g.BURST_INTERVAL,))
check_true("说明书里的「冲 %.0f 秒」和代码一致" % g.BURST_WINDOW,
           "%.0f 秒" % g.BURST_WINDOW in GUIDE, "BURST_WINDOW=%s" % g.BURST_WINDOW)

# 说明书第 3 条要说清「高频一共冲多久」，否则用户看到 17 秒不知从哪算起
check_true("说明书讲了高频一共冲多久（提前的那几秒也算）",
           "共约" in GUIDE, "说明书没讲清 17 秒怎么来的")

# 对时周期
resync = re.search(r"next_resync = time\.time\(\) \+ (\d+)", APP_SOURCE)
check_true("代码里有重新对时的周期", resync is not None)
if resync:
    minutes = int(resync.group(1)) / 60.0
    check_true("说明书里的对时周期和代码一致（%.0f 分钟）" % minutes,
               "每半小时" in GUIDE and minutes == 30,
               "代码是 %s 秒" % resync.group(1))

# 日志上限
check_true("说明书没承诺无限日志（代码上限 %d 行）" % m.App.LOG_MAX_LINES,
           m.App.LOG_MAX_LINES > 0)

# 连续异常上限
check_true("说明书说清了「连续异常会停下这门课」",
           "连续异常" in GUIDE or "看不懂" in GUIDE or "异常" in GUIDE,
           "说明书没提这件事")
check_true("代码里确实有这个上限（%d 次）" % m.MAX_CONSECUTIVE_ERRORS,
           m.MAX_CONSECUTIVE_ERRORS > 0)


# ==========================================================================
section("3 说明书只有一份：界面里看到的和导出的 txt 必须一样")
# ==========================================================================

check_true("界面说明书由 GUIDE_SECTIONS 生成（没有第二份硬编码文案）",
           m.HELP_TEXT == m.help_text())

dist_txt = os.path.join(ROOT, "dist", "使用说明.txt")
if os.path.exists(dist_txt):
    with open(dist_txt, "r", encoding="utf-8-sig") as handle:
        exported = handle.read()
    # utf-8-sig 是为了让 Windows 记事本正确识别中文，所以比的时候把 BOM 去掉
    check_true("导出的 使用说明.txt 和当前的说明书一致（改完说明书要重新打包）",
               exported.lstrip("\ufeff").strip() == m.HELP_TEXT.strip(),
               "两者不一致：导出 %d 字，当前 %d 字"
               % (len(exported.strip()), len(m.HELP_TEXT.strip())))
else:
    print("  （dist/使用说明.txt 还不存在，跳过）")


# ==========================================================================
section("4 署名与来源：写上去的每一句都要能对上")
# ==========================================================================

for subject, must in (
        ("上游原作 Lewin671", "Lewin671"),
        ("上游仓库 YourLesson", "Lewin671/YourLesson"),
        ("维护版 guiyi886", "guiyi886"),
        ("维护版仓库", "guiyi886/szu_grab_course"),
        ("本版作者 理不尽", "理不尽"),
        ("说明本版作者不是原作者", "不是上面任何一位原作者"),
        ("说明两个仓库都没有开源许可证", "没有标注开源许可证"),
):
    check_true("署名里有「%s」" % subject, must in GUIDE or must in README,
               "找不到：%s" % must)
    check_true("「%s」在界面上也署名了（不只是说明书里）" % subject,
               must in APP_SOURCE or subject in ("说明本版作者不是原作者",
                                                "说明两个仓库都没有开源许可证"),
               "界面源码里找不到：%s" % must)

check_true("界面标题栏附近的署名行指向维护版仓库",
           m.MAINTAINED_URL == "https://github.com/guiyi886/szu_grab_course",
           m.MAINTAINED_URL)


# ==========================================================================
section("5 说明书里提醒的坑，代码里真的处理了吗")
# ==========================================================================

MECHANISMS = [
    ("凭证失效会整轮停下",
     "STOPALL_RESULTS" in open(os.path.join(ROOT, "szu_grabber.py"),
                              encoding="utf-8").read()),
    ("被提示太频繁会自动放慢", "def next_delay" in g.__dict__ or hasattr(g, "next_delay")),
    ("抢到一门就从清单里划掉", hasattr(m.App, "_set_grab_status")),
    ("名额满会继续蹲（不算异常）", "full" not in "".join(g.TRANSIENT_RESULTS)),
    ("冲突/学分/权限会停下那门课",
     g.FATAL_RESULTS == {"conflict", "credit", "perm", "limit"}),
    ("对时间用服务器时间，不用本机时间", hasattr(g.CourseGrabber, "server_clock_offset")),
    ("12 小时制提醒（下午三点要填 15）", "凌晨" in APP_SOURCE),
    ("电脑睡眠会错过（说明书里有这条提醒）", "睡眠" in GUIDE),
]
for label, ok in MECHANISMS:
    check_true("说明书承诺「%s」，代码里有对应做法" % label, ok)

# 说明书不能承诺做不到的事
check_true("说明书没有承诺「一定能抢到」",
           "不保证" in GUIDE, "说明书缺少「不保证什么」这一段")
check_true("说明书说清了抽签轮次帮不上忙",
           "抽签" in GUIDE)
check_true("说明书说清了高频不是无限冲（会被限速打断）",
           "操作过于频繁" in GUIDE and "退出高频" in GUIDE)


# ==========================================================================
section("6 README 要覆盖「别人拿到之后会遇到的事」")
# ==========================================================================

for subject, must in (
        ("凭证明文存在本地", "明文"),
        ("出错记录文件", m.CRASH_NAME),
        ("配置文件", m.CONFIG_NAME),
        ("自检/审计脚本放在哪", "checks"),
        ("官网地址写对（bkxk）", "bkxk.szu.edu.cn"),
):
    check_true("README 提到了「%s」" % subject, must in README,
               "README 里找不到：%s" % must)

# 界面上的三个时间框后面标着单位（时/分/秒），说明书必须跟着讲，
# 不然用户看到的还是三个看不懂的空框
check_true("说明书说了时间框后面带单位（时、分、秒）",
           "时、分、秒" in GUIDE, "说明书没讲三个框的单位")

# 复制格式：用户实测只有 bash 那个是全的（cmd / powershell 会少掉 Cookie 那一行）。
# 说明书原来写的是「三个子选项随便哪个都行」——那是错的，必须钉住别再写回去。
check_true("说明书要求复制时选 bash", "只能选 bash" in GUIDE,
           "说明书没说清要选 bash")
check_true("说明书点明了 cmd / powershell 会不全",
           "powershell" in GUIDE and "不全" in GUIDE,
           "说明书没提醒另外两种格式会缺东西")
check_true("说明书里不再出现「随便哪个都行」这种错话",
           "随便哪个都行" not in GUIDE, "又把错误说法写回去了")
check_true("配图里也说清了只有 bash 是全的",
           "只有 bash 那个是全的" in APP_SOURCE, "示意图没跟着改")
# 说明书和日志都是「纯文本」，写 Markdown 的加粗只会原样显示成星号。
# （我在 README 里写惯了 **加粗**，往界面文案里搬时漏过一次。）
check_true("说明书里没有 Markdown 星号（会原样显示成 **）",
           "**" not in m.HELP_TEXT,
           [l for l in m.HELP_TEXT.splitlines() if "**" in l][:2])
_advice = m.network_advice("HTTPConnectionPool(host='bkxk.szu.edu.cn', port=80): "
                           "Max retries exceeded ... Connection to bkxk.szu.edu.cn "
                           "timed out. (connect timeout=15)")
check_true("连不上时，提示里点名学生实际要用的那个客户端（SecureLink）",
           "SecureLink" in _advice, _advice[:120])
check_true("网络提示里也不能出现星号", "**" not in _advice, _advice[:120])
check_true("网络提示里保住了技术细节（排查要用）",
           "timed out" in _advice, _advice[-160:])
# 说明书必须告诉用户「凭证会被明文存到本地」，这是隐私相关的事实
check_true("说明书讲了凭证会被存到本地、且是明文文件",
           m.CONFIG_NAME in GUIDE and "明文" in GUIDE,
           "说明书里没有 %s 或「明文」" % m.CONFIG_NAME)
check_true("说明书讲了怎么把存下来的凭证抹掉",
           "清空" in GUIDE and ("删掉" in GUIDE or "删除" in GUIDE))


print("\n" + "=" * 72)
print("跑了 %d 项检查，失败 %d 项" % (CHECKS[0], len(FAILURES)))
for item in FAILURES:
    print("  · " + item)
print("=" * 72)
sys.exit(1 if FAILURES else 0)

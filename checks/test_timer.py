# -*- coding: utf-8 -*-
"""「等到开抢时刻自动开抢」端到端实测（假接口，不联网）。

跑法： python checks/test_timer.py

为什么要这个测试：用户实测报「设好了 8:08，到点没开枪」。光看代码读不出
结论——必须让它真的挂着、真的到点、真的提交，才能证明定时有没有用。
所以这里用一个假 grabber（不联网）把整条路走一遍：

  1. 目标时刻设在几秒后 → 必须打「开始待机」；
  2. 到点前 lead 秒 → 必须打「★ 进入高频」，第一次提交要贴着那一刻；
  3. 高频持续 BURST_WINDOW 秒后 → 必须打「高频时段结束」；
  4. 目标时刻已经过去 → 必须打「填的开抢时刻已经过去」，不做高频；
  5. 待机期间点停止 → 立刻退出，且待机期间一次都不提交。

★ 日志要从界面控件（txt_log）里读，不要从 msg_q 采样：
  界面自己的轮询会先把队列读走，采样会漏行（这里踩过一次）。

会短暂创建窗口（隐藏），跑完自己关掉。
"""

import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import szu_grab_app as m  # noqa: E402

FULL = '{"code":"0","msg":"该课程超过课容量"}'

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
    why = "" if why in ("", None) else str(why)
    if not got:
        FAILURES.append("%s%s" % (label, ("：" + why) if why else ""))
        print("  FAIL %s %s" % (label, why))
    else:
        print("  ok   %s" % label)


class TimerGrabber:
    """假接口：不联网，记录每次提交的时刻。"""

    def __init__(self):
        self.calls = []
        self.add_param_style = "json"
        self.style_switched = False
        self.last_status = 200
        self.last_rtt = 0.05     # 假装直连，很快

    def server_clock_offset(self):
        return 0.0               # 假装本机与服务器一致

    def choose(self, class_id, ctype):
        self.calls.append(time.time())
        return FULL              # 名额满：继续蹲，流程不会自己结束


def run_case(target_offset, wait_seconds, stop_after=None):
    """挂上抢课并观察。

    target_offset：目标时刻＝现在 + 这么多秒（负数＝已经过去的时刻）
    wait_seconds：观察多久
    stop_after：跑到这么多秒就点停止（测「待机期间点停止」）
    """
    app = m.App()
    app.withdraw()
    app.grab_items = {"ID0": {"id": "202320242150294000101", "name": "甲课",
                              "teacher": "某", "type": "TYKC",
                              "status": "待抢"}}
    grabber = TimerGrabber()
    now = time.localtime()
    seconds = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec + target_offset
    start_sec = seconds % 86400

    worker = threading.Thread(
        target=app._grab_worker,
        args=(grabber, (200, 400), {"start": start_sec}, ["ID0"]),
        daemon=True)
    started_at = time.time()
    worker.start()
    limit = started_at + (stop_after if stop_after is not None else wait_seconds)
    while time.time() < limit:
        app.update()
        time.sleep(0.05)
    app.stop_flag.set()
    worker.join(timeout=5)
    app.update()
    time.sleep(0.3)
    app.update()
    text = app.txt_log.get("1.0", "end")
    app.destroy()
    return grabber, text, started_at


print("=" * 72)
print("1 目标时刻在 6 秒后：待机 → 到点前 lead 秒进高频 → 之后收手")
print("=" * 72)
grabber, text, t_start = run_case(6, 26)
print(text.strip()[:700])
print()
check_true("打了「开始待机」", "开始待机" in text)
check_true("打了「★ 进入高频」", "★ 进入高频" in text)
check_true("打了「高频时段结束，回到你选的速度」", "高频时段结束" in text)
check_true("确实提交过", len(grabber.calls) > 3, "%d 次" % len(grabber.calls))

if grabber.calls:
    first = grabber.calls[0] - t_start
    last = grabber.calls[-1] - t_start
    target_at = 6.0
    print("  第一次提交在开始后 %.2f 秒（目标约 %.0f 秒，提前量 %.0f 秒）"
          % (first, target_at, m.BURST_LEAD))
    check_true("第一次提交发生在待机之后（> 3 秒才动手）", first > 3.0,
               "%.2f 秒" % first)
    check_true("第一次提交不早于「目标 − 提前量 − 0.5 秒」（不白冲太久）",
               first >= target_at - m.BURST_LEAD - 0.5, "%.2f 秒" % first)
    check_true("提交一直持续到目标时刻之后（覆盖放名额那一瞬）",
               last > target_at, "最后 %.2f 秒" % last)
    gaps = [b - a for a, b in zip(grabber.calls, grabber.calls[1:])]
    high = [gap for gap in gaps if gap < 0.3]
    check_true("存在高频提交（间隔 < 0.3 秒至少 3 次）", len(high) >= 3,
               "高频 %d 次" % len(high))

print()
print("=" * 72)
print("2 目标时刻已经过去：不做高频，直接正常跑")
print("=" * 72)
grabber2, text2, _ = run_case(-90, 6)
print(text2.strip()[:400])
print()
check_true("提示了「填的开抢时刻已经过去」", "已经过去" in text2)
check_true("没有进入高频", "★ 进入高频" not in text2)
check_true("仍然在正常提交", len(grabber2.calls) > 1,
           "%d 次" % len(grabber2.calls))

print()
print("=" * 72)
print("3 待机期间点停止：立刻退出，且待机期间一次都不提交")
print("=" * 72)
grabber3, text3, _ = run_case(60, 30, stop_after=3)
print(text3.strip()[:400])
print()
check_true("打了「开始待机」", "开始待机" in text3)
check_true("没有进入高频（因为被停了）", "★ 进入高频" not in text3)
check_true("待机期间没有提交任何请求", len(grabber3.calls) == 0,
           "%d 次" % len(grabber3.calls))

print()
print("=" * 72)
print("跑了 %d 项检查，失败 %d 项" % (CHECKS[0], len(FAILURES)))
for item in FAILURES:
    print("  · " + item)
print("=" * 72)
sys.exit(1 if FAILURES else 0)

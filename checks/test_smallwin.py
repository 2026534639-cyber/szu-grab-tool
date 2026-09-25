# -*- coding: utf-8 -*-
"""小窗口适配的检查。

跑法： python checks/test_smallwin.py

用户报的是「适配下小窗口」——小屏笔记本（1366x768）上原来窗口比屏幕还高，
底部的「开始抢课」和日志被顶出屏幕，点不到。原因有两条，都在这测：

  1. 窗口尺寸的下限会反超屏幕可用高度（1366x768 + 150% 缩放时算出 840）；
  2. 左栏内容自然高度约 830px，1366x768 的可用高度只有 ~728 —— 光调尺寸治不了，
     左栏必须能滚。

所以这里对「五种屏幕 × 两种缩放」逐一检查三件事：
  · 窗口装得进屏幕可用区域（不超屏）；
  · 需要滚动时，左栏滚动范围要覆盖全部内容；
  · 滚到底之后，「开始抢课」按钮必须落在可视区域里（否则用户找不到它）。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import szu_grab_app as m  # noqa: E402

FAILURES = []
CHECKS = [0]


def check_true(label, got, why=""):
    CHECKS[0] += 1
    why = "" if why in ("", None) else str(why)
    if not got:
        FAILURES.append("%s%s" % (label, ("：" + why) if why else ""))
        print("  FAIL %s %s" % (label, why))
    else:
        print("  ok   %s" % label)


SCREENS = ((1920, 1080), (1600, 900), (1440, 900), (1366, 768), (1280, 720))
DPIS = (96, 144)          # 100% 和 150% 缩放


def probe(width, height, dpi):
    """假装屏幕是 width×height、缩放对应 dpi，返回三项检查结果。"""
    # 注意：不能只假造 winfo_screenwidth —— _work_area() 会去问 Windows
    # 要真实工作区，假屏幕会被它覆盖。所以这里直接把 _work_area 也假掉。
    m.App.winfo_fpixels = lambda self, value: dpi
    m.App._work_area = lambda self: (width, height)
    app = m.App()
    app.withdraw()
    try:
        app._apply_window_size()
        app.update()
        app.update_idletasks()

        win_w, win_h = (int(part) for part in
                        app.geometry().split("+")[0].split("x"))
        fits = win_w <= width and win_h <= height

        box = app.left_canvas.bbox("all")
        content_h = box[3] if box else 0
        view_h = app.left_canvas.winfo_height()
        need_scroll = content_h > view_h

        # 滚到底，看「开始抢课」在不在可视区里
        app.left_canvas.yview_moveto(1.0)
        app.update_idletasks()
        top = app.left_canvas.canvasy(0)
        button_bottom = (app.btn_start.winfo_rooty()
                         - app.left_canvas.winfo_rooty()
                         + app.btn_start.winfo_height())
        reachable = (not need_scroll) or (top <= button_bottom <= top + view_h)
        scale = app.scale
    finally:
        app.destroy()
    return fits, need_scroll, reachable, (win_w, win_h), scale


print("=" * 72)
print("窗口尺寸与左栏可达性")
print("=" * 72)
for width, height in SCREENS:
    for dpi in DPIS:
        fits, need_scroll, reachable, size, scale = probe(width, height, dpi)
        label = ("%dx%d 缩放%.0f%%（窗口 %dx%d，左栏%s）"
                 % (width, height, scale * 100, size[0], size[1],
                    "需要滚动" if need_scroll else "一屏放得下"))
        check_true("不超屏：" + label, fits)
        check_true("滚到底能看到「开始抢课」：" + label, reachable)


print()
print("=" * 72)
print("细节：滚动条只在装不下时出现")
print("=" * 72)
m.App.winfo_fpixels = lambda self, value: 96
m.App._work_area = lambda self: (1920, 1080)
app = m.App()
app.withdraw()
app.update()
app._refresh_left_bar()
app.update_idletasks()
check_true("内容装不下时显示滚动条",
           app.left_canvas.bbox("all")[3] > app.left_canvas.winfo_height())
check_true("按状态标记，滚动条是摆出来的", bool(app._left_bar_shown))
check_true("滚轮能滚动左栏（绑过事件）",
           bool(app.left_canvas.bind("<MouseWheel>") is not None
                or app.left_canvas.yview() is not None))
# 关窗不应留下 after 任务（否则 Tk 会刷 invalid command name）
jobs = [getattr(app, "_poll_job", None), getattr(app, "_left_bar_job", None)]
check_true("after 任务句柄被托管（关窗时好取消）",
           all(hasattr(app, name) for name in
               ("_poll_job", "_left_bar_job", "_auto_parse_job")))
app.destroy()

print()
print("小的窗口也应当能开（1024x768 这种老机器）")
fits, _, reachable, size, _ = probe(1024, 768, 96)
check_true("1024x768 不超屏（窗口 %dx%d）" % size, fits)
check_true("1024x768 滚到底能看到「开始抢课」", reachable)

print()
print("=" * 72)
print("跑了 %d 项检查，失败 %d 项" % (CHECKS[0], len(FAILURES)))
for item in FAILURES:
    print("  · " + item)
print("=" * 72)
sys.exit(1 if FAILURES else 0)

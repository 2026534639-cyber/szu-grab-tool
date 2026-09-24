# -*- coding: utf-8 -*-
"""验收两份 exe 的差别：一份要口令，一份不要。

跑法： python checks/probe_two_builds.py

只读窗口标题，不模拟任何输入、不动鼠标键盘。
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import shoot_exe as S  # noqa: E402

FAILURES = []


def windows_now():
    return [title for _, title in S.list_windows()]


def wait_for(predicate, seconds=45):
    deadline = time.time() + seconds
    while time.time() < deadline:
        titles = windows_now()
        hit = predicate(titles)
        if hit:
            return hit, titles
        time.sleep(0.6)
    return None, windows_now()


def probe(exe):
    """启动一个 exe，看它先出现哪个窗口。返回 (有没有口令门, 有没有主窗口)。"""
    subprocess.run(["taskkill", "/F", "/IM", os.path.basename(exe)],
                   capture_output=True)
    time.sleep(1.0)
    process = subprocess.Popen([exe], cwd=os.path.dirname(exe))
    try:
        gate, titles = wait_for(lambda ts: [t for t in ts if "口令" in t], 40)
        main, titles2 = wait_for(
            lambda ts: [t for t in ts if t.strip() == "深大抢课助手"], 8)
        print("      看到的窗口标题:", sorted(set(titles + titles2))[:6])
        return bool(gate), bool(main)
    finally:
        S.kill_tree(process)
        time.sleep(0.5)


def check(label, got, want):
    if got != want:
        FAILURES.append("%s：得到 %r，期望 %r" % (label, got, want))
        print("  FAIL %s：得到 %r，期望 %r" % (label, got, want))
    else:
        print("  ok   %s → %r" % (label, got))


dist = os.path.join(os.path.dirname(HERE), "dist")
public = os.path.join(dist, "深大抢课助手.exe")
personal = os.path.join(dist, "深大抢课助手_自己用.exe")

print("=== 「给大家用」的那份（应该先要口令）===")
gate, main = probe(public)
check("出现了口令门", gate, True)
check("口令没过之前，不开主窗口", main, False)

print()
print("=== 「自己用」的那份（应该直接进主界面）===")
gate2, main2 = probe(personal)
check("没有口令门", gate2, False)
check("直接开了主窗口", main2, True)

print()
print("=" * 72)
print("失败 %d 项" % len(FAILURES))
for item in FAILURES:
    print("  · " + item)
print("=" * 72)
sys.exit(1 if FAILURES else 0)

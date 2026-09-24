# -*- coding: utf-8 -*-
"""验收打包版「还能不能用」：不空转 + 窗口能处理消息。

用法： python checks/probe_alive.py <exe路径> [观察秒数]

两个指标，都是环境无关的（不需要模拟鼠标、不需要截图、不靠窗口状态）：

  1. **空闲 CPU 占用**。界面"卡死"的本质是主线程被无穷无尽的回调占满，
     这时进程会一直烧 CPU；正常空闲程序应该接近 0。实测：出问题的那版持续
     100%，修好后 0~1%。
  2. **窗口能不能处理消息**：`SendMessageTimeout(WM_NULL, SMTO_ABORTIFHUNG)`
     就是问"这条消息你的消息循环多久能处理掉"。实测修好后是 0 毫秒。

## 两个走过弯路的地方，写在这里免得以后再踩

- **`IsHungAppWindow` 在非交互会话里不能用**：它对正常窗口也报"未响应"
  （新旧两版测出来一模一样，从 0.0 秒起就是"是"）。它是按"多久没收到输入"
  判断的，而这个会话压根没有输入。
- **`--onefile` 的 exe 会分裂成引导进程 + 真正跑界面的子进程**，
  `Popen` 拿到的是**引导**那个，测它的 CPU 永远是 0，会得出"程序很乖"的
  错误结论。要用 `GetWindowThreadProcessId(窗口句柄)` 问出真正那个进程。
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

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class FILETIME(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


def pid_of_window(hwnd):
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def cpu_seconds(pid):
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        creation, exit_, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if not kernel32.GetProcessTimes(handle, ctypes.byref(creation),
                                       ctypes.byref(exit_),
                                       ctypes.byref(kernel), ctypes.byref(user)):
            return None
        k = (kernel.high << 32) | kernel.low
        u = (user.high << 32) | user.low
        return (k + u) / 1e7
    finally:
        kernel32.CloseHandle(handle)


def responds(hwnd, timeout_ms=2000):
    result = ctypes.c_ulong(0)
    return bool(user32.SendMessageTimeoutW(hwnd, WM_NULL, 0, 0,
                                           SMTO_ABORTIFHUNG, timeout_ms,
                                           ctypes.byref(result)))


def main():
    exe = sys.argv[1]
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0

    # 先把同名残留清干净：不然 find_window 找到的可能是上一个没死透的窗口，
    # 测出来的是那个僵尸的数字（我第一次就这么被骗过，两次测到同一个 PID）。
    subprocess.run(["taskkill", "/F", "/IM", os.path.basename(exe)],
                   capture_output=True)
    time.sleep(1.0)

    print("exe:", exe, flush=True)
    process = subprocess.Popen([exe], cwd=os.path.dirname(exe))
    try:
        hwnd, title = S.wait_for_window("深大抢课助手", 45)
        if not hwnd:
            print("FAIL 45 秒内没找到主窗口", flush=True)
            return 2
        windows = [t for _, t in S.list_windows() if "深大抢课助手" in t]
        if len(windows) > 1:
            print("FAIL 同时存在 %d 个窗口，测不准" % len(windows), flush=True)
            return 2
        pid = pid_of_window(hwnd)
        print("窗口 %r 属于进程 PID %d（Popen 拿到的是引导进程 %s）"
              % (title, pid, process.pid), flush=True)
        # 等它把启动那段忙完再开始采样：onefile 要解包、起界面、还会自动检查一次
        # 凭证，头一两秒 CPU 会冲到几十个百分点（实测冷启动 62%），那不是空转。
        # 等太短会把启动峰值当成"程序在空转"，误报一次。
        time.sleep(8.0)

        print("\n-- 1 空闲 CPU --", flush=True)
        before = cpu_seconds(pid)
        t0 = time.time()
        samples = []
        while time.time() - t0 < seconds:
            time.sleep(3.0)
            now = cpu_seconds(pid)
            if before is None or now is None:
                print("  （拿不到 CPU 时间）", flush=True)
                break
            used = (now - before) / (time.time() - t0)
            samples.append(used)
            print("  累计 %.2fs CPU，近段占用约 %.0f%%" % (now, used * 100), flush=True)
        peak = max(samples) if samples else 0.0

        print("\n-- 2 窗口能不能处理消息 --", flush=True)
        answers = []
        for index in range(5):
            started = time.time()
            ok = responds(hwnd)
            answers.append(ok)
            print("  第 %d 次：%s（%.0f ms）"
                  % (index + 1, "响应" if ok else "没响应", (time.time() - started) * 1000),
                  flush=True)
            time.sleep(0.8)

        print()
        if peak > 0.5:
            print("FAIL 空闲时 CPU 占用峰值 %.0f%%——程序在空转，"
                  "用户会看到界面越来越卡直到点不动" % (peak * 100), flush=True)
            return 1
        if not all(answers):
            print("FAIL 有 %d 次消息没被处理——窗口不响应"
                  % (len(answers) - sum(answers)), flush=True)
            return 1
        print("PASS 空闲 CPU 峰值 %.1f%%，消息响应 %d/%d"
              % (peak * 100, sum(answers), len(answers)), flush=True)
        return 0
    finally:
        S.kill_tree(process)


if __name__ == "__main__":
    sys.exit(main())

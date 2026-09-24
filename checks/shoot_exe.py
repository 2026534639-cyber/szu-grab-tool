# -*- coding: utf-8 -*-
"""验收打包版：把 exe 放到「中文 + 空格」的目录里单独跑，抓图存下来。

用法： python checks/shoot_exe.py <exe路径> <输出目录>

为什么要这么绕：打包版和源码版是两个世界——资源路径（_MEIPASS）、
工作目录（exe 在哪）、有没有控制台都不一样。只有在真实 exe 上跑一遍才算验过。
抓图不是为了好看，是为了确认界面上的字没被截断、四张示意图真的画出来了。

两个坑写在前面：
  · GetWindowRect 必须是结构体参数，用四个 out int 拿到的是错的值
  · 自己这个脚本不声明 DPI 感知的话，坐标会被 Windows 缩放，
    SetCursorPos 点下去会偏——窗口矩形和光标坐标必须都在同一套坐标里
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import subprocess
import sys
import time

from PIL import Image

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def list_windows():
    """所有可见窗口的 (hwnd, 标题)。"""
    out = []

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                out.append((hwnd, buffer.value))
        return True

    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(proc(callback), 0)
    return out


def find_window(title_part):
    for hwnd, title in list_windows():
        if title_part in title:
            return hwnd, title
    return None, None


def wait_for_window(title_part, seconds):
    """等窗口出现。每轮都把见过的标题打出来，卡住时一眼能看出为什么。"""
    deadline = time.time() + seconds
    seen = set()
    while time.time() < deadline:
        windows = list_windows()
        for hwnd, title in windows:
            if title_part in title:
                return hwnd, title
        new = {title for _, title in windows} - seen
        if new:
            seen |= new
            print("  当前可见窗口（新）：%s" % sorted(new)[:6], flush=True)
        time.sleep(0.8)
    return None, None


def shoot(hwnd, path):
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    # 用屏幕 DC 做 BitBlt。**不要用 PrintWindow**：Tk 的窗口不处理 WM_PRINT，
    # PrintWindow 在它上面会一直不返回（实测挂死到超时，半小时白等）。
    # 代价是要求窗口在屏幕上可见、不被挡住，所以先把它切到前台。
    # 也**不要**加 RedrawWindow(RDW_UPDATENOW)——它是同步等目标窗口绘制，
    # 在 Tk 上同样会挂死（实测），而且对"屏幕帧是旧的"这个现象也没帮助。
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    screen_dc = user32.GetDC(0)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)
    gdi32.BitBlt(memory_dc, 0, 0, width, height, screen_dc,
                 rect.left, rect.top, SRCCOPY)

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 32

    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    image = image.convert("RGB")
    image.save(path)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(0, screen_dc)

    colors = image.getcolors(maxcolors=1000000)
    return (width, height, len(colors) if colors else -1)


def human_recently_active(seconds=20.0):
    """最近这段时间里，真实用户有没有动过键盘鼠标？

    这个函数存在的唯一理由是**这条事故教训**（2026-09-21）：本脚本原来有一套
    「自动点开使用说明」的循环，会 SetCursorPos 挪动**真实光标**、并在屏幕上
    轮流点击 90 个位置。我在用户正用电脑的时候跑了它，用户那边就是
    「鼠标完全不受控制」。所以：

      · 本文件**不再包含任何模拟输入**（SetCursorPos / mouse_event / 按键）；
      · 这个函数留作闸门——以后谁要加回模拟输入，必须先过它（返回 True
        表示人正在用电脑，绝对不许动鼠标）。
    """
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return True                      # 问不出来就当成"人在用"，宁可不做
    elapsed_ms = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms < seconds * 1000


def kill_tree(process):
    """连子进程一起结束。

    PyInstaller 的 --onefile 会跑出**两个**进程：引导程序解包后启动真正的程序。
    process.terminate() 只干掉引导那个，真正的窗口进程会一直留着——
    验收脚本跑几轮就会攒一堆常驻进程，还会占着 exe 所在的目录删不掉。
    所以用 taskkill /T（结束整棵进程树）。"""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)],
                       capture_output=True, timeout=20)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass



def main():
    if human_recently_active():
        print("跳过：检测到最近有人在使用电脑。")
        print("      抓图会置顶窗口抢走你的前台焦点，人在用时不能做。")
        return {"main": None, "notes": ["有人在用电脑，已跳过"]}, None
    exe, out_dir = sys.argv[1], sys.argv[2]
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    print("exe:", exe, flush=True)
    process = subprocess.Popen([exe], cwd=os.path.dirname(exe))
    results = {"main": None, "help": None, "helpers": [], "notes": []}
    try:
        print("等主窗口出现…", flush=True)
        hwnd, title = wait_for_window("深大抢课助手", 45)
        if not hwnd:
            results["notes"].append("45 秒内没看到主窗口")
            print("FAIL 45 秒内没看到主窗口", flush=True)
            return results, process
        print("看到窗口:", title, flush=True)

        time.sleep(3.0)                     # 等它把界面画完
        size = shoot(hwnd, os.path.join(out_dir, "01_主窗口.png"))
        results["main"] = size
        print("主窗口抓图:", size, flush=True)

        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        user32.SetForegroundWindow(hwnd)
        user32.ShowWindow(hwnd, 9)          # SW_RESTORE，防止最小化
        time.sleep(0.8)
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        results["rect"] = (rect.left, rect.top, rect.right, rect.bottom)

        # 使用说明窗口**不在这里点开**：那需要模拟鼠标输入，会抢走用户的鼠标
        # （2026-09-21 事故，见上面的 human_recently_active）。
        # 它的内容改由 checks/shoot_help.py 直接调用 show_help() 来验证——
        # 走的是同一份代码，只是绕开了"点一下"这个动作；示意图还会逐张做
        # 程序化核对（元素数量、有没有画到画布外面、关键文字在不在）。
        results["notes"].append("使用说明窗口不走模拟点击，改由 shoot_help.py 直接验证")
        return results, process
    finally:
        kill_tree(process)


if __name__ == "__main__":
    info, proc = main()
    print("结果:", info, flush=True)
    time.sleep(1.0)
    sys.exit(0 if info.get("main") else 1)

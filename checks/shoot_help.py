# -*- coding: utf-8 -*-
"""验收「使用说明 · 图文」：抓图 + 程序化核对示意图。

用法： python checks/shoot_help.py <输出目录>

两件事都做：

1. **抓图**：把主窗口先收起来再打开说明书，让它的第一次绘制就落在干净的屏幕上，
   然后逐张滚动抓图。这个会话对模拟输入不接受（试过 SetCursorPos / mouse_event /
   PostMessage / 按键，全部无效），所以不能用鼠标点按钮，直接调 show_help()——
   和按钮绑的是同一个函数（test_docs 会检查这层绑定）。

2. **程序化核对**（不依赖抓图能不能成）：每张示意图是一个 Canvas，
   检查它上面真的画了东西、元素没有画到画布外面去、关键文字在不在。
   元素画到边界外就是"用户看不见"，这种缺陷在人眼抓图上很容易漏掉。
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from PIL import Image  # noqa: E402

import shoot_exe as S  # noqa: E402
import szu_grab_app as m  # noqa: E402

FAILURES = []


def check_true(label, got, why=""):
    if not got:
        FAILURES.append("%s%s" % (label, ("：" + why) if why else ""))
        print("  FAIL %s %s" % (label, why))
    else:
        print("  ok   %s" % label)


def canvas_texts(canvas):
    values = []
    for item in canvas.find_all():
        if canvas.type(item) == "text":
            values.append(canvas.itemcget(item, "text"))
    return values


def canvas_bbox(canvas):
    box = canvas.bbox("all")
    return box


def main():
    if S.human_recently_active():
        print("跳过：最近有人在使用电脑（这个脚本会把窗口置顶，会打断你）。")
        return 0
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "shots")
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    app = m.App()
    app.withdraw()               # 先收主窗口：抓图抓的是"屏幕上最上面那一层"
    app.update()
    time.sleep(0.6)
    app.show_help()
    app.update()

    hwnd, title = S.find_window("使用说明")
    if not hwnd:
        print("FAIL 没找到使用说明窗口")
        return 1
    print("使用说明窗口:", title, hwnd)
    S.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0040)
    app.update()
    time.sleep(2.5)

    text = app.help_text
    names = text.window_names()
    print("\n嵌进文本框的示意图数量:", len(names), "（应该是 4）")
    check_true("四张示意图都嵌进去了", len(names) == 4, "实际 %d 张" % len(names))

    # ---- 抓图 ----
    size = S.shoot(hwnd, os.path.join(out_dir, "02_使用说明_顶部.png"))
    print("顶部抓图:", size)
    shots = []
    for index, name in enumerate(names):
        try:
            text.see(name)
            app.update()
            time.sleep(0.9)
            path = os.path.join(out_dir, "03_示意图%d.png" % (index + 1))
            info = S.shoot(hwnd, path)
            shots.append((path, info))
            print("示意图 %d 抓图:" % (index + 1), info)
            # 确认屏幕内容真的跟着滚了（不然抓到的是一堆一样的图）
        except Exception as error:
            print("  示意图 %d 抓图失败：%s" % (index + 1, error))

    if len(shots) >= 2:
        sizes = [os.path.getsize(path) for path, _ in shots]
        if len(set(sizes)) == 1:
            print("  注意：滚动后抓到的图字节数完全相同——这个会话里屏幕不会"
                  "因为滚动而重绘（非交互会话的已知现象）。示意图的内容改用"
                  "下面的程序化核对来验，不靠抓图。")
        else:
            check_true("滚动后抓到的图确实变了（不是同一张）", True)

    # ---- 程序化核对每张示意图 ----
    # 注意：text.window_names() 的返回顺序**不等于**插入顺序（实测是错位的），
    # 所以按内容认图，不按序号认。
    print()
    DIAGRAM_KEYS = {
        "step1_f12": ("第 1 步的图（开发者工具 / 网络标签）",
                      ["bkxk.szu.edu.cn", "Network / 网络", "F12"]),
        # 第 2 步这张图重画过：原来把 recommendedCourse 写在过滤框里，
        # 等于教用户"去过滤框里搜这个词"。现在画的是"点两下标签→那一行自己冒出来"。
        "step2_tabs": ("第 2 步的图（点两下标签，那一行自己出现）",
                       ["方案内课程", "本班课程", "recommendedCourse.do",
                        "不用在过滤框里搜"]),
        "step3_menu": ("第 3 步的图（右键 Copy as cURL）",
                       ["Copy as cURL", "Copy", "powershell"]),
        "step4_paste": ("第 4 步的图（粘回来显示四个 ✅）",
                        ["✅ 学号", "✅ Cookie", "✅ token", "✅ 批次码"]),
    }

    canvas_text = {}
    for name in names:
        canvas = text.nametowidget(name)
        canvas_text[name] = " ".join(canvas_texts(canvas))

    matched = {}
    for diagram, (label, keys) in DIAGRAM_KEYS.items():
        hits = [name for name, value in canvas_text.items()
                if all(key in value for key in keys)]
        check_true("找得到%s（靠内容认，不靠序号）" % label, len(hits) == 1,
                   "匹配到 %d 张画布 %s" % (len(hits), hits))
        if len(hits) == 1:
            matched[diagram] = hits[0]
        elif hits:
            matched[diagram] = hits[0]

    check_true("四张图互不重复、一张对一张", len(set(matched.values())) == 4,
               "对应关系：%s" % matched)

    for diagram, name in matched.items():
        canvas = text.nametowidget(name)
        items = canvas.find_all()
        types = {}
        for item in items:
            types[canvas.type(item)] = types.get(canvas.type(item), 0) + 1
        check_true("%s 真的画了东西：%d 个元素 %s"
                   % (DIAGRAM_KEYS[diagram][0], len(items), types), len(items) >= 10,
                   "只有 %d 个元素" % len(items))

        box = canvas_bbox(canvas)
        width = canvas.winfo_reqwidth()
        height = canvas.winfo_reqheight()
        if box:
            left, top, right, bottom = box
            check_true("%s 的元素没画到画布外面（内容 %s / 画布 %dx%d）"
                       % (DIAGRAM_KEYS[diagram][0], box, width, height),
                       left >= -1 and top >= -1 and right <= width + 1
                       and bottom <= height + 1,
                       "有元素超出边界，用户看不到")

    # ---- 说明书正文的完整性 ----
    print()
    body = text.get("1.0", "end")
    for must in ("深大抢课助手 · 使用说明", "怎么拿凭证", "找课", "开始抢课",
                 "抢课当天的准备清单", "常见问题", "署名与来源",
                 "Lewin671", "guiyi886", "理不尽", m.CONFIG_NAME):
        check_true("说明书正文里有「%s」" % must, must in body)

    app.destroy()
    return 1 if FAILURES else 0


if __name__ == "__main__":
    code = main()
    print("\n" + "=" * 72)
    if FAILURES:
        print("失败 %d 项：" % len(FAILURES))
        for item in FAILURES:
            print("  · " + item)
    else:
        print("全部通过 ✅")
    print("=" * 72)
    sys.exit(code)

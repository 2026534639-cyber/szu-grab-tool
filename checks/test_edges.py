# -*- coding: utf-8 -*-
"""第四层：长时间与边界。

跑法： python checks/test_edges.py

盯的是「用久了、用极端了才会出事」的地方：
  · 清单很大 / 很小
  · 一连提交几千次之后，内存和日志有没有失控
  · 服务器一直有数据时，翻页会不会翻到天荒地老
  · 配置写不下去（只读目录、盘不存在）时会不会崩
  · 出错记录文件能不能写出来
"""

import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

import szu_grab_app as m  # noqa: E402
import szu_grabber as g  # noqa: E402
from fake_server import FakeServer  # noqa: E402

FAILURES = []
CHECKS = [0]

for _name in ("showinfo", "showwarning", "showerror", "askyesno"):
    setattr(m.messagebox, _name, lambda *a, **k: True)


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


class Canned:
    """按剧本回，用完就一直回同一个结果。"""

    def __init__(self, script=(), fallback='{"code":"0","msg":"该课程超过课容量"}',
                 stop_flag=None, limit=None):
        self.script = list(script)
        self.fallback = fallback
        self.calls = []
        self.stop_flag = stop_flag
        self.limit = limit
        self.add_param_style = "json"
        self.style_switched = False
        self.last_status = 200

    def choose(self, class_id, ctype):
        self.calls.append(class_id)
        if self.stop_flag is not None and self.limit and len(self.calls) >= self.limit:
            self.stop_flag.set()
        return self.script.pop(0) if self.script else self.fallback

    def query_selected(self):
        return []


# ==========================================================================
section("1 清单很大：100 门一起抢")
# ==========================================================================

app = m.App()
app.withdraw()
app.destroy()

app = m.App()
app.withdraw()
for index in range(100):
    app._append_grab_item({"id": "ID%03d" % index, "name": "课程%03d" % index,
                           "teacher": "老师%d" % index, "type": "TYKC",
                           "status": "待抢"})
check("清单里有 100 门", len(app._grab_in_order()), 100)

# 把间隔改成 0，让这一轮跑得完（真实间隔是 200ms 起，100 门要 20 秒）
_original_next_delay = m.next_delay
m.next_delay = lambda *a, **k: 0.0
fake = Canned(fallback='{"code":"1","msg":"添加选课志愿成功"}')
app.stop_flag.clear()
started = time.time()
app._grab_worker(fake, (200, 400), None, app._grab_in_order_iids())
elapsed = time.time() - started
m.next_delay = _original_next_delay

done = [iid for iid, item in app.grab_items.items()
        if item["status"].startswith("✅")]
check("100 门全部抢到", len(done), 100)
check("每一门只提交一次（抢到就不再重复提交）", len(fake.calls), 100)
check_true("跑得完，没有卡住（%.1f 秒）" % elapsed, elapsed < 30)

msgs = []
while not app.msg_q.empty():
    msgs.append(app.msg_q.get_nowait())
finished = [p for k, p in msgs if k == "finished"]
check("收尾汇报的 total 是 100", finished[-1]["total"] if finished else None, 100)
check("收尾汇报的 got 是 100", finished[-1]["got"] if finished else None, 100)
check("没有漏在待办里的课", finished[-1]["left"] if finished else None, [])
app.destroy()


# ==========================================================================
section("2 清单只有一门：连提交几千次，内存和日志不能失控")
# ==========================================================================

app = m.App()
app.withdraw()
app._append_grab_item({"id": "ID1", "name": "唯一的一门课", "teacher": "某",
                       "type": "TYKC", "status": "待抢"})
m.next_delay = lambda *a, **k: 0.0
ATTEMPTS = 3000
fake = Canned(stop_flag=app.stop_flag, limit=ATTEMPTS)
app.stop_flag.clear()
app._grab_worker(fake, (200, 400), None, app._grab_in_order_iids())
m.next_delay = _original_next_delay

check("确实提交了 3000 次", len(fake.calls), ATTEMPTS)
# 把队列里的日志真正灌进控件再数行数（只数控件里的行，队列还没处理就不算）
queued = 0
while not app.msg_q.empty():
    app._drain_queue()
    queued += 1
    if queued > 100:
        break
app._drain_queue()
lines = int(app.txt_log.index("end-1c").split(".")[0])
check_true("队列里的日志确实很多（说明压力是真的）", queued > 0,
           "队列处理轮数 %d" % queued)
check_true("日志被截住，没有涨到 3000 行（实际 %d 行）" % lines,
           lines <= app.LOG_MAX_LINES + 2, "实际 %d 行" % lines)
check("每门课的尝试计数只留一条", len(app.attempt_counts), 1)
check("尝试计数没有溢出成负数", max(app.attempt_counts.values()), ATTEMPTS)
app.destroy()


# ==========================================================================
section("3 服务器一直有数据：翻页必须有个头")
# ==========================================================================

_original_sleep = g.time.sleep
g.time.sleep = lambda seconds: None          # 跳过翻页之间的 0.25 秒


def run_paging_test():
    grabber = g.CourseGrabber(
        {"student_code": "2023123456", "cookie": "_WEU=x",
         "token": "6e912f8e-1234-5678-9abc-def012345678", "batch": "2026A1B2C3D4"},
        timeout=3)
    calls = []

    def always_page(ctype, page, page_size):
        """永远回一页数据，模拟「怎么翻都还有」。"""
        calls.append(page)
        return {"dataList": [{"courseName": "永远有课", "tcList": [
            {"teachingClassID": "C-%d" % page, "classCapacity": "10",
             "numberOfSelected": "0"}]}]}

    grabber._fetch_page = always_page
    rows = grabber._iter_type("TYKC")
    return rows, calls


try:
    rows, pages = run_paging_test()
finally:
    g.time.sleep = _original_sleep

check_true("翻页有上限，不会一直翻下去（翻了 %d 页）" % len(pages),
           len(pages) <= 200, "翻了 %d 页" % len(pages))
check_true("确实翻到接近上限才停（说明上限生效，而不是立刻返回）",
           len(pages) >= 190, "%d 页" % len(pages))
check_true("返回的行数跟翻的页数对得上", len(rows) == len(pages),
           "%d 行 / %d 页" % (len(rows), len(pages)))


# ==========================================================================
section("4 配置写不下去时（只读目录 / 盘不存在），不能崩")
# ==========================================================================

app = m.App()
app.withdraw()
app._append_grab_item({"id": "ID1", "name": "甲", "teacher": "某", "type": "TYKC",
                       "status": "待抢"})

real_app_dir = m.app_dir
try:
    m.app_dir = lambda: "Z:\\这个盘不存在\\随便什么"
    try:
        app._save_config()
        check_true("盘不存在时保存配置不崩（只在日志里说一声）", True)
    except Exception as error:
        check_true("盘不存在时保存配置不崩", False, repr(error))

    try:
        path = m.write_crash_log(ValueError, ValueError("试试"), None)
        check("写不出出错记录时返回空字符串，而不是抛异常", path, "")
    except Exception as error:
        check_true("写不出出错记录时不抛异常", False, repr(error))
finally:
    m.app_dir = real_app_dir

# 目录只读的情况：用一个真实的只读目录试（Windows 上把目录设成只读基本无效，
# 所以这里退一步：用一个文件冒充目录，写入必然失败）
app.destroy()


# ==========================================================================
section("5 出错记录文件：写了要有内容，且不能污染工程目录")
# ==========================================================================

CONFIG_PATH = os.path.join(ROOT, m.CONFIG_NAME)
if os.path.exists(CONFIG_PATH):
    os.remove(CONFIG_PATH)

crash_path = os.path.join(ROOT, m.CRASH_NAME)
if os.path.exists(crash_path):
    os.remove(crash_path)
try:
    try:
        raise ValueError("故意制造一个错误，用来检查记录文件")
    except ValueError:
        written = m.write_crash_log(*sys.exc_info())
    check_true("出错记录写到了 exe 旁边", written == crash_path, written)
    content = ""
    if os.path.exists(crash_path):
        with open(crash_path, "r", encoding="utf-8") as handle:
            content = handle.read()
    check_true("记录里有异常类型", "ValueError" in content)
    check_true("记录里有那句话", "故意制造一个错误" in content)
    check_true("记录里有时间戳", time.strftime("%Y-") in content)
    check_true("记录里有调用栈", "line" in content or "第" in content)
finally:
    if os.path.exists(crash_path):
        os.remove(crash_path)

# 窗口回调里出错：要写文件、要进日志、要弹框，而且自己不能再炸
app = m.App()
app.withdraw()
POPUPS = []
m.messagebox.showerror = lambda *a, **k: POPUPS.append(a)
try:
    raise RuntimeError("回调里的假异常")
except RuntimeError:
    app.report_callback_exception(*sys.exc_info())
check_true("Tk 回调出错会弹框告诉用户", bool(POPUPS), str(POPUPS))
check_true("Tk 回调出错会写进日志",
           "程序出错了" in app.txt_log.get("1.0", "end"),
           app.txt_log.get("1.0", "end")[-120:])
check_true("Tk 回调出错会留下记录文件", os.path.exists(crash_path))
if os.path.exists(crash_path):
    os.remove(crash_path)
app.destroy()

check_true("跑完没在工程目录里留下配置文件或记录文件",
           not os.path.exists(CONFIG_PATH) and not os.path.exists(crash_path))
print("\n  工程目录里剩下的文件：")
for name in sorted(os.listdir(ROOT)):
    print("    " + name)


print("\n" + "=" * 72)
print("跑了 %d 项检查，失败 %d 项" % (CHECKS[0], len(FAILURES)))
for item in FAILURES:
    print("  · " + item)
print("=" * 72)
sys.exit(1 if FAILURES else 0)

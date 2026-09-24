# -*- coding: utf-8 -*-
"""卡死探测器：定位"界面没反应"到底堵在哪儿。

用法： python checks/probe_freeze.py

做法：
  1. 装一个心跳：主线程每 50ms 记一次时间戳。两次心跳间隔超过 1 秒
     = 界面在这段时间里是死的（Tk 只在主线程处理事件，主线程一堵，窗口就不响应）。
  2. 再装一个看门狗线程：发现主线程超过 2 秒没心跳，就把**主线程当前的调用栈**
     打出来——直接指出卡在哪一行，不用猜。
  3. 按用户的真实操作顺序驱动一遍（粘凭证 → 自动检查 → 搜索 → 加清单 → 开抢 → 停止），
     每步都报告这一步造成的最大卡顿。

关键点：中途用假的 HTTP 服务器或"黑洞地址"来控制网络快慢，这样能分辨
「卡是因为在等网络」还是「卡是因为主线程自己在忙」。
"""

import os
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

os.environ["NO_PROXY"] = "127.0.0.1,localhost"
os.environ["no_proxy"] = "127.0.0.1,localhost"

import szu_grab_app as m  # noqa: E402
import szu_grabber as g  # noqa: E402
from fake_server import FakeServer  # noqa: E402

REAL_GRABBER = m.CourseGrabber
MAIN_ID = threading.get_ident()

# 弹窗：不真弹（真弹会等人点，测不下去），只记账
POPUPS = []
for _name in ("showinfo", "showwarning", "showerror", "askyesno"):
    def _make(name):
        def _fake(*args, **kwargs):
            POPUPS.append((name, args[0] if args else ""))
            return True
        return _fake
    setattr(m.messagebox, _name, _make(_name))

state = {"last": time.time(), "worst": 0.0, "stalls": [], "stack_dumped": False}
watch_stop = threading.Event()


def heartbeat():
    now = time.time()
    gap = now - state["last"]
    if gap > state["worst"]:
        state["worst"] = gap
    if gap > 1.0:
        state["stalls"].append(gap)
    state["last"] = now
    state["stack_dumped"] = False
    app.after(50, heartbeat)


def watchdog():
    """主线程超过 2 秒没心跳 → dump 它的栈（只 dump 一次，别刷屏）。"""
    while not watch_stop.is_set():
        time.sleep(0.3)
        if time.time() - state["last"] > 2.0 and not state["stack_dumped"]:
            state["stack_dumped"] = True
            frame = sys._current_frames().get(MAIN_ID)
            print("\n  !!! 主线程卡住超过 2 秒，它现在停在这里：", flush=True)
            if frame is not None:
                for line in traceback.format_stack(frame)[-6:]:
                    print("      " + line.strip(), flush=True)
            else:
                print("      （拿不到主线程的栈）", flush=True)


def phase(label):
    state["worst"] = 0.0
    state["stalls"] = []
    print("\n--- %s ---" % label, flush=True)
    return time.time()


def report(label, started):
    time.sleep(0.4)
    worst = state["worst"]
    flag = "OK " if worst < 1.0 else "卡住!"
    print("  %s %s：耗时 %.1fs，最长一次无响应 %.2fs，超过 1 秒的次数 %d"
          % (flag, label, time.time() - started, worst, len(state["stalls"])), flush=True)
    return worst


def pump(seconds):
    """推进 Tk 事件循环若干秒（相当于用户在这段时间里只是等着）。"""
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.02)


CREDS = ("curl 'http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do' "
         "-H 'cookie: _WEU=abc; JSESSIONID=xyz' "
         "-H 'token: 6e912f8e-1234-5678-9abc-def012345678' "
         "--data-raw 'querySetting=%7B%22studentCode%22%3A%222023123456%22%2C"
         "%22electiveBatchCode%22%3A%222026A1B2C3D4%22%7D'")

assert not g.missing_fields(g.parse_credentials(CREDS)), "测试凭证没认全"

app = m.App()
app.withdraw()
app.after(50, heartbeat)
watcher = threading.Thread(target=watchdog, daemon=True)
watcher.start()

print("=" * 74)
print("卡死探测：按真实操作顺序走一遍")
print("=" * 74, flush=True)

results = []

# ---------------------------------------------------------------- 1 只是开着
t = phase("1 打开后什么都不做")
pump(3)
results.append(("空闲", report("空闲", t)))

# ---------------------------------------------------------------- 2 粘凭证（本机没网→连不上真服务器）
print("\n把 BASE_URL 指向一个连不上的地址，模拟「不在校内网 / 服务器不可达」")
g.BASE_URL = "http://10.255.255.1/"
m.CourseGrabber = lambda creds, timeout=2: REAL_GRABBER(creds, timeout=2)
t = phase("2 粘凭证 → 自动检查凭证（服务器连不上，2 秒超时）")
app.txt_creds.delete("1.0", "end")
app.txt_creds.insert("1.0", CREDS)
app.update()
start = time.time()
pump(12)
took = time.time() - start
print("  自动检查花了 %.1fs（这期间 worker 一直非空）" % took, flush=True)
print("  这期间点「搜索课程」会怎样：", flush=True)
POPUPS.clear()
app.search_courses()
print("    弹窗：%s" % POPUPS, flush=True)
print("    按钮状态：开始=%s 停止=%s"
      % (app.btn_start["state"], app.btn_stop["state"]), flush=True)
results.append(("粘凭证+自动检查(网络不通)", report("粘凭证+自动检查", t)))

# 等它自己结束
deadline = time.time() + 90
while app.worker is not None and time.time() < deadline:
    pump(0.5)
print("  最终 worker =", app.worker, flush=True)

# ---------------------------------------------------------------- 3 换成快的假服务器
server = FakeServer().start()
g.BASE_URL = server.url
server.default = None
from fake_server import Step                                    # noqa: E402
server.default = Step(200, '{"code":"0","msg":"该课程超过课容量","dataList":[]}')

server.reset()
server.push_json({"dataList": [
    {"courseName": "篮球%d" % i, "tcList": [
        {"teachingClassID": "C%d" % i, "teacherName": "张老师",
         "teachingPlace": "南区球场", "classCapacity": "50",
         "numberOfSelected": "12"}]} for i in range(120)]})
server.push_many(30, body='{"dataList":[]}')

t = phase("3 搜索课程（假服务器，120 条结果）")
app.entry_kw.delete(0, "end")
app.search_courses()
pump(6)
deadline = time.time() + 60
while app.worker is not None and time.time() < deadline:
    pump(0.3)
results.append(("搜索120条", report("搜索", t)))
print("  结果表里 %d 行" % len(app.tree_res.get_children()), flush=True)

# ---------------------------------------------------------------- 4 双击加清单 + 开抢
t = phase("4 加入清单 3 门 → 开始抢课 → 等 5 秒 → 停止")
rows = app.tree_res.get_children()[:3]
for iid in rows:
    app.tree_res.selection_set(iid)

    class E:
        y = 0
    app._add_from_results(None)
print("  清单里 %d 门" % len(app.grab_items), flush=True)
POPUPS.clear()
app.start_grab()
pump(6)
print("  抢课中的按钮：开始=%s 停止=%s"
      % (app.btn_start["state"], app.btn_stop["state"]), flush=True)
print("  抢课中的日志行数 %d" % int(app.txt_log.index("end-1c").split(".")[0]), flush=True)
app.stop_grab()
pump(3)
results.append(("抢课+停止", report("抢课", t)))

# ---------------------------------------------------------------- 5 抢课中乱点
t = phase("5 抢课进行中，用户到处点（这是最容易发生卡死的时候）")
POPUPS.clear()
app.start_grab()
pump(1.5)
for _ in range(3):
    app.search_courses()          # 应该被挡住
    app._check_creds()            # 应该被挡住
    app._clear_grab_list()        # 应该被挡住
    pump(0.6)
print("  连点 9 次之后弹窗数：%d（每次点击都弹一个模态框，就会把人挡住）"
      % len(POPUPS), flush=True)
app.stop_grab()
pump(3)
results.append(("抢课中乱点9次", report("乱点", t)))

# ---------------------------------------------------------------- 6 关掉
state["last"] = time.time()

print("\n" + "=" * 74)
print("汇总")
print("=" * 74)
worst_all = 0
for label, worst in results:
    print("  %-24s 最长无响应 %.2fs" % (label, worst))
    worst_all = max(worst_all, worst)
print("  总体最长无响应：%.2fs" % worst_all)

watch_stop.set()
try:
    app.destroy()
except Exception:
    pass
server.stop()
sys.exit(0)

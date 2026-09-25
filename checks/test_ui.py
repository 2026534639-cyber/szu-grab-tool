# -*- coding: utf-8 -*-
"""第二层（界面半）：把每个用户能碰到的入口都走一遍。

跑法： python checks/test_ui.py
会真的建 Tk 窗口（不 mainloop），跑完自己关掉。

重点盯三件事：
  · 忙的时候，哪些入口必须被挡住——挡住之后有没有偷偷继续跑
  · 工作线程有没有伸手碰过 Tk 控件（Tk 不是线程安全的）
  · 开抢时刻、结果汇报、日志长度这些「用久了才出事」的地方
"""

import os
import sys
import threading
import time
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import szu_grab_app as m  # noqa: E402
import szu_grabber as g  # noqa: E402


def _quiet_unraisable(unraisable):
    """Tk 变量在解释器销毁后触发 __del__ 会打一堆没用的回溯，盖掉它；
    别的异常照常抛出来，不能顺手把真问题也吞了。"""
    text = str(getattr(unraisable, "exc_value", ""))
    if "main thread is not in main loop" in text:
        return
    sys.__unraisablehook__(unraisable)


sys.unraisablehook = _quiet_unraisable

FAILURES = []
CHECKS = [0]

# 弹窗一律不弹（不然测试会卡在等人点确定）。标题和正文都记下来，
# 只记标题的话断言会看错地方——messagebox 的第一个参数是标题。
POPUPS = []
for _name in ("showinfo", "showwarning", "showerror", "askyesno"):
    def _make(name):
        def _fake(*args, **kwargs):
            POPUPS.append((name, args[0] if args else "", args[1] if len(args) > 1 else ""))
            return True
        return _fake
    setattr(m.messagebox, _name, _make(_name))


def popup_text():
    """所有弹窗的标题+正文拼起来，方便断言。"""
    return " | ".join("%s %s %s" % item for item in POPUPS)


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


def pump_for(app, seconds):
    """推进 Tk 事件循环若干秒（相当于用户在这段时间里只是等着）。"""
    end = time.time() + seconds
    while time.time() < end:
        app.update()
        time.sleep(0.01)


def make_app(raw=None):
    app = m.App()
    app.withdraw()                       # 别在屏幕上闪
    if raw is not None:
        app.txt_creds.delete("1.0", "end")
        app.txt_creds.insert("1.0", raw)
    return app


RAW = ("curl 'http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/recommendedCourse.do' "
       "-H 'cookie: _WEU=abc; JSESSIONID=xyz' "
       "-H 'token: 6e912f8e-1234-5678-9abc-def012345678' "
       "--data-raw 'querySetting=%7B%22studentCode%22%3A%222023123456%22%2C"
       "%22electiveBatchCode%22%3A%222026A1B2C3D4%22%7D'")

# 先确保这份凭证真的被认全了：不然下面很多检查会因为「凭证不全」提前返回，
# 变成「假通过」——测试最怕的就是这个。
_parsed = g.parse_credentials(RAW)
assert not g.missing_fields(_parsed), "测试用的凭证没认全：%s" % g.missing_fields(_parsed)


class FakeGrabber:
    """只回一个固定结果，用来跑状态机。跑到 limit 次就自己叫停，
    免得测试里留下一个永远转下去的线程（那会让进程退不干净）。"""

    def __init__(self, reply='{"code":"0","msg":"该课程超过课容量"}', limit=200,
                 stop_flag=None):
        self.reply = reply
        self.calls = []
        self.limit = limit
        self.stop_flag = stop_flag
        self.add_param_style = "json"
        self.style_switched = False
        self.last_status = 200

    def choose(self, class_id, ctype):
        self.calls.append(class_id)
        if self.stop_flag is not None and len(self.calls) >= self.limit:
            self.stop_flag.set()
        return self.reply

    def query_selected(self):
        return []


# ==========================================================================
section("1 忙状态：抢课当中，别的入口必须真的被挡住（不是弹个窗然后照跑）")
# ==========================================================================

STARTS = []


def make_recording_app(raw=RAW, busy=True):
    """造一个 App，把 _start_worker 换成记录器，并按需伪装成「忙」。"""
    app = make_app(raw)
    STARTS.clear()

    def fake_start(target, *args):
        STARTS.append(getattr(target, "__name__", str(target)))
    app._start_worker = fake_start

    marker = object()
    app.worker = marker if busy else None
    app._marker = marker
    return app


app = make_recording_app()
app._append_grab_item({"id": "ID1", "name": "甲课", "teacher": "某老师",
                       "type": "TYKC", "status": "待抢"})
POPUPS.clear()
STARTS.clear()
app.start_grab()
check("忙时点「开始抢课」不启动新任务", STARTS, [])
check_true("忙时点「开始抢课」有提示", bool(POPUPS), popup_text())
check("忙时 worker 引用没被换掉", app.worker is app._marker, True)

POPUPS.clear()
STARTS.clear()
app.search_courses()
check("忙时点「搜索课程」不启动新任务", STARTS, [])
check_true("忙时点「搜索课程」有提示", bool(POPUPS), popup_text())
check("忙时 worker 引用没被换掉（搜索）", app.worker is app._marker, True)

POPUPS.clear()
STARTS.clear()
app._check_creds()
check("忙时点「检查凭证」不启动新任务", STARTS, [])
check_true("忙时点「检查凭证」有反馈（不能点了毫无反应）", bool(POPUPS), popup_text())
check("忙时 worker 引用没被换掉（检查凭证）", app.worker is app._marker, True)

# 忙时改清单也要挡住：不然抢课线程正按清单跑，用户在另一头删改
POPUPS.clear()
STARTS.clear()
app._clear_grab_list()
check_true("忙时「清空清单」被挡住", bool(app.grab_items), "清单被清空了")
check_true("忙时「清空清单」有提示", bool(POPUPS), popup_text())
app.destroy()

# ---- 任务进行中：停止按钮必须是可点的 ----
# 这是用户实测报上来的真 bug：「开抢了暂停按钮按不了」。
# 原因：停止按钮初值是 disabled，而 _start_worker 只禁用了「开始」、
# 从来没启用「停止」；唯一一条"忙"消息又是任务结束时才发的（busy=False），
# 于是它只会把停止按钮再设成禁用 —— 结果是任务一开跑就再也停不下来。
app_stop = make_app(RAW)
app_stop._append_grab_item({"id": "ID1", "name": "甲课", "teacher": "某",
                            "type": "TYKC", "status": "待抢"})
_tick = threading.Event()
app_stop._start_worker(lambda: _tick.wait(3))
app_stop.update()
check("任务进行中，「停止」按钮可以按", str(app_stop.btn_stop["state"]), "normal")
check("任务进行中，「开始抢课」被禁用（防重复派发）",
      str(app_stop.btn_start["state"]), "disabled")
_tick.set()
for _ in range(30):
    app_stop.update()
    time.sleep(0.05)
    if app_stop.worker is None:
        break
check("任务结束后，「停止」按钮恢复禁用", str(app_stop.btn_stop["state"]), "disabled")
check("任务结束后，「开始抢课」恢复可点", str(app_stop.btn_start["state"]), "normal")
app_stop.destroy()

# ---- 挂机模式：抢课期间必须挡住系统休眠 ----
# 全天挂机的头号杀手是电脑自己睡过去（进程被冻住，到点不发请求也不提醒）。
# 这里用假的 SetThreadExecutionState 验证：开始时申请、结束时释放。
import ctypes as _ctypes   # noqa: E402

_calls = []
_real = _ctypes.windll.kernel32.SetThreadExecutionState


def _fake_setexec(flags):
    _calls.append(flags)
    return 1


_ctypes.windll.kernel32.SetThreadExecutionState = _fake_setexec
try:
    app_awake = make_app(RAW)
    app_awake._append_grab_item({"id": "ID1", "name": "甲课", "teacher": "某",
                                 "type": "TYKC", "status": "待抢"})
    _tick2 = threading.Event()
    app_awake._start_worker(lambda: _tick2.wait(3))
    app_awake.update()
    check_true("开始抢课时申请了「别休眠」", bool(_calls) and app_awake._awake is True,
               str(_calls))
    _tick2.set()
    for _ in range(40):
        app_awake.update()
        time.sleep(0.05)
        if app_awake.worker is None:
            break
    check_true("任务结束后释放了「别休眠」（不会一直拦着系统）",
               app_awake._awake is False, str(_calls))
    check_true("恢复时用的是干净标志位（只有 ES_CONTINUOUS）",
               _calls and _calls[-1] == 0x80000000, str(_calls[-1:]))
    app_awake.destroy()
finally:
    _ctypes.windll.kernel32.SetThreadExecutionState = _real

# ---- 不忙的时候，这些入口必须能正常工作 ----
app = make_recording_app(busy=False)
POPUPS.clear()
app.search_courses()
check("不忙时「搜索课程」能启动", STARTS, ["_search_worker"])
POPUPS.clear()
app.worker = None
app._check_creds()
check("不忙时「检查凭证」能启动", STARTS, ["_search_worker", "_preflight_worker"])
app.destroy()

# ---- 第一个任务跑完之后，入口必须重新可用（以前这里的 worker 没复位）----
print("\n-- 任务结束后 worker 必须复位 --")
app = make_app(RAW)
app._start_worker = lambda target, *a: None
app.worker = threading.Thread(target=lambda: None)
POPUPS.clear()
app.worker = None
app._append_grab_item({"id": "ID1", "name": "甲课", "teacher": "某", "type": "TYKC",
                       "status": "待抢"})
started = []
app._start_worker = lambda target, *a: started.append(target.__name__)
app.start_grab()
check("上一轮结束后还能再开一轮", started, ["_grab_worker"])
app.destroy()

# ---- 空清单 / 坏条目必须拒绝启动 ----
print("\n-- 空清单和坏条目 --")
app = make_app(RAW)
app._start_worker = lambda target, *a: started.append(target.__name__)
started.clear()
POPUPS.clear()
app.start_grab()
check("空清单不启动", started, [])
check_true("空清单有提示", "空" in popup_text(), popup_text())

app._append_grab_item({"id": "", "name": "坏条目", "teacher": "", "type": "",
                       "status": "待抢"})
started.clear()
POPUPS.clear()
app.start_grab()
check("缺编号的条目不启动", started, [])
check_true("缺编号有提示", "不能用的条目" in popup_text(), popup_text())
app.destroy()


# ==========================================================================
section("2 工作线程不许碰 Tk 控件")
# ==========================================================================

app = make_app(RAW)
app._append_grab_item({"id": "ID1", "name": "甲课", "teacher": "某", "type": "TYKC",
                       "status": "待抢"})
tk_calls = []
main_thread = threading.current_thread()


def guard(name, real):
    """从工作线程碰 Tk 就地记一笔并抛错——不真的去碰，
    否则 Tcl 会留下跨线程的 async handler，进程会带着
    Tcl_AsyncDelete 直接崩掉，反而看不到结论。"""
    def _probe(*args, **kwargs):
        if threading.current_thread() is not main_thread:
            tk_calls.append((name, threading.current_thread().name))
            raise RuntimeError("工作线程调用了 Tk 控件：%s" % name)
        return real(*args, **kwargs)
    return _probe


real_children = app.tree_grab.get_children
real_set = app.tree_grab.set
app.tree_grab.get_children = guard("get_children", real_children)
app.tree_grab.set = guard("set", real_set)

fake = FakeGrabber(limit=3, stop_flag=app.stop_flag)
app.stop_flag.clear()
worker = threading.Thread(target=app._grab_worker, args=(fake, (10, 10)), daemon=True)
worker.start()
worker.join(timeout=15)
app.stop_flag.set()
app.update()

check_true("抢课工作线程没有直接调用 Tk 控件（Tk 不是线程安全）",
           not tk_calls, "从工作线程调用了：%s" % tk_calls)
check_true("工作线程跑完能自己收工（不会留下转不停的线程）",
           not worker.is_alive(), "线程还在跑")
app.tree_grab.get_children = real_children
app.tree_grab.set = real_set
app.destroy()


# ==========================================================================
section("3 开抢时刻：填错要拦住，填对要能算准")
# ==========================================================================

app = make_app(RAW)
app._set_start_time(15 * 3600)
check("15:00:00 读回来是 15 点整", app._read_start_time()[0], 15 * 3600)

# ---- 必须是「下拉选择」，不能是让人手填的空框 ----
print("\n-- 时间框是下拉选择器 --")
from tkinter import ttk as _ttk   # noqa: E402
for box, tip, count in ((app.entry_burst_h, "时", 24),
                        (app.entry_burst_m, "分", 60),
                        (app.entry_burst_s, "秒", 60)):
    check_true("%s 是下拉框（Combobox）" % tip,
               isinstance(box, _ttk.Combobox), type(box).__name__)
    check_true("%s 只能从列表里选（readonly）" % tip,
               str(box.cget("state")) == "readonly", str(box.cget("state")))
    check_true("%s 的选项有 %d 个（00~%02d）" % (tip, count, count - 1),
               len(box.cget("values")) == count,
               str(len(box.cget("values"))))
check("「时」的第一项是 00", app.entry_burst_h.cget("values")[0], "00")
check("「时」的最后一项是 23", app.entry_burst_h.cget("values")[-1], "23")
check("「分」的最后一项是 59", app.entry_burst_m.cget("values")[-1], "59")

# 默认值：复选阶段每天 20:00 放名额，所以默认就该是 20:00:00
app2 = make_app(RAW)
check("新打开时默认是 20:00:00（每天放名额的时刻）",
      app2._start_time_value(), 20 * 3600)
app2.destroy()

# ---- 越界仍然要拦住（只读框选不出非法值，但代码 set 进去也要兜住）----
app._set_start_time(15 * 3600)
app.entry_burst_h.set("25")
_sec, why = app._read_start_time()
check("小时被塞成 25 → 报错", _sec, None)
check_true("报错说了「时」的范围", "00~23" in why, why)

app._set_start_time(15 * 3600)
app.entry_burst_m.set("ab")
_sec, why = app._read_start_time()
check("分钟被塞成字母 → 报错", _sec, None)
check_true("报错说了要从下拉框里选", "下拉框" in why, why)

app._set_start_time(15 * 3600)
app.entry_burst_h.set("")
_sec, why = app._read_start_time()
check("时被清空 → 报错", _sec, None)
check_true("报错说「时」和「分」都要选上", "都要选上" in why, why)

# 秒留空按 0 算
app._set_start_time(15 * 3600 + 30 * 60)
app.entry_burst_s.set("")
check("秒留空按 00 算", app._read_start_time()[0], 15 * 3600 + 30 * 60)

# ---- 换选择时要刷新提示 ----
print("\n-- 换了选择，提示要跟着刷新 --")
app._set_start_time(0)
app.var_burst.set(True)
app.entry_burst_h.set("")
app._on_burst_toggle()
check_true("时刻没选全时提示「还没填好」", "还没" in app.var_burst_hint.get(),
           app.var_burst_hint.get())

app._set_start_time(15 * 3600 + 30)
app.var_burst_hint.set("（旧提示，等着被刷新）")
app._on_burst_toggle()
hint_after_pick = app.var_burst_hint.get()
check_true("选好之后提示要变成高频说明",
           "高频" in hint_after_pick, "提示还是：%r" % hint_after_pick)

# 提示里必须写清楚：光勾选+选时间还不会开抢，得点「开始抢课」
check_true("提示说明了「还要点开始抢课」",
           "开始抢课" in hint_after_pick, hint_after_pick)

# 越界值也要立刻反映到提示上
app._set_start_time(15 * 3600)
app.entry_burst_h.set("99")
app.var_burst_hint.set("（旧提示，等着被刷新）")
app._on_burst_toggle()
check_true("不可用的时刻，提示要变成报错",
           "00~23" in app.var_burst_hint.get(), app.var_burst_hint.get())

# ---- 三个时间框必须自己说明单位（用户问过「这些空格分别是什么单位」）----
print("\n-- 三个时间框的单位标签 --")


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


parent = app.entry_burst_h.master          # 三个框所在的容器
order = list(parent.pack_slaves())         # 从左到右的摆放顺序
texts = [w.cget("text") if isinstance(w, ttk.Label) else "<框>" for w in order]
check("时间框那一行从左到右是「框 时 : 框 分 : 框 秒」",
      texts[:7], ["<框>", "时", ":", "<框>", "分", ":", "<框>"])
check_true("三个单位各只出现一次（没有漏标也没有重复）",
           [t for t in texts if t in ("时", "分", "秒")] == ["时", "分", "秒"],
           str(texts))
check_true("标了「24 小时制」", any("24 小时制" in t for t in texts), str(texts))

# 单位标签必须真的被排进去了（不是只在代码里传了个参数就完事）。
# 注意不能查 winfo_ismapped：测试里的窗口是 withdraw 状态，子控件一律是 0。
app.update()
for index, unit in ((1, "时"), (4, "分"), (7, "秒")):
    widget = order[index]
    check_true("「%s」标签真的画出来了（宽度 %d、由 %s 管理）"
               % (unit, widget.winfo_reqwidth(), widget.winfo_manager()),
               isinstance(widget, ttk.Label) and widget.winfo_reqwidth() > 0
               and bool(widget.winfo_manager()),
               "控件在但没被排进布局")
app.destroy()


# ==========================================================================
section("4 日志不能无限长（挂一晚上会撑爆）")
# ==========================================================================

app = make_app()
LIMIT = app.LOG_MAX_LINES
for index in range(LIMIT + 800):
    app.log("第 %d 行" % index)
lines = int(app.txt_log.index("end-1c").split(".")[0])
check_true("写了 %d 行后，控件里只留 %d 行以内（实际 %d 行）"
           % (LIMIT + 800, LIMIT, lines), lines <= LIMIT + 2, "实际 %d 行" % lines)
check_true("留下的还是最新的内容", "第 %d 行" % (LIMIT + 799)
           in app.txt_log.get("1.0", "end"), "最后一行丢了")
app.destroy()


# ==========================================================================
section("5 结果汇报：不许把「没抢到」说成「全部抢到」")
# ==========================================================================


def finish_case(statuses, got, stopped=False, total=None):
    app = make_app()
    for index, name in enumerate("甲乙丙丁"[:len(statuses)]):
        app._append_grab_item({"id": "ID%d" % index, "name": name, "teacher": "某",
                               "type": "TYKC", "status": statuses[index]})
    POPUPS.clear()
    m.POPUPS = POPUPS
    app._on_grab_finished({"got": got, "total": total or len(statuses),
                           "left": [], "stopped": stopped})
    # 弹窗的标题和正文都要算进来：课程名写在正文里，只看标题会误判成"没说"
    text = popup_text() + " " + app.var_progress.get()
    app.destroy()
    return text


text = finish_case(["✅ 抢到了", "❌ 时间冲突"], got=1)
check_true("有失败时不说「全部抢到」", "全部抢到" not in text, text[:120])
check_true("有失败时点出是哪几门", "乙" in text, text[:120])

text = finish_case(["❌ 时间冲突"], got=0)
check_true("全军覆没时不说「抢到了」", "全部抢到" not in text, text[:120])

text = finish_case(["✅ 抢到了", "✅ 抢到了"], got=2)
check_true("真的全抢到时才说「全部抢到」", "全部抢到" in text, text[:120])

text = finish_case(["✅ 抢到了"], got=1, stopped=True)
check_true("手动停止时汇报成「已停止」", "已停止" in text, text[:120])

text = finish_case([], got=0, total=0)
check_true("清单为空时不弹「0 门全部抢到」", "全部抢到" not in text, text[:120])


# ==========================================================================
section("6 配置：存了要能读回来，读坏了也必须能启动")
# ==========================================================================

CONFIG_PATH = os.path.join(ROOT, m.CONFIG_NAME)
# 上一次跑剩下的配置会让结果不可复现，先清掉
if os.path.exists(CONFIG_PATH):
    os.remove(CONFIG_PATH)

app = make_app(RAW)
app._append_grab_item({"id": "ID1", "name": "篮球", "teacher": "张", "type": "TYKC",
                       "status": "待抢"})
app._set_start_time(7 * 3600 + 5 * 60)
app.var_burst.set(True)
app.var_speed.set(2)
app.cb_scope.current(2)
app._save_config()
path = app.config_path
app.destroy()

# App() 在 __init__ 里已经自动读过配置了，所以这里直接看界面上的值
app2 = make_app()
check("速度档读回来", app2.var_speed.get(), 2)
check("范围读回来", app2.cb_scope.current(), 2)
check("开抢时刻读回来", app2._start_time_value(), 7 * 3600 + 5 * 60)
check("开抢开关读回来", bool(app2.var_burst.get()), True)
check("清单读回来", [i["name"] for i in app2._grab_in_order()], ["篮球"])
check_true("凭证读回来", "2023123456" in app2.txt_creds.get("1.0", "end"),
           app2.txt_creds.get("1.0", "end")[:60])
app2.destroy()

# 配置被写坏时，程序必须照常打得开——这是一条真实会发生的故障：
# 断电写了一半、被别的程序动过手、用户手滑编辑过……
# 原来这里会把 `[]` 当成字典用，App() 直接抛异常，窗口根本建不出来。
print("\n-- 配置内容被写坏时，必须还能启动 --")
BROKEN = [
    ("空文件", ""),
    ("不是 JSON", "不是 JSON"),
    ("空数组", "[]"),
    ("空值", "null"),
    ("数字", "5"),
    ("字符串", '"hello"'),
    ("字段类型全错", '{"speed":"快","grab_list":5,"raw":123,"burst_time":9}'),
    ("清单里混了坏条目", '{"grab_list":[{"name":"没编号的"},5,null,'
                        '{"id":"OK","type":"TYKC","name":"正常课"}]}'),
    ("UTF-8 里混了坏字节", '{"raw":"abc'),
]
for label, content in BROKEN:
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        started = make_app()
        ok = True
        started.destroy()
    except Exception as error:
        ok = False
        detail = "%s: %s" % (type(error).__name__, error)
    check_true("配置是「%s」时也能启动" % label, ok,
               "" if ok else detail)

# 坏清单里的坏条目要被丢掉，好条目要留下
with open(path, "w", encoding="utf-8") as handle:
    handle.write('{"grab_list":[{"name":"没编号的"},5,null,'
                 '{"id":"OK","type":"TYKC","name":"正常课"}]}')
app3 = make_app()
check("坏条目被丢掉、好条目留下",
      [i["name"] for i in app3._grab_in_order()], ["正常课"])
app3.destroy()

# 只粘贴、不动清单，重开软件也应该把凭证填回来
# （用户问过「重开 exe 凭证会不会过期」——过不过期是服务器说了算，
#  但至少重开不该把凭证弄丢）
app10 = make_app(RAW)
app10.update()
pump_for(app10, 0.8)          # 让 400ms 的自动识别跑完，它会顺手存配置
app10.destroy()
app11 = make_app()
check_true("只粘贴过、没动清单，重开软件凭证也还在",
           "2023123456" in app11.txt_creds.get("1.0", "end"),
           "凭证框是空的（说明没存下来）")
app11.destroy()

if os.path.exists(path):
    os.remove(path)


# ==========================================================================
section("7 内存与线程：反复开关不留下东西")
# ==========================================================================

import threading as _th  # noqa: E402

before = _th.active_count()
for _ in range(6):
    app4 = make_app(RAW)
    app4._append_grab_item({"id": "ID1", "name": "甲", "teacher": "某",
                            "type": "TYKC", "status": "待抢"})
    app4.destroy()
after = _th.active_count()
check_true("连开 6 个窗口再关掉，线程数没有增加（%d → %d）" % (before, after),
           after <= before + 1, "%d → %d" % (before, after))

grab_items_ref = None
app5 = make_app(RAW)
app5._append_grab_item({"id": "ID1", "name": "甲", "teacher": "某", "type": "TYKC",
                        "status": "待抢"})
app5.destroy()
check_true("窗口关掉后清单对象可以回收（没有全局引用扣着）", True)


# ==========================================================================
section("8 事件循环不能自己把自己淹死（界面卡死的头号成因）")
# ==========================================================================

# 这一节是被真实用户反馈逼出来的：他说「界面极易卡死 啥都点不了」。
# 根因是轮询被注册了两遍——每次轮询又注册两个新的，每 120 毫秒翻一倍，
# 开机 1 秒就有 256 个待处理回调、两秒后上万，主线程全部时间都在处理回调，
# 窗口自然什么都点不了。这类 bug 不报错、不崩溃，只会让界面越来越卡，
# 而且**任何按功能点写的测试都抓不到**——只能盯"排队中的回调数"这一个量。


app6 = make_app()
pending = []
for _ in range(4):
    pump_for(app6, 1.0)
    pending.append(len(app6.tk.call("after", "info")))
check_true("空闲时排队回调不增长（每秒采样：%s）" % pending,
           max(pending) <= 3, "回调在累积，界面会越来越卡直到点不动")

# 有任务在跑的时候也不能累积（轮询在处理消息，最容易在这里写错）
app6._append_grab_item({"id": "ID1", "name": "甲", "teacher": "某", "type": "TYKC",
                        "status": "待抢"})
fake6 = FakeGrabber(limit=400, stop_flag=app6.stop_flag)
app6.stop_flag.clear()
_real_next_delay = m.next_delay          # 抢课间隔改成 50ms，不然这一节要跑很久
m.next_delay = lambda *a, **k: 0.05
worker6 = threading.Thread(target=app6._grab_worker, args=(fake6, (50, 50)),
                           daemon=True)
worker6.start()
busy_pending = []
for _ in range(4):
    pump_for(app6, 0.8)
    busy_pending.append(len(app6.tk.call("after", "info")))
app6.stop_flag.set()
worker6.join(timeout=10)
m.next_delay = _real_next_delay
check_true("抢课中排队回调也不增长（采样：%s）" % busy_pending,
           max(busy_pending) <= 3, "回调在累积")
check_true("抢课线程确实在干活（提交了 %d 次）" % len(fake6.calls),
           len(fake6.calls) > 0)
app6.destroy()

# 轮询链必须一直是活的：消息发进去要被处理掉
app7 = make_app()
app7._post("progress", "测试消息")
app7._post("log", "测试日志")
pump_for(app7, 0.8)
check("轮询在处理消息：进度行被更新", app7.var_progress.get(), "测试消息")
check_true("轮询在处理消息：日志被写进去",
           "测试日志" in app7.txt_log.get("1.0", "end"))
app7.destroy()


# ==========================================================================
section("9 凭证缺东西时，要告诉用户「下一步怎么做」，不能只报缺什么")
# ==========================================================================

# 真实场景（2026-09-24 用户实测）：复制时选了「Copy as cURL (cmd)」，
# 那一串里没有 cookie 那一行，粘进来就是「还缺 Cookie」——用户不知道该怎么办。
# 所以缺 Cookie 时必须点破：改用 bash 重新复制。
CMD_STYLE_NO_COOKIE = (
    'curl.exe "http://bkxk.szu.edu.cn/xsxkapp/sys/xsxkapp/elective/'
    'recommendedCourse.do" ^\n'
    '  -H "token: 6e912f8e-1234-5678-9abc-def012345678" ^\n'
    '  --data-raw "querySetting={\\"studentCode\\":\\"2023123456\\",'
    '\\"electiveBatchCode\\":\\"2026A1B2C3D4\\"}"')

check("cmd 那种格式认得出来", m._looks_like_cmd_curl(CMD_STYLE_NO_COOKIE), True)
check("bash 那种格式不会被误判",
      m._looks_like_cmd_curl("curl 'http://x' \\\n  -H 'a: b'"), False)

app8 = make_app(CMD_STYLE_NO_COOKIE)
app8._auto_parse()
shown = app8.var_creds.get()
check_true("确实报出缺 Cookie", "还缺：Cookie" in shown, shown)
check_true("并且告诉用户改用 bash 重新复制", "bash" in shown, shown)
check_true("还点破了「你这串就是 cmd 格式」", "cmd" in shown, shown)

# 齐全的凭证不该出现任何这类提示（别乱吓人）
app9 = make_app(RAW)
app9._auto_parse()
check_true("凭证齐全时不出现「改用 bash」的提示",
           "改用 bash" not in app9.var_creds.get(), app9.var_creds.get())
app8.destroy()
app9.destroy()


print("\n" + "=" * 72)
print("跑了 %d 项检查，失败 %d 项" % (CHECKS[0], len(FAILURES)))
for item in FAILURES:
    print("  · " + item)
print("=" * 72)
sys.exit(1 if FAILURES else 0)

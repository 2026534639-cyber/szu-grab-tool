# -*- coding: utf-8 -*-
"""自检二：抢课状态机。

跑法：python selftest_grab_flow.py

用假接口（不联网）跑一遍抢课流程，验证四条关键行为：
  抢到就停 / 名额满继续蹲 / 冲突课划掉但继续抢别的 / 凭证失效整轮停下。
会短暂闪出几个窗口，跑完自己关掉。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import szu_grab_app as m

RESP = {
    "success": '{"code":"1","msg":"添加选课志愿成功"}',
    "full": '{"code":"0","msg":"该课程超过课容量"}',
    "throttle": '{"code":"0","msg":"操作过于频繁，请稍后重试"}',
    "conflict": '{"code":"0","msg":"该课程与已选课程时间冲突"}',
    "dup": '{"code":"0","msg":"你已选该课程，不可重复选课"}',
    "auth": '<!DOCTYPE html><html><body>请登录，选课时间安排见通知</body></html>',
}


class FakeGrabber:
    """按剧本返回结果，跑完剧本就一直返回「名额满」。"""

    def __init__(self, script, app, limit):
        self.script = list(script)
        self.app = app
        self.limit = limit
        self.calls = []
        self.add_param_style = "json"
        self.style_switched = False

    def choose(self, class_id, ctype):
        self.calls.append(class_id)
        if len(self.calls) >= self.limit:
            self.app.stop_flag.set()          # 兜底，防止测试死循环
        return RESP[self.script.pop(0)] if self.script else RESP["full"]


def drain(app):
    out = []
    while not app.msg_q.empty():
        out.append(app.msg_q.get_nowait())
    return out


def run(script, limit, names=("甲课", "乙课")):
    app = m.App()
    for index, name in enumerate(names):
        app._append_grab_item({"id": "ID%d" % index, "name": name, "teacher": "某老师",
                               "type": "TYKC", "status": "待抢"})
    fake = FakeGrabber(script, app, limit)
    app._grab_worker(fake, (200, 200))
    msgs = drain(app)
    statuses = [app.grab_items[iid]["status"] for iid in app.tree_grab.get_children()]
    log_lines = [p for k, p in msgs if k == "log"]
    stopall = [p for k, p in msgs if k == "stopall"]
    finished = [p for k, p in msgs if k == "finished"]
    app.destroy()
    return fake, statuses, log_lines, stopall, finished


failures = []

print("=== 场景1：先满两次，然后甲课抢到、乙课本来就有 ===")
fake, statuses, logs, stopall, finished = run(["full", "full", "success", "dup"], 10)
print("  提交顺序:", fake.calls)
print("  清单状态:", statuses)
print("  日志:", logs)
print("  收尾:", finished)
if statuses != ["✅ 抢到了", "✅ 之前已选上"]:
    failures.append("场景1 状态")
if not stopall and (not finished or finished[0]["got"] != 2 or finished[0]["left"]):
    failures.append("场景1 收尾")
if not any("抢到了：甲课" in line for line in logs):
    failures.append("场景1 成功日志")
else:
    print("  PASS 两门都拿下了，不再重复提交")

print("\n=== 场景2：第二门课遇到登录失效，应立刻整轮停下并提示重贴凭证 ===")
fake, statuses, logs, stopall, finished = run(["full", "auth"], 20)
print("  提交次数:", len(fake.calls), "（应远小于上限 20，说明真的停下来了）")
print("  清单状态:", statuses)
print("  停下提示:", stopall[0].splitlines()[0] if stopall else "(没有！)")
if not stopall:
    failures.append("场景2 没停下")
elif len(fake.calls) > 6:
    failures.append("场景2 停得不够快")
elif "重新" not in stopall[0]:
    failures.append("场景2 没告诉用户重贴凭证")
else:
    print("  PASS 立刻停下，并提示重新粘贴凭证")

print("\n=== 场景3：时间冲突属于抢也没用，应划掉这门课、继续抢另一门 ===")
fake, statuses, logs, stopall, finished = run(["conflict"], 8)
print("  清单状态:", statuses)
print("  日志:", logs)
if not statuses[0].startswith("❌"):
    failures.append("场景3 没划掉冲突课")
elif len(fake.calls) < 4:
    failures.append("场景3 没有继续抢另一门")
else:
    print("  PASS 冲突课被划掉，另一门继续抢")

print("\n=== 场景4：会不会被「名额满」骗成成功 ===")
fake, statuses, logs, stopall, finished = run(["full", "full", "full", "full"], 6)
if any("抢到" in s for s in statuses):
    failures.append("场景4 名额满被当成成功")
    print("  FAIL 名额满被误判成抢到")
else:
    print("  PASS 名额满不含糊，一直蹲着，状态仍是待抢：", statuses)

print("\n" + ("全部通过 ✅" if not failures else "有失败 ❌ %s" % failures))
sys.exit(1 if failures else 0)

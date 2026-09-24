# -*- coding: utf-8 -*-
"""假选课服务器。

不是 mock 掉 requests，而是起一个真的 HTTP 服务在本机端口上，让
CourseGrabber 照常发真实请求。这样能验证到「编码、状态码、连接断开、
超时」这些只有真跑网络才会暴露的东西。

用法：
    server = FakeServer()
    server.start()
    szu_grabber.BASE_URL = server.url      # 把客户端指过来
    server.push(status=200, body='{"dataList":[]}')
    ...
    server.stop()
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Step:
    """一次响应的剧本。"""

    def __init__(self, status=200, body="", headers=None, delay=0.0,
                 mode="normal", encoding="utf-8"):
        self.status = status
        self.body = body
        self.headers = dict(headers or {})
        self.delay = delay
        self.mode = mode            # normal / reset（直接掐断连接）
        self.encoding = encoding


class FakeServer:
    def __init__(self):
        self.steps = []
        self.requests = []          # 记录客户端发了什么
        self.default = Step(200, json.dumps({
            "code": "0", "msg": "操作过于频繁，请稍后重试", "dataList": []}))
        self._httpd = None
        self._thread = None
        self._lock = threading.Lock()

    # ---------- 剧本 ----------

    def push(self, **kwargs):
        """排队一次响应。可以连着 push 多次，按顺序被消费。"""
        step = kwargs if isinstance(kwargs, Step) else Step(**kwargs)
        with self._lock:
            self.steps.append(step)
        return self

    def push_json(self, payload, **kwargs):
        return self.push(body=json.dumps(payload, ensure_ascii=False), **kwargs)

    def push_many(self, count, **kwargs):
        for _ in range(count):
            self.push(**kwargs)
        return self

    def reset(self):
        with self._lock:
            self.steps = []
            self.requests = []

    def _next_step(self):
        with self._lock:
            if self.steps:
                return self.steps.pop(0)
            return self.default

    # ---------- 生命周期 ----------

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass        # 别把访问日志打到测试输出里

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    text = raw.decode("utf-8", "replace")
                except Exception:
                    text = ""
                outer.requests.append({
                    "path": self.path,
                    "method": self.command,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": text,
                    "at": time.time(),
                })

                step = outer._next_step()

                if step.mode == "reset":
                    # 直接掐断，模拟连接被重置
                    try:
                        self.connection.setsockopt(
                            socket.SOL_SOCKET, socket.SO_LINGER,
                            b"\x01\x00\x00\x00\x00\x00\x00\x00")
                        self.connection.close()
                    except Exception:
                        pass
                    return

                if step.delay:
                    time.sleep(step.delay)

                body = step.body
                if isinstance(body, str):
                    body = body.encode(step.encoding)

                # 用 send_response_only：父类的 send_response() 会自作主张补一个
                # Date 头，那样就永远测不出「服务器没给时间」这条分支。
                self.send_response_only(step.status)
                for key, value in step.headers.items():
                    if key.startswith("_"):
                        continue        # 下划线开头的是测试开关，不是真表头
                    self.send_header(key, value)
                if "Date" not in step.headers and not step.headers.get("_no_date"):
                    self.send_header("Date", self.date_time_string())
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            do_GET = _handle
            do_POST = _handle

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def url(self):
        host, port = self._httpd.server_address[:2]
        return "http://%s:%d/" % (host, port)

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

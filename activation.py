# -*- coding: utf-8 -*-
"""深大抢课助手 · 授权校验（可选功能）

只有「给大家用」那一份 exe 会带上这个：判断依据是打包时有没有把
`activation.json` 一起打进去。你自己用的那份不带这个文件，所以启动
**不弹口令、不联网、什么都不问**。

━━━━━━━━━━━━ 口令是怎么算出 来的 ━━━━━━━━━━━━
口令 = 由「密钥 + 日期 + 版本号」算出来的一串字符。这带来三件事：

  1. **打开要口令**：不知道密钥就猜不出口令；
  2. **口令能随时变**：换一天就换一个，你手里那个"生成器"（见
     auth_server/生成口令.bat）算的就是当天要发什么；
  3. **旧版会自然失效**：口令里掺了版本号——你一发新版的口令，
     旧 exe 拿自己的版本号去算，算出来永远是"不对"。
     所以不需要服务器也能做到"旧版崩坏"。

━━━━━━━━━━━━ 先说清两个弱点 ━━━━━━━━━━━━
  · **密钥在 exe 里，能脱壳的人可以挖出来**，进而自己造口令。对"同学之间
    互相传一传"这个场景够用；要真挡住破解，得上服务器或加壳（我不建议加壳，
    杀软误报会毁掉"别人拿到就能用"这件事）。
  · **这是靠"日期"对时**的：用户电脑时间被改（或时区不对）就会算不对口令。
    所以校验时**同时接受昨天和今天的口令**，留出容错。

━━━━━━━━━━━━ 另外还有一层（可选，能连上才生效）━━━━━━━━━━━━
`activation.json` 里可以配一个 `endpoint`（我给他部署的那个 Cloudflare 服务）。
配了的话，启动时会顺便问一句服务器；服务器可以说"这一版停用/这份副本停用"。
**关键：连不上服务器时一律放行**（只认离线口令），绝不因为网络问题把人锁在门外。
"""

import hashlib
import hmac
import json
import os
import random
import string
import sys
import time

CONFIG_NAME = "activation.json"
CACHE_NAME = "szu_grab_auth.json"
SERVER_TIMEOUT = 6.0


def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _resource(name: str) -> str:
    base = getattr(sys, "_MEIPASS", _app_dir())
    return os.path.join(base, name)


def load_config() -> dict:
    """读打包进来的授权配置。**文件不在就说明是"自己用"的那一份。**"""
    path = _resource(CONFIG_NAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


CONFIG = load_config()
ENABLED = bool(CONFIG.get("secret"))


def app_version() -> str:
    return str(CONFIG.get("version") or "2.0.0")


# --------------------------------------------------------------------------
# 口令
# --------------------------------------------------------------------------

ALPHABET = "".join(ch for ch in string.ascii_uppercase + string.digits
                   if ch not in "O0I1")          # 去掉易混的 0/O/1/I


def password_for(secret: str, day: str, version: str, length: int = 6) -> str:
    """算出「某一天 + 某个版本」的口令。生成器和 exe 用的是同一个函数。"""
    seed = "%s|%s" % (day, version)
    digest = hmac.new(secret.encode("utf-8"), seed.encode("utf-8"),
                      hashlib.sha256).digest()
    out = []
    for index in range(length):
        out.append(ALPHABET[digest[index] % len(ALPHABET)])
    return "".join(out)


def day_string(offset_days: int = 0) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time()
                                                   + offset_days * 86400))


def accepted_passwords(days_back: int = 1) -> list:
    """当前可用的口令（含昨天那份，容忍电脑时间/时区有点偏）。"""
    version = app_version()
    secret = CONFIG.get("secret", "")
    return [password_for(secret, day_string(-offset), version)
            for offset in range(days_back + 1)]


def check_password(typed: str) -> bool:
    """离线校验。大小写不敏感、首尾空格不算。"""
    typed = (typed or "").strip().upper()
    if not typed:
        return False
    return typed in accepted_passwords()


# --------------------------------------------------------------------------
# 本机记录（随机安装号 + 上次成功时间）——只为了"以后能单独停掉某一份副本"
# --------------------------------------------------------------------------

def _load_cache() -> dict:
    path = os.path.join(_app_dir(), CACHE_NAME)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(data: dict) -> None:
    try:
        with open(os.path.join(_app_dir(), CACHE_NAME), "w",
                  encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
    except Exception:
        pass


def install_id() -> str:
    """这台机器上这份副本的随机号（首次运行时生成）。

    用途只有一个：万一某一份被别人转出去乱传，你可以在服务端只停掉那一份。
    它**不包含任何硬件信息**，就是随机字符串，不涉及隐私。
    """
    cache = _load_cache()
    value = str(cache.get("install") or "")
    if not value:
        value = "".join(random.choice(string.ascii_lowercase + string.digits)
                        for _ in range(12))
        cache["install"] = value
        _save_cache(cache)
    return value


def mark_ok() -> None:
    cache = _load_cache()
    cache["last_ok"] = int(time.time())
    cache["version"] = app_version()
    cache["install"] = cache.get("install") or install_id()
    _save_cache(cache)


# --------------------------------------------------------------------------
# 可选的服务端校验：连不上就放行（绝不因为网络问题把人锁在外面）
# --------------------------------------------------------------------------

def server_verdict(password: str) -> str:
    """问一下服务器。返回 "ok" / "deny:<原因>" / ""（没配或连不上）。"""
    endpoint = str(CONFIG.get("endpoint") or "").strip()
    if not endpoint:
        return ""
    payload = json.dumps({"password": password, "version": app_version(),
                          "install": install_id()}).encode("utf-8")
    try:
        import requests
        response = requests.post(endpoint, data=payload, timeout=SERVER_TIMEOUT,
                                 headers={"Content-Type": "application/json"})
        data = response.json()
    except Exception:
        return ""                      # 连不上/看不懂 → 当没这回事，放行
    if data.get("ok"):
        return "ok"
    return "deny:" + str(data.get("msg") or "服务器说不能用")


def verify(typed: str):
    """总入口。返回 (能不能用, 给用户看的一句话)。

    顺序：先离线口令（永远可用），再看服务器（能连上才说话）。
    """
    if not check_password(typed):
        return False, "口令不对。找作者要当天的口令。"
    verdict = server_verdict(typed)
    if verdict.startswith("deny:"):
        return False, verdict[len("deny:"):]
    mark_ok()
    return True, ""

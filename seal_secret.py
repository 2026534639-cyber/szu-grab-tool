# -*- coding: utf-8 -*-
"""把 activation.json 里的明文密钥封进 activation.seal（仅打包「给大家用」时用）。

设计目标：
  · 分发的 exe 里**不再出现明文 secret**（字符串搜索挖不出来）；
  · 解包后即使找到 .seal 文件，也还要过 AES + 分散在代码里的派生材料；
  · 本地开发 / 生成口令仍读 activation.json（本机、不进 git）。

用法：
  python seal_secret.py          # 读 activation.json → 写 activation.seal
  python seal_secret.py --check  # 验证 seal 能解出与 json 一致的 secret
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "activation.json")
SEAL_PATH = os.path.join(HERE, "activation.seal")

# 派生材料故意拆成多段、不写成完整口令串——静态字符串搜索拿不到完整密钥。
# 改任何一段都会让旧 seal 解不开，需要重新 seal_secret.py。
_K1 = bytes([0x73, 0x7A, 0x75, 0x2D, 0x67, 0x72, 0x61, 0x62])  # "szu-grab"
_K2 = bytes([0x2F, 0x61, 0x75, 0x74, 0x68, 0x2F, 0x76, 0x32])  # "/auth/v2"
_K3 = bytes([0xC0, 0xDE, 0x71, 0xEE, 0x51, 0x67, 0x4E, 0x55])
_K4 = b"li-bu-jin-2026-protect"


def _material() -> bytes:
    return _K1 + _K2 + _K3 + _K4 + "|理不尽|深大抢课助手".encode("utf-8")


def derive_key(extra: bytes = b"") -> bytes:
    """从分散材料派生 32 字节 AES 密钥。"""
    return hashlib.pbkdf2_hmac(
        "sha256",
        _material() + extra,
        b"szu-grab-seal-v1",
        120000,
        dklen=32,
    )


def seal(secret: str, meta: dict) -> bytes:
    """返回可落盘的 seal 字节（magic + b64 json blob）。"""
    key = derive_key(str(meta.get("version") or "2.0.0").encode("utf-8"))
    nonce = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    # 额外绑定 version/period，防止把 seal 挪到别的版本配置上复用
    aad = json.dumps(
        {"v": meta.get("version"), "p": meta.get("period_days")},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    cipher.update(aad)
    ciphertext, tag = cipher.encrypt_and_digest(secret.encode("utf-8"))
    payload = {
        "n": base64.b64encode(nonce).decode("ascii"),
        "t": base64.b64encode(tag).decode("ascii"),
        "c": base64.b64encode(ciphertext).decode("ascii"),
        "a": base64.b64encode(aad).decode("ascii"),
        "version": meta.get("version"),
        "period_days": meta.get("period_days"),
        "endpoint": meta.get("endpoint") or "",
    }
    blob = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return b"SZUSEAL1\n" + blob + b"\n"


def unseal(raw: bytes) -> dict:
    """解 seal → {secret, version, period_days, endpoint}。失败抛 ValueError。"""
    if not raw.startswith(b"SZUSEAL1\n"):
        raise ValueError("seal magic 不对")
    body = raw.split(b"\n", 1)[1].strip()
    payload = json.loads(base64.b64decode(body).decode("utf-8"))
    version = str(payload.get("version") or "2.0.0")
    key = derive_key(version.encode("utf-8"))
    nonce = base64.b64decode(payload["n"])
    tag = base64.b64decode(payload["t"])
    ciphertext = base64.b64decode(payload["c"])
    aad = base64.b64decode(payload["a"])
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    cipher.update(aad)
    secret = cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
    return {
        "secret": secret,
        "version": version,
        "period_days": payload.get("period_days") or 7,
        "endpoint": payload.get("endpoint") or "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只验证，不重写")
    args = parser.parse_args()

    if not os.path.exists(JSON_PATH):
        print("找不到 activation.json：", JSON_PATH)
        return 1
    with open(JSON_PATH, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    secret = str(cfg.get("secret") or "")
    if not secret or secret.startswith("在这里填"):
        print("activation.json 里没有可用的 secret")
        return 1

    if args.check:
        if not os.path.exists(SEAL_PATH):
            print("没有 activation.seal")
            return 1
        with open(SEAL_PATH, "rb") as handle:
            got = unseal(handle.read())
        ok = got["secret"] == secret
        print("seal 解出 secret 与 json 一致：" , ok)
        print("version=", got["version"], "period=", got["period_days"])
        return 0 if ok else 2

    raw = seal(secret, cfg)
    with open(SEAL_PATH, "wb") as handle:
        handle.write(raw)
    # 立刻自检
    got = unseal(raw)
    assert got["secret"] == secret
    print("已写入", SEAL_PATH, "（%d 字节）" % len(raw))
    print("自检通过。打包「给大家用」时请带上 activation.seal，不要带 activation.json。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""打包后检查：activation.json 里的明文 secret 不得出现在 exe 字节里。"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist", "深大抢课助手.exe")
cfg = os.path.join(ROOT, "activation.json")
if not os.path.exists(cfg):
    print("没有 activation.json，跳过")
    sys.exit(0)
secret = str(json.load(open(cfg, encoding="utf-8")).get("secret") or "")
if not secret or len(secret) < 8:
    print("secret 太短，跳过")
    sys.exit(0)
data = open(exe, "rb").read()
hits = []
if secret.encode("utf-8") in data:
    hits.append("utf-8 原文")
if secret.encode("utf-16le") in data:
    hits.append("utf-16le 原文")
# also common json fragment
frag = ('"secret": "%s"' % secret).encode("utf-8")
if frag in data:
    hits.append("json 片段")
print("检查文件:", exe)
print("文件大小:", len(data))
if hits:
    print("FAIL 明文密钥出现在 exe 里：", "、".join(hits))
    sys.exit(1)
print("OK 明文密钥未出现在 exe 字节中")
# seal magic should be present for public
# onefile 会压缩资源，magic 不一定能被裸搜到；文件名字符串更稳
if b"SZUSEAL1" in data or b"activation.seal" in data:
    print("OK 含密封件（SZUSEAL1 或 activation.seal）")
else:
    print("WARN 未找到密封件痕迹（若是自己用那份可忽略）")
if b"ANTI_REVERSE" in data:
    print("OK 含拒解声明资源")
if b"seal_secret" in data or b"activation.cp312" in data:
    print("OK 含加固模块痕迹")
sys.exit(0)

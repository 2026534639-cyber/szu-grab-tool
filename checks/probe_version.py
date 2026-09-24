# -*- coding: utf-8 -*-
"""读 exe 的文件属性（版本信息）——用来验证打包时写进去的作者/版权在不在。"""

import sys

import win32api

exe = sys.argv[1]
try:
    win32api.GetFileVersionInfo(exe, "\\")
except Exception as error:
    print("这个 exe 里没有版本信息：%s" % error)
    sys.exit(1)

trans = win32api.GetFileVersionInfo(exe, r"\VarFileInfo\Translation")
lang, cp = trans[0]


def query(key):
    try:
        return win32api.GetFileVersionInfo(
            exe, r"\StringFileInfo\%04x%04x\%s" % (lang, cp, key))
    except Exception:
        return "(无)"


for key in ("ProductName", "CompanyName", "LegalCopyright", "FileVersion",
            "FileDescription"):
    print("  %-16s %s" % (key, query(key)))

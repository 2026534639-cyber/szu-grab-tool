# -*- coding: utf-8 -*-
"""第一层：静态与结构审计。

不装第三方工具，直接用标准库 ast 扫出这个项目真正在乎的几类问题：

  1. 导入了却没用到的名字
  2. self 属性只读未赋值（拼写错误的典型症状）
  3. self 属性赋值后从未被读
  4. 可变默认参数（def f(x=[]) 这种）
  5. 被吞掉的异常（except: pass）
  6. 函数定义了但全项目没人引用
  7. 重复的字典键、重复的元组字面量（3 个元素以上的才看）
  8. return/raise 之后还有语句

设计要点：两个源文件当成一个整体看（szu_grab_app 会用 szu_grabber 的函数，
反过来也一样），类方法算「已定义的属性」，「被当回调传递的名字」也算引用。
用法： python checks/ast_audit.py
退出码非 0 表示有需要人看一眼的东西。
"""

import ast
import builtins
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS = ("szu_grabber.py", "szu_grab_app.py")
BUILTIN_NAMES = set(dir(builtins))

# 这些名字来自标准库或框架，跨文件也看不到定义，直接放过
EXTERNAL_OK = {
    "annotations", "self", "super", "cls", "event", "text", "value", "node",
}

# tk.Tk / ttk 继承下来的方法：本文件里当然找不到赋值，属正常
INHERITED_OK = {
    "after", "after_cancel", "bell", "clipboard_get", "columnconfigure", "geometry",
    "iconbitmap", "iconphoto", "minsize", "rowconfigure", "title", "tk",
    "winfo_fpixels", "winfo_screenheight", "winfo_screenwidth", "deiconify", "lift",
    "destroy", "winfo_children", "wait_window", "update_idletasks", "config",
    "configure", "cget", "grid", "grid_remove", "pack", "place", "bind",
    "winfo_ismapped", "winfo_height", "winfo_width", "winfo_reqheight",
    "winfo_rooty", "winfo_class", "itemcget", "itemconfigure", "bbox",
    "canvasy", "yview", "yview_moveto", "yview_scroll", "create_window",
    "cget values",
}


def _name_of(node):
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _is_self_attr(node):
    return (isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self")


class Index:
    """把两个文件一起索引一遍。"""

    def __init__(self, trees):
        self.imported = {}          # name -> (file, lineno)
        self.defined_funcs = {}     # name -> (file, lineno, is_method)
        self.method_names = set()   # 所有类方法名
        self.referenced = set()     # 被读/被调用/被当值传递的名字
        self.attr_loaded = {}       # attr -> (file, lineno)
        self.attr_stored = {}       # attr -> (file, lineno)
        self.dynamic_attr = set()   # getattr(x, 变量) 出现过的文件里的字符串
        self.string_literals = {}   # file -> set(str)
        self.loaded_names = {}      # file -> set(name)

        for path, tree in trees:
            self._scan(path, tree)

    def _scan(self, path, tree):
        literals = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
        self.string_literals[path] = literals

        # 类方法名：类体里直接 def 的；类体里的赋值（如 _URL_RE）也算已定义
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.method_names.add(item.name)
                        self.defined_funcs.setdefault(
                            item.name, (path, item.lineno, True))
                    elif isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                self.attr_stored.setdefault(
                                    target.id, (path, item.lineno))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.imported[alias.asname or alias.name.split(".")[0]] = (
                        path, node.lineno)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    self.imported[alias.asname or alias.name] = (path, node.lineno)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.defined_funcs.setdefault(node.name, (path, node.lineno, False))
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Load):
                    self.referenced.add(node.id)
                else:
                    self.referenced.add(node.id)   # 赋值也算「这个名字被用到了」
            elif isinstance(node, ast.Attribute):
                # 只看 self.xxx 这一层：self.a.b() 里的 .b 不算本类的属性
                if _is_self_attr(node):
                    if isinstance(node.ctx, ast.Load):
                        self.attr_loaded.setdefault(node.attr, (path, node.lineno))
                    else:
                        self.attr_stored.setdefault(node.attr, (path, node.lineno))
                self.referenced.add(node.attr)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                    if len(node.args) >= 2 and not isinstance(
                            node.args[1], ast.Constant):
                        # getattr(obj, 变量)：目标名字写成了字符串，无法静态判断
                        self.dynamic_attr.add(path)

    def dynamically_reachable(self, path, name):
        return path in self.dynamic_attr and name in self.string_literals.get(path, ())


def audit(path, index):
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source, filename=path)
    findings = []

    # ---- 1. 导入但没用 ----
    for name, (where, lineno) in sorted(index.imported.items(), key=lambda kv: kv[1][1]):
        if where != path:
            continue
        if name in ("annotations",) or name.startswith("__"):
            continue
        if name not in index.referenced:
            findings.append(("导入未使用", lineno, "import %s" % name))

    # ---- 2. self 属性只读未赋值 ----
    for attr, (where, lineno) in sorted(index.attr_loaded.items()):
        if where != path:
            continue
        if attr in index.attr_stored or attr in index.method_names:
            continue
        if attr in BUILTIN_NAMES or attr in EXTERNAL_OK or attr in INHERITED_OK:
            continue
        if index.dynamically_reachable(path, attr):
            continue
        findings.append(("只被读、本类从没赋过值（疑似拼错）", lineno, "self.%s" % attr))

    # ---- 3. self 属性赋值后从未被读 ----
    for attr, (where, lineno) in sorted(index.attr_stored.items()):
        if where != path:
            continue
        # 任何对象身上同名属性被读过都算读过（比如 app 里读 grabber.style_switched）
        if attr in index.referenced or attr in EXTERNAL_OK:
            continue
        if index.dynamically_reachable(path, attr):
            continue
        findings.append(("只被赋值、全项目没读过", lineno, "self.%s" % attr))

    # ---- 4. 可变默认参数 ----
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defaults = list(node.args.defaults) + \
                [d for d in node.args.kw_defaults if d is not None]
            for default in defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    findings.append(("可变默认参数", node.lineno, node.name))
                elif isinstance(default, ast.Call) and _name_of(default.func) in (
                        "list", "dict", "set"):
                    findings.append(("可变默认参数", node.lineno, node.name))

    # ---- 5. 被吞掉的异常 ----
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            body = [item for item in handler.body
                    if not (isinstance(item, ast.Expr)
                            and isinstance(item.value, ast.Constant))]
            if not body:
                kind = "裸 except（连 Exception 都不写）" if handler.type is None \
                    else "except 块里什么都不做，异常被吞掉"
                findings.append((kind, handler.lineno, ""))

    # ---- 6. 定义了但全项目没人引用 ----
    for name, (where, lineno, is_method) in sorted(
            index.defined_funcs.items(), key=lambda kv: kv[1][1]):
        if where != path or name.startswith("__"):
            continue
        if name in index.referenced:
            continue
        if index.dynamically_reachable(path, name):
            continue
        findings.append(("定义后全项目未引用", lineno, name))

    # ---- 7. 重复的字典键 / 三元以上元组字面量 ----
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            seen = {}
            for key in node.keys:
                if isinstance(key, ast.Constant):
                    if key.value in seen:
                        findings.append(("字典键重复", key.lineno, repr(key.value)))
                    seen[key.value] = key.lineno
        if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) >= 3:
            seen = {}
            for item in node.elts:
                if isinstance(item, ast.Constant) and isinstance(
                        item.value, (str, int, float, bool)):
                    if item.value in seen:
                        findings.append(("元组/列表字面量里同值重复",
                                         item.lineno, repr(item.value)))
                    seen[item.value] = item.lineno

    # ---- 8. return/raise 之后还有语句 ----
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if not isinstance(block, list):
                continue
            for index_, item in enumerate(block[:-1]):
                if isinstance(item, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                    findings.append(("不可达代码（上一句就 return/raise 了）",
                                     block[index_ + 1].lineno, field))
                    break

    return findings


def main():
    trees = []
    for name in TARGETS:
        with open(os.path.join(ROOT, name), "r", encoding="utf-8") as handle:
            trees.append((name, ast.parse(handle.read(), filename=name)))
    index = Index(trees)

    total = 0
    for name in TARGETS:
        findings = audit(name, index)
        print("=" * 72)
        print("%s  →  %d 条待看" % (name, len(findings)))
        print("=" * 72)
        for kind, lineno, detail in findings:
            where = ("第 %d 行" % lineno) if lineno else ""
            print("  [%s] %s %s" % (kind, where, detail))
        if not findings:
            print("  （无）")
        print()
        total += len(findings)
    print("合计 %d 条。" % total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())

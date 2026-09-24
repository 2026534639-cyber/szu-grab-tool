# -*- coding: utf-8 -*-
"""把授权相关模块编成原生扩展（.pyd），抬高解包/反编译成本。

只编译：
  · seal_secret.py  —— 密钥派生与 AES 解封
  · activation.py   —— 口令算法

用法（在工程根目录）：
  python setup_harden.py build_ext --inplace

成功后目录里会出现 seal_secret*.pyd / activation*.pyd。
打包「给大家用」时优先带 .pyd；源 .py 可不再打进包。

说明：这是「提高成本」，不是绝对防破解。没有 Visual C++ 编译器时会失败，
build.bat 会自动退回纯 Python（仍有 seal 加密）。
"""

from setuptools import setup
from Cython.Build import cythonize

setup(
    name="szu_grab_harden",
    ext_modules=cythonize(
        ["seal_secret.py", "activation.py"],
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
        },
        annotate=False,
    ),
    zip_safe=False,
)

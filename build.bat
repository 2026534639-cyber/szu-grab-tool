@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   深大抢课助手 - 打包
echo   本版界面重做与打包：理不尽
echo   原作：Lewin671/YourLesson
echo         guiyi886/szu_grab_course
echo ============================================
echo.

echo [1/3] 检查依赖（requests / pyinstaller）...
python -m pip install --quiet --disable-pip-version-check requests pyinstaller
if errorlevel 1 (
    echo     依赖安装失败。如果是网络问题，可以先用国内镜像：
    echo     python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests pyinstaller
    pause
    exit /b 1
)

echo [2/3] 打包 exe（第一次会比较慢，几分钟）...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "深大抢课助手v2" ^
    --icon "szu_grab.ico" ^
    --add-data "szu_grab.ico;." ^
    --add-data "szu_grab.png;." ^
    --version-file "version_info.txt" ^
    szu_grab_app.py
if errorlevel 1 (
    echo     打包失败，看上面的报错。
    pause
    exit /b 1
)

echo [3/3] 导出使用说明（和程序里的帮助同一份内容）...
python -c "import szu_grab_app as m; open(r'dist/使用说明.txt','w',encoding='utf-8-sig').write(m.HELP_TEXT)"

if exist "dist\深大抢课助手v2.exe" (
    echo.
    echo ============================================
    echo   完成！产物在 dist 文件夹里：
    echo     dist\深大抢课助手v2.exe
    echo     dist\使用说明.txt
    echo ============================================
) else (
    echo 打包似乎没成功，dist 里没有 exe。
)
pause

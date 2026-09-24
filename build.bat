@echo off
setlocal
cd /d "%~dp0"

rem 用法:  build.bat            打包「自己用」的（不带口令门、不联网）
rem        build.bat public     打包「给大家用」的（带口令门，需要 activation.json）
rem
rem 两份用的是同一套源码，唯一区别是「给大家用」那份会把 activation.json
rem 一起打进去 —— 程序看到这个文件才会要口令。所以不会出现"两份代码不同步"。

set MODE=%1
if "%MODE%"=="" set MODE=self
if /i "%MODE%"=="self" goto do_self
if /i "%MODE%"=="public" goto do_public
echo 用法: build.bat [self^|public]
pause
exit /b 1

:do_self
set APPNAME=深大抢课助手_自己用
set ADDMODE=
set TXTNAME=使用说明_自己用
echo ============================================
echo   打包「自己用」的那份
echo   （不带口令门，不联网，双击就用）
echo ============================================
goto build

:do_public
set APPNAME=深大抢课助手
set ADDMODE=--add-data "activation.json;."
set TXTNAME=使用说明
echo ============================================
echo   打包「给大家用」的那份
echo   （启动要口令；口令用 auth_server\生成口令.bat 算）
echo ============================================
goto build

:build
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
    --name "%APPNAME%" ^
    --icon "szu_grab.ico" ^
    --add-data "szu_grab.ico;." ^
    --add-data "szu_grab.png;." ^
    --version-file "version_info.txt" ^
    %ADDMODE% ^
    szu_grab_app.py
if errorlevel 1 (
    echo     打包失败，看上面的报错。
    pause
    exit /b 1
)

echo [3/3] 导出使用说明（和程序里的帮助同一份内容）...
python -c "import szu_grab_app as m; open(r'dist/%TXTNAME%.txt','w',encoding='utf-8-sig').write(m.HELP_TEXT)"

echo.
echo ============================================
echo   完成！产物在 dist 文件夹里：
echo     dist\%APPNAME%.exe
echo ============================================
pause

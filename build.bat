@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem ── 深大抢课助手 · 打包 ────────────────────────────────────────────────
rem   build.bat all      一次做完两份并放到桌面（推荐，平时就用这个）
rem   build.bat public   只做「给大家用」那份（口令门 + 加固）
rem   build.bat self     只做「自己用」那份（免口令）
rem
rem 为什么要有 all：两份是同一套源码，但只有「给大家用」那份会打入口令门和
rem 加固件。以前改完代码要记得分别打两次，漏一次就会出现「我用的新版、
rem 别人用的旧版」——所以这里一条命令把两份都做完，并一起更新桌面。
rem ─────────────────────────────────────────────────────────────────────

set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"
set "DESK=%USERPROFILE%\Desktop"

set MODE=%~1
if "%MODE%"=="" set MODE=all
if /i "%MODE%"=="all" goto do_all
if /i "%MODE%"=="public" goto do_public
if /i "%MODE%"=="self" goto do_self
echo 用法: build.bat [all^|public^|self]
exit /b 1

:do_all
echo ============================================
echo   两份一起做：自己用 + 给大家用
echo ============================================
call "%~f0" public
if errorlevel 1 exit /b 1
call "%~f0" self
if errorlevel 1 exit /b 1
goto deliver

:do_public
set APPNAME=深大抢课助手
set TXTNAME=使用说明
set HARDEN=1
call :build_one
exit /b %ERRORLEVEL%

:do_self
set APPNAME=深大抢课助手_自己用
set TXTNAME=使用说明_自己用
set HARDEN=
call :build_one
exit /b %ERRORLEVEL%

:build_one
echo.
echo ---- 打包「%APPNAME%」----
echo [1] 依赖...
"%PY%" -m pip install --quiet --disable-pip-version-check requests pyinstaller pycryptodome setuptools wheel Cython
if errorlevel 1 exit /b 1

set ADDMODE=
if not defined HARDEN goto pack

echo [2] 密封密钥...
"%PY%" seal_secret.py
if errorlevel 1 exit /b 1
"%PY%" seal_secret.py --check
if errorlevel 1 exit /b 1

echo [3] 编译 .pyd（有 MinGW 才编）...
if exist "E:\msys64\mingw64\bin\gcc.exe" (
  set "PATH=E:\msys64\mingw64\bin;%SystemRoot%\system32;%SystemRoot%;D:\python;D:\python\Scripts"
  "%PY%" setup_harden.py build_ext --inplace --compiler=mingw32
) else (
  echo     没找到 MinGW，跳过 .pyd（仍有密封件）
)
set ADDMODE=--add-data "activation.seal;."
set ADDMODE=!ADDMODE! --add-data "ANTI_REVERSE_NOTICE.txt;."
if exist "activation.cp312-win_amd64.pyd" set ADDMODE=!ADDMODE! --add-binary "activation.cp312-win_amd64.pyd;."
if exist "seal_secret.cp312-win_amd64.pyd" set ADDMODE=!ADDMODE! --add-binary "seal_secret.cp312-win_amd64.pyd;."

:pack
echo [4] PyInstaller...
set STASHED=
if defined HARDEN (
  if exist activation.cp312-win_amd64.pyd if exist activation.py (
    ren activation.py activation.py.packbak
    set STASHED=1
  )
  if exist seal_secret.cp312-win_amd64.pyd if exist seal_secret.py (
    ren seal_secret.py seal_secret.py.packbak
  )
)
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed --noupx ^
  --name "%APPNAME%" ^
  --icon "szu_grab.ico" ^
  --add-data "szu_grab.ico;." ^
  --add-data "szu_grab.png;." ^
  --add-data "ANTI_REVERSE_NOTICE.txt;." ^
  --version-file "version_info.txt" ^
  --hidden-import Crypto --hidden-import Crypto.Cipher --hidden-import Crypto.Cipher.AES ^
  --hidden-import Crypto.Random --collect-submodules Crypto ^
  !ADDMODE! ^
  szu_grab_app.py
set ERR=!ERRORLEVEL!

if defined STASHED (
  if exist activation.py.packbak ren activation.py.packbak activation.py
  if exist seal_secret.py.packbak ren seal_secret.py.packbak seal_secret.py
)
if not "!ERR!"=="0" (
  echo     打包失败。
  exit /b 1
)

echo [5] 导出使用说明...
"%PY%" -c "import szu_grab_app as m; open(r'dist/%TXTNAME%.txt','w',encoding='utf-8-sig').write(m.HELP_TEXT)"

if defined HARDEN (
  echo [6] 明文密钥不得出现在 exe...
  "%PY%" checks/probe_no_plaintext_secret.py "dist\%APPNAME%.exe"
  if errorlevel 1 exit /b 1
)
exit /b 0

:deliver
echo.
echo ---- 更新桌面（两份一起）----
rem 桌面上的 exe 正在运行的话会覆盖失败：用 Python 检查。
rem （别用 tasklist + find —— find 会被 PATH 影响解析成 MSYS 的 GNU find，
rem   参数写法完全不同，会刷一屏 "No such file or directory"。）
"%PY%" checks\ensure_not_running.py
if errorlevel 1 (
  echo   请关掉上面说的那份，再跑一次 build.bat all。
  exit /b 1
)
copy /Y "dist\深大抢课助手.exe" "%DESK%\深大抢课助手.exe" >nul
copy /Y "dist\深大抢课助手_自己用.exe" "%DESK%\深大抢课助手_自己用.exe" >nul
copy /Y "dist\使用说明.txt" "%DESK%\深大抢课助手_使用说明.txt" >nul
echo.
echo ============================================
echo   两份都好了，桌面已更新：
echo     深大抢课助手.exe         （发给大家，要口令）
echo     深大抢课助手_自己用.exe  （你自己用，免口令）
echo     深大抢课助手_使用说明.txt
echo ============================================
exit /b 0

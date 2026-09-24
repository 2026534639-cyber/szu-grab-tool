@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem 强制使用 Windows Python，避免 PATH 里的 MSYS python 抢命令
set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"

set MODE=%~1
if "%MODE%"=="" set MODE=self
if /i "%MODE%"=="self" goto do_self
if /i "%MODE%"=="public" goto do_public
echo 用法: build.bat [self^|public]
exit /b 1

:do_self
set APPNAME=深大抢课助手_自己用
set TXTNAME=使用说明_自己用
set HARDEN=
set ADDMODE=
echo ============================================
echo   打包「自己用」（无口令）
echo ============================================
goto deps

:do_public
set APPNAME=深大抢课助手
set TXTNAME=使用说明
set HARDEN=1
echo ============================================
echo   打包「给大家用」（口令 + 加固）
echo ============================================
goto deps

:deps
echo.
echo [1] 依赖...
"%PY%" -m pip install --quiet --disable-pip-version-check requests pyinstaller pycryptodome setuptools wheel Cython
if errorlevel 1 exit /b 1

if not defined HARDEN goto pack

echo [1b] 密封密钥...
"%PY%" seal_secret.py
if errorlevel 1 exit /b 1
"%PY%" seal_secret.py --check
if errorlevel 1 exit /b 1

echo [1c] 编译 .pyd（MinGW）...
if exist "E:\msys64\mingw64\bin\gcc.exe" (
  set "PATH=E:\msys64\mingw64\bin;%SystemRoot%\system32;%SystemRoot%;D:\python;D:\python\Scripts"
  "%PY%" setup_harden.py build_ext --inplace --compiler=mingw32
) else (
  echo     无 MinGW，跳过 pyd
)

set ADDMODE=--add-data "activation.seal;."
set ADDMODE=!ADDMODE! --add-data "ANTI_REVERSE_NOTICE.txt;."
if exist "activation.cp312-win_amd64.pyd" set ADDMODE=!ADDMODE! --add-binary "activation.cp312-win_amd64.pyd;."
if exist "seal_secret.cp312-win_amd64.pyd" set ADDMODE=!ADDMODE! --add-binary "seal_secret.cp312-win_amd64.pyd;."

:pack
echo [2] PyInstaller...
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
set ERR=%ERRORLEVEL%

if defined STASHED (
  if exist activation.py.packbak ren activation.py.packbak activation.py
  if exist seal_secret.py.packbak ren seal_secret.py.packbak seal_secret.py
)

if not "%ERR%"=="0" (
  echo 打包失败
  exit /b 1
)

echo [3] 导出说明...
"%PY%" -c "import szu_grab_app as m; open(r'dist/%TXTNAME%.txt','w',encoding='utf-8-sig').write(m.HELP_TEXT)"

if defined HARDEN (
  echo [4] 明文密钥不得出现在 exe...
  "%PY%" checks/probe_no_plaintext_secret.py "dist\%APPNAME%.exe"
  if errorlevel 1 exit /b 1
)

echo.
echo 完成: dist\%APPNAME%.exe
exit /b 0

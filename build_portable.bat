@echo off
rem Builds the PORTABLE version: dist\Another-Video-Downloader-Portable.exe with yt-dlp, Pillow, ffmpeg and an icon included.
rem Put this file, make_icon.py and the fonts folder next to yt_downloader.py, then double-click it.
rem ffmpeg.exe and ffprobe.exe are used from this folder if present,
rem otherwise they are downloaded once from gyan.dev (about 90 MB).
rem deno.exe (JavaScript runtime, required by YouTube for full speed) is downloaded once from GitHub if missing.

python -m pip install -U pyinstaller "yt-dlp[default]" pillow pystray
if errorlevel 1 (
  echo pip failed.
  pause
  exit /b 1
)

python make_icon.py
if not exist icon.ico (
  echo icon.ico could not be created - is make_icon.py next to this file?
  pause
  exit /b 1
)

set NEED=0
if not exist ffmpeg.exe set NEED=1
if not exist ffprobe.exe set NEED=1
if "%NEED%"=="1" (
  echo Downloading ffmpeg, please wait...
  powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile ffmpeg_dl.zip; Expand-Archive ffmpeg_dl.zip -DestinationPath ffmpeg_dl -Force; Get-ChildItem ffmpeg_dl -Recurse -Include ffmpeg.exe,ffprobe.exe | Copy-Item -Destination .; Remove-Item ffmpeg_dl.zip; Remove-Item ffmpeg_dl -Recurse -Force"
)
if not exist ffmpeg.exe (
  echo ffmpeg.exe not found. Put ffmpeg.exe and ffprobe.exe next to this file and retry.
  pause
  exit /b 1
)
if not exist ffprobe.exe (
  echo ffprobe.exe not found. Put ffmpeg.exe and ffprobe.exe next to this file and retry.
  pause
  exit /b 1
)

if not exist deno.exe (
  echo Downloading Deno ^(JavaScript runtime needed by YouTube^), please wait...
  powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip' -OutFile deno_dl.zip; Expand-Archive deno_dl.zip -DestinationPath deno_dl -Force; Get-ChildItem deno_dl -Recurse -Include deno.exe | Copy-Item -Destination .; Remove-Item deno_dl.zip; Remove-Item deno_dl -Recurse -Force"
)
if not exist deno.exe (
  echo deno.exe not found. Download it from https://github.com/denoland/deno/releases and put it next to this file.
  pause
  exit /b 1
)

python -m PyInstaller --noconfirm --clean --onefile --windowed --name "Another-Video-Downloader-Portable" --icon icon.ico --add-data "icon.ico;." --add-data "fonts;fonts" --collect-all yt_dlp --collect-all yt_dlp_ejs --hidden-import pystray._win32 --add-binary "ffmpeg.exe;." --add-binary "ffprobe.exe;." --add-binary "deno.exe;." yt_downloader.py
if errorlevel 1 (
  echo PyInstaller failed.
  pause
  exit /b 1
)

echo.
echo Done: dist\Another-Video-Downloader-Portable.exe
pause

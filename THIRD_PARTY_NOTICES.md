# Third-party software / Logiciels tiers

Another Video Downloader is released under the MIT license (see `LICENSE`). It uses the following projects, each under its own license:

| Project | Use | License |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Downloads (installed through pip) | The Unlicense (public domain) |
| [Pillow](https://python-pillow.org/) | Images, icons, thumbnails | MIT-CMU (HPND) |
| [pystray](https://github.com/moses-palmer/pystray) | Notification-area icon (optional) | LGPL-3.0 |
| [Sora](https://github.com/sora-xor/sora-font) | Font (`fonts/`, license in `fonts/OFL.txt`) | SIL Open Font License 1.1 |
| [FFmpeg](https://ffmpeg.org/) | Merging, MP3 conversion, trimming | LGPL-2.1+ / GPL-2+ depending on the build |
| Python, Tk | Runtime and interface | PSF License / Tcl-Tk license |

## FFmpeg

The source code of this repository does **not** contain FFmpeg. `build_exe.bat` downloads the "essentials" build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (GPLv3) and packs it into the `.exe` it creates. If you distribute such an `.exe`, you must comply with FFmpeg's license: see <https://ffmpeg.org/legal.html>; the FFmpeg source code is available at <https://ffmpeg.org/download.html>. You can also publish an `.exe` without ffmpeg and let users install it themselves (`winget install ffmpeg`).

## pystray

pystray is LGPL-3.0 and is used as an unmodified library (imported, installed through pip). Users can replace it freely.

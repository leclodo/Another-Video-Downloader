# Another Video Downloader

**FR** · [English below](#english)

Une interface graphique simple pour [yt-dlp](https://github.com/yt-dlp/yt-dlp) : colle un lien, choisis la qualité, télécharge. Pour Windows (Python + Tkinter), libre et open source.

## Fonctions

- **Téléchargement** de vidéos YouTube et des autres sites pris en charge par yt-dlp, en qualité au choix ou en **MP3**
- **File d'attente** : plusieurs téléchargements, pause / reprise, réordonnancement par glisser-déposer, tri par colonne, sauvegarde automatique de la file entre deux lancements
- **Découpe** (début / fin) avant ou après l'ajout à la file ; un lien avec un timer (`?t=90`) préremplit le début
- **Playlists** : ajout de toute la playlist en une fois
- **Directs (lives)** : enregistrement « depuis le début » ou « maintenant », arrêt propre qui produit un MP4 lisible
- **Miniatures** : aperçu en grand avec zoom, enregistrement en qualité maximale (clic droit)
- **Nom de fichier** personnalisable (`{title}`, `{channel}`, `{length}`, `{date}`, `{views}`), limite de vitesse, détection des fichiers déjà téléchargés
- **Notifications** : son et bulle de fin de téléchargement, son d'erreur, 3 styles de bulle, volume réglable
- **Thèmes** : sombre, clair, sakura, cyberpunk, hacker ; **français / anglais**
- **Fenêtre de logs** pour le débogage, réduction dans la zone de notification

## Installation

### Option 1 : l'exécutable (le plus simple)

Télécharge `Another Video Downloader.exe` dans l'onglet [**Releases**](../../releases) et lance-le. Rien d'autre à installer.

### Option 2 : depuis les sources

Prérequis : Python 3.10+ et [ffmpeg](https://ffmpeg.org/) (pour le MP3, la découpe et la fusion vidéo + audio).

```bash
pip install -r requirements.txt
winget install ffmpeg        # si ffmpeg n'est pas déjà installé
python yt_downloader.py
```

### Créer l'exécutable soi-même

Double-clique sur `build_exe.bat` (Windows). Il installe PyInstaller, télécharge ffmpeg si besoin et crée `dist\Another Video Downloader.exe`.

## Données

Les réglages et la file d'attente sont enregistrés dans `%APPDATA%\Another Video Downloader\`.

## Avertissement

Cet outil sert à télécharger des contenus dont tu as le droit de faire une copie (tes propres vidéos, contenus sous licence libre, usage privé autorisé dans ton pays, etc.). Respecte le droit d'auteur et les conditions d'utilisation des sites. Les auteurs déclinent toute responsabilité quant à l'usage qui en est fait.

## Licence

[MIT](LICENSE) © 2026 le-clodo. Les logiciels tiers (yt-dlp, FFmpeg, Pillow, pystray, police Sora) gardent leurs propres licences : voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

<a name="english"></a>
## English

A simple graphical interface for [yt-dlp](https://github.com/yt-dlp/yt-dlp): paste a link, pick a quality, download. For Windows (Python + Tkinter), free and open source.

### Features

- **Downloads** from YouTube and every site supported by yt-dlp, in the quality of your choice or as **MP3**
- **Queue**: several downloads, pause / resume, drag-and-drop reordering, sorting by column, queue saved automatically between launches
- **Trimming** (start / end) before or after adding to the queue; a link with a timestamp (`?t=90`) pre-fills the start
- **Playlists**: add a whole playlist at once
- **Live streams**: record "from the start" or "from now", clean stop that produces a playable MP4
- **Thumbnails**: large preview with zoom, save in the highest quality (right click)
- Customizable **file names** (`{title}`, `{channel}`, `{length}`, `{date}`, `{views}`), speed limit, detection of already downloaded files
- **Notifications**: sound and popup when a download finishes, error sound, 3 popup styles, adjustable volume
- **Themes**: dark, light, sakura, cyberpunk, hacker; **French / English**
- **Log window** for debugging, minimize to the notification area

### Install

**Executable (easiest):** download `Another Video Downloader.exe` from [**Releases**](../../releases) and run it.

**From source:** Python 3.10+ and [ffmpeg](https://ffmpeg.org/) (MP3, trimming, video + audio merge).

```bash
pip install -r requirements.txt
winget install ffmpeg        # if ffmpeg is not installed yet
python yt_downloader.py
```

**Build the .exe yourself:** double-click `build_exe.bat` (Windows). It installs PyInstaller, downloads ffmpeg if needed and creates `dist\Another Video Downloader.exe`.

### Data

Settings and the queue are stored in `%APPDATA%\Another Video Downloader\`.

### Disclaimer

Use this tool only for content you are allowed to copy (your own videos, freely licensed content, private use where your country allows it, etc.). Respect copyright and the terms of service of the sites. The authors accept no responsibility for how it is used.

### License

[MIT](LICENSE) © 2026 le-clodo. Third-party software (yt-dlp, FFmpeg, Pillow, pystray, Sora font) keeps its own license: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

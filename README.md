# Another Video Downloader

<img width="1082" height="596" alt="image" src="https://github.com/user-attachments/assets/b280e8ff-021a-49e6-b5fb-beb94eb31211" />


**FR** · [English below](#english)

Une interface graphique simple pour [yt-dlp](https://github.com/yt-dlp/yt-dlp) : colle un lien, choisis la qualité, télécharge. Pour Windows (Python + Tkinter), libre et open source.

## Fonctions

### Téléchargement
- Vidéos YouTube et **plus de mille autres sites** pris en charge par yt-dlp (liste consultable dans l'appli), en qualité au choix (jusqu'à la meilleure disponible) ou en **MP3**
- **Choix du codec** : H.264, VP9 ou AV1. Le mode **compatible montage** (H.264 + AAC) garantit des fichiers lisibles dans Premiere et les autres logiciels de montage, avec ré-encodage automatique si besoin
- **Taille et durée estimées** avant de lancer, **limite de vitesse** réglable (et fiable), **nouvelles tentatives automatiques** en cas d'erreur réseau
- **Rapide** : téléchargement en fragments parallèles, Deno inclus pour éviter le ralentissement de YouTube, reconnexion automatique quand une connexion est bridée
- Dossier d'enregistrement au choix, **nom de fichier personnalisable** (`{title}`, `{channel}`, `{length}`, `{date}`, `{views}`), renommage d'un fichier, **détection des doublons** (déjà dans la file, déjà téléchargé, déjà dans le dossier)
- Fichiers de travail dans un dossier temporaire caché par vidéo : le dossier choisi reste propre

### Découpe (trim)
- Début / fin avant ou après l'ajout à la file, modifiable à tout moment ; un lien avec un timer (`?t=90`) préremplit le début
- Réglage **Précise / Rapide** : *Rapide* (par défaut) coupe sur les images clés sans ré-encoder, *Précise* coupe à l'image près
- **VODs Twitch très rapides** : seuls les segments utiles sont téléchargés en parallèle (8 à la fois), puis assemblés avec ffmpeg ; retour automatique à yt-dlp en cas d'échec

### File d'attente et playlists
- Plusieurs téléchargements, pause / reprise, réordonnancement par glisser-déposer, tri par colonne, sauvegarde automatique entre deux lancements
- **Playlists** : ajout de toute la playlist ou **choix des vidéos** (cases à cocher, tout cocher / décocher) ; une barre de couleur regroupe les vidéos d'une même playlist
- **Options de file** : démarrage programmé à une heure donnée, et action à la fin (ne rien faire, mise en veille ou extinction du PC)
- Miniatures dans la file, bouton pour copier le lien d'une vidéo, vitesse affichée lissée, progression en pourcentage y compris pendant la fusion et la conversion

### Directs (lives)
- Enregistrement « depuis le début » ou « à partir de maintenant », arrêt propre qui produit un MP4 lisible

### Historique, miniatures, cookies
- **Historique** des téléchargements, avec recherche, tri récents / anciens, ouverture du fichier ou du dossier
- **Miniatures** : aperçu en grand avec zoom, enregistrement en qualité maximale (clic droit)
- **Cookies** (Firefox, ou fichier `cookies.txt` importé pour Chrome / Edge / Brave) utilisés seulement quand une vidéo demande une connexion (privée, +18, membres)

### Interface
- **Thèmes** : sombre, clair, sakura, cyberpunk, hacker ; **français / anglais** ; format de date au choix
- **Notifications** : son et bulle de fin de téléchargement, 3 styles de bulle, 4 mélodies, son d'erreur, volume réglable
- Réduction dans la zone de notification (ou quitter à la fermeture), instance unique (relancer l'appli réaffiche la fenêtre)
- **Mises à jour en un clic** depuis la fenêtre Infos (GitHub)
- **Fenêtre de logs** conservés entre les sessions (avec détection des plantages) et utilisation de la RAM et du CPU affichée dans l'en-tête
- **Confidentialité** : aucune donnée collectée ni partagée, tout reste sur ton PC

## Installation

### Option 1 : l'exécutable (le plus simple)

Télécharge `Another-Video-Downloader-Installer.exe` dans l'onglet [**Releases**](../../releases) et lance-le (installation sans droits administrateur, raccourci dans le menu démarrer). Mises à jour en un clic depuis la fenêtre **Infos**.

### Option 2 : depuis les sources

Prérequis : Python 3.10+ et [ffmpeg](https://ffmpeg.org/) (pour le MP3, la découpe et la fusion vidéo + audio).

```bash
pip install -r requirements.txt
winget install ffmpeg        # si ffmpeg n'est pas déjà installé
python yt_downloader.py
```

### Créer l'exécutable soi-même

Installeur : installe [Inno Setup 6](https://jrsoftware.org/isdl.php) puis double-clique sur `build_installer.bat` (crée `dist\Another-Video-Downloader-Installer.exe`). Version portable : `build_portable.bat` (crée `dist\Another-Video-Downloader-Portable.exe`). Dans les deux cas, PyInstaller est installé et ffmpeg et Deno (nécessaire à YouTube pour la vitesse) téléchargés si besoin.

## Données

Les réglages, la file d'attente, l'historique et les logs (`logs.txt`) sont enregistrés dans `%APPDATA%\Another Video Downloader\`.

## Avertissement

Cet outil sert à télécharger des contenus dont tu as le droit de faire une copie (tes propres vidéos, contenus sous licence libre, usage privé autorisé dans ton pays, etc.). Respecte le droit d'auteur et les conditions d'utilisation des sites. Les auteurs déclinent toute responsabilité quant à l'usage qui en est fait.

## Licence

[MIT](LICENSE) © 2026 le-clodo. Les logiciels tiers (yt-dlp, FFmpeg, Pillow, pystray, police Sora) gardent leurs propres licences : voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

<a name="english"></a>
## English

A simple graphical interface for [yt-dlp](https://github.com/yt-dlp/yt-dlp): paste a link, pick a quality, download. For Windows (Python + Tkinter), free and open source.

### Features

#### Downloading
- YouTube and **over a thousand other sites** supported by yt-dlp (list available in the app), in the quality of your choice (up to the best available) or as **MP3**
- **Codec choice**: H.264, VP9 or AV1. The **editing-compatible** mode (H.264 + AAC) guarantees files that open in Premiere and other editors, with automatic re-encoding when needed
- **Estimated size and time** before starting, adjustable (and reliable) **speed limit**, **automatic retries** on network errors
- **Fast**: parallel fragment downloads, Deno bundled to avoid YouTube slowdowns, automatic reconnection when a connection is throttled
- Chosen output folder, **customizable file names** (`{title}`, `{channel}`, `{length}`, `{date}`, `{views}`), file renaming, **duplicate detection** (already in the queue, already downloaded, already in the folder)
- Work files go to a hidden per-video temporary folder: your chosen folder stays clean

#### Trimming
- Start / end before or after adding to the queue, editable at any time; a link with a timestamp (`?t=90`) pre-fills the start
- **Precise / Fast** setting: *Fast* (default) cuts on keyframes without re-encoding, *Precise* cuts frame-accurately
- **Very fast Twitch VODs**: only the needed segments are downloaded in parallel (8 at a time), then assembled with ffmpeg; automatic fallback to yt-dlp if it fails

#### Queue and playlists
- Several downloads, pause / resume, drag-and-drop reordering, sorting by column, saved automatically between launches
- **Playlists**: add the whole playlist or **pick the videos** (checkboxes, select / clear all); a colour bar groups the videos of one playlist
- **Queue options**: scheduled start at a given time, and an action when finished (nothing, sleep or shut down the PC)
- Thumbnails in the queue, button to copy a video's link, smoothed speed display, percentage progress including during merging and conversion

#### Live streams
- Record "from the start" or "from now", clean stop that produces a playable MP4

#### History, thumbnails, cookies
- Download **history** with search, newest / oldest sorting, open the file or its folder
- **Thumbnails**: large preview with zoom, save in the highest quality (right click)
- **Cookies** (Firefox, or an imported `cookies.txt` for Chrome / Edge / Brave) used only when a video requires login (private, age-restricted, members-only)

#### Interface
- **Themes**: dark, light, sakura, cyberpunk, hacker; **French / English**; date format of your choice
- **Notifications**: sound and popup when a download finishes, 3 popup styles, 4 melodies, error sound, adjustable volume
- Minimize to the notification area (or quit on close), single instance (relaunching shows the existing window)
- **One-click updates** from the Info window (GitHub)
- **Log window** kept between sessions (with crash detection) and RAM / CPU usage shown in the header
- **Privacy**: no data is collected or shared, everything stays on your PC

### Install

**Installer (easiest):** download `Another-Video-Downloader-Installer.exe` from [**Releases**](../../releases) and run it (no admin rights needed, Start menu shortcut). One-click updates from the **Info** window.

**From source:** Python 3.10+ and [ffmpeg](https://ffmpeg.org/) (MP3, trimming, video + audio merge).

```bash
pip install -r requirements.txt
winget install ffmpeg        # if ffmpeg is not installed yet
python yt_downloader.py
```

**Build it yourself:** installer: install [Inno Setup 6](https://jrsoftware.org/isdl.php), then double-click `build_installer.bat` (creates `dist\Another-Video-Downloader-Installer.exe`). Portable: `build_portable.bat` (creates `dist\Another-Video-Downloader-Portable.exe`). Both install PyInstaller and download ffmpeg and Deno (needed by YouTube for full speed) if needed.

### Data

Settings, the queue, the history and the logs (`logs.txt`) are stored in `%APPDATA%\Another Video Downloader\`.

### Disclaimer

Use this tool only for content you are allowed to copy (your own videos, freely licensed content, private use where your country allows it, etc.). Respect copyright and the terms of service of the sites. The authors accept no responsibility for how it is used.

### License

[MIT](LICENSE) © 2026 le-clodo. Third-party software (yt-dlp, FFmpeg, Pillow, pystray, Sora font) keeps its own license: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

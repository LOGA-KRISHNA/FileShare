# SessionShare — Python Local File Sharing (up to 1 GB)

A lightweight, session-based file sharing server. Files are served only
while the Python process is running and auto-expire after 8 hours.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server
python app.py

# 3. Open in browser
http://localhost:5000
```

## Features

| Feature | Detail |
|---|---|
| Max file size | **1 GB** per file |
| File formats | **Any** (PDF, video, zip, docx, …) |
| Storage | Local `session_uploads/` folder |
| Share links | Copyable download URL per file |
| Auto-expiry | 8 hours after upload |
| Multi-upload | Yes — upload several files at once |
| Download counter | Tracks how many times each file was downloaded |

## Sharing with others on the same network

Replace `localhost` with your LAN IP address, e.g.:

```
http://192.168.1.42:5000
```

Find your IP with `ipconfig` (Windows) or `ifconfig / ip a` (Linux/Mac).

## Notes

- Files are **deleted permanently** when the server stops or expires.
- No database needed — everything is in memory.
- For internet-wide sharing, expose the port via ngrok or similar.
"""
SessionShare - File Sharing App (up to 1 GB per file)
Run: python app.py
Then open: http://localhost:5000
Files are available only during the server session (cleared on restart).
"""

import os
import uuid
import time
import threading
from pathlib import Path
from datetime import datetime
from flask import (
    Flask, request, jsonify, send_from_directory,
    render_template_string, abort
)
from werkzeug.utils import secure_filename

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
UPLOAD_FOLDER = Path("session_uploads")
MAX_FILE_SIZE  = 1 * 1024 * 1024 * 1024   # 1 GB
SESSION_TTL    = 3600 * 8                  # 8 hours (seconds)

UPLOAD_FOLDER.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)

# In-memory registry: { file_id: { name, path, size, uploaded_at, downloads } }
file_registry: dict = {}
registry_lock = threading.Lock()


# ──────────────────────────────────────────────
# Background cleanup (removes expired files)
# ──────────────────────────────────────────────
def _cleanup_loop():
    while True:
        time.sleep(300)  # check every 5 min
        now = time.time()
        with registry_lock:
            expired = [fid for fid, info in file_registry.items()
                       if now - info["uploaded_at"] > SESSION_TTL]
            for fid in expired:
                try:
                    Path(file_registry[fid]["path"]).unlink(missing_ok=True)
                except Exception:
                    pass
                del file_registry[fid]

threading.Thread(target=_cleanup_loop, daemon=True).start()


# ──────────────────────────────────────────────
# HTML Template
# ──────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>SessionShare</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Syne:wght@700;800&display=swap" rel="stylesheet"/>
<style>
  :root {
    --bg:      #0c0e10;
    --surface: #13161a;
    --border:  #252830;
    --accent:  #00e5a0;
    --accent2: #6c63ff;
    --text:    #e8eaf0;
    --muted:   #6b7080;
    --danger:  #ff4f6d;
    --radius:  12px;
    --mono: 'DM Mono', monospace;
    --head: 'Syne', sans-serif;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--mono);
    min-height: 100vh;
    padding: 32px 16px 64px;
  }

  /* ── grid noise texture ── */
  body::before {
    content: '';
    position: fixed; inset: 0;
    background-image:
      linear-gradient(rgba(0,229,160,.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,229,160,.03) 1px, transparent 1px);
    background-size: 32px 32px;
    pointer-events: none; z-index: 0;
  }

  .wrap { max-width: 800px; margin: 0 auto; position: relative; z-index: 1; }

  /* ── header ── */
  header { text-align: center; margin-bottom: 48px; }
  .logo { font-family: var(--head); font-size: 2.6rem; font-weight: 800;
          background: linear-gradient(135deg, var(--accent), var(--accent2));
          -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
  .tagline { color: var(--muted); font-size: .82rem; margin-top: 6px; letter-spacing: .08em; }

  /* ── card ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 32px;
    margin-bottom: 28px;
  }
  .card-title {
    font-family: var(--head);
    font-size: 1rem; font-weight: 700;
    color: var(--accent); letter-spacing: .06em;
    margin-bottom: 20px; text-transform: uppercase;
  }

  /* ── drop zone ── */
  #dropzone {
    border: 2px dashed var(--border);
    border-radius: var(--radius);
    padding: 48px 24px;
    text-align: center;
    cursor: pointer;
    transition: border-color .2s, background .2s;
    position: relative;
  }
  #dropzone.over, #dropzone:hover {
    border-color: var(--accent);
    background: rgba(0,229,160,.04);
  }
  #dropzone input[type=file] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }
  .dz-icon { font-size: 2.4rem; margin-bottom: 12px; }
  .dz-hint { color: var(--muted); font-size: .82rem; margin-top: 6px; }
  .dz-limit { color: var(--accent2); font-size: .78rem; margin-top: 4px; }

  /* ── progress ── */
  #progress-wrap { margin-top: 20px; display: none; }
  #progress-label { font-size: .8rem; color: var(--muted); margin-bottom: 6px; }
  #progress-bar-bg {
    background: var(--border); border-radius: 99px; height: 8px; overflow: hidden;
  }
  #progress-bar {
    height: 100%; width: 0%;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    border-radius: 99px; transition: width .15s;
  }
  #progress-pct { font-size: .78rem; color: var(--accent); margin-top: 4px; text-align: right; }

  /* ── upload btn ── */
  #upload-btn {
    margin-top: 20px; width: 100%; padding: 14px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    color: #0c0e10; font-family: var(--head); font-size: .95rem; font-weight: 700;
    border: none; border-radius: var(--radius); cursor: pointer;
    letter-spacing: .04em; transition: opacity .2s, transform .1s;
  }
  #upload-btn:hover { opacity: .9; }
  #upload-btn:active { transform: scale(.98); }
  #upload-btn:disabled { opacity: .4; cursor: not-allowed; }

  /* ── message ── */
  #msg { margin-top: 16px; font-size: .85rem; min-height: 20px; }
  #msg.ok  { color: var(--accent); }
  #msg.err { color: var(--danger); }

  /* ── file table ── */
  table { width: 100%; border-collapse: collapse; font-size: .82rem; }
  th { color: var(--muted); font-weight: 500; text-align: left; padding: 8px 10px;
       border-bottom: 1px solid var(--border); }
  td { padding: 10px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(255,255,255,.015); }

  .fname { color: var(--text); word-break: break-all; }
  .fsize { color: var(--muted); white-space: nowrap; }
  .ftime { color: var(--muted); font-size: .75rem; }

  .btn-copy, .btn-dl, .btn-del {
    padding: 5px 10px; border-radius: 6px; border: 1px solid;
    font-family: var(--mono); font-size: .75rem; cursor: pointer;
    transition: background .15s; white-space: nowrap;
  }
  .btn-copy { border-color: var(--accent2); color: var(--accent2); background: transparent; }
  .btn-copy:hover { background: rgba(108,99,255,.15); }
  .btn-dl   { border-color: var(--accent);  color: var(--accent);  background: transparent; margin-left: 4px; }
  .btn-dl:hover   { background: rgba(0,229,160,.1); }
  .btn-del  { border-color: var(--danger);  color: var(--danger);  background: transparent; margin-left: 4px; }
  .btn-del:hover  { background: rgba(255,79,109,.1); }

  .empty-row td { text-align: center; color: var(--muted); padding: 32px; }

  /* ── share toast ── */
  #toast {
    position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%) translateY(80px);
    background: var(--accent); color: #0c0e10;
    font-family: var(--head); font-size: .85rem; font-weight: 700;
    padding: 10px 22px; border-radius: 99px;
    transition: transform .3s cubic-bezier(.34,1.56,.64,1), opacity .3s;
    opacity: 0; pointer-events: none; z-index: 999;
  }
  #toast.show { transform: translateX(-50%) translateY(0); opacity: 1; }

  /* ── footer ── */
  footer { text-align: center; color: var(--muted); font-size: .75rem; margin-top: 40px; }
  footer span { color: var(--accent); }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">SessionShare</div>
    <div class="tagline">// instant · local · session-only file sharing  ·  up to 1 GB</div>
  </header>

  <!-- Upload Card -->
  <div class="card">
    <div class="card-title">↑ Upload File</div>
    <div id="dropzone">
      <input type="file" id="file-input" multiple/>
      <div class="dz-icon">📁</div>
      <div>Drop files here or <strong style="color:var(--accent)">click to browse</strong></div>
      <div class="dz-hint">Any file format supported</div>
      <div class="dz-limit">Max 1 GB per file</div>
    </div>

    <div id="progress-wrap">
      <div id="progress-label">Uploading…</div>
      <div id="progress-bar-bg"><div id="progress-bar"></div></div>
      <div id="progress-pct">0%</div>
    </div>

    <button id="upload-btn" disabled>Select a file first</button>
    <div id="msg"></div>
  </div>

  <!-- Files Card -->
  <div class="card">
    <div class="card-title">📂 Shared Files This Session</div>
    <table id="file-table">
      <thead>
        <tr>
          <th>File</th><th>Size</th><th>Uploaded</th><th>DL</th><th>Actions</th>
        </tr>
      </thead>
      <tbody id="file-body">
        <tr class="empty-row"><td colspan="5">No files shared yet.</td></tr>
      </tbody>
    </table>
  </div>

  <footer>Files auto-expire after <span>8 hours</span> · data never leaves your machine</footer>
</div>

<div id="toast">Link copied!</div>

<script>
const fileInput   = document.getElementById('file-input');
const dropzone    = document.getElementById('dropzone');
const uploadBtn   = document.getElementById('upload-btn');
const progressWrap= document.getElementById('progress-wrap');
const progressBar = document.getElementById('progress-bar');
const progressPct = document.getElementById('progress-pct');
const msgEl       = document.getElementById('msg');
const fileBody    = document.getElementById('file-body');
const toast       = document.getElementById('toast');

let selectedFiles = [];

// ── drag & drop ──
dropzone.addEventListener('dragover', e => { e.preventDefault(); dropzone.classList.add('over'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('over'));
dropzone.addEventListener('drop', e => {
  e.preventDefault(); dropzone.classList.remove('over');
  if (e.dataTransfer.files.length) { fileInput.files = e.dataTransfer.files; handleFileSelect(); }
});

fileInput.addEventListener('change', handleFileSelect);

function handleFileSelect() {
  selectedFiles = Array.from(fileInput.files);
  if (!selectedFiles.length) return;
  const names = selectedFiles.map(f => f.name).join(', ');
  uploadBtn.disabled = false;
  uploadBtn.textContent = `Upload ${selectedFiles.length > 1 ? selectedFiles.length + ' files' : '"' + selectedFiles[0].name + '"'}`;
  setMsg('', '');
}

uploadBtn.addEventListener('click', uploadFiles);

async function uploadFiles() {
  if (!selectedFiles.length) return;
  uploadBtn.disabled = true;
  progressWrap.style.display = 'block';

  for (let i = 0; i < selectedFiles.length; i++) {
    const file = selectedFiles[i];
    setMsg('', '');
    progressBar.style.width = '0%';
    progressPct.textContent = '0%';
    document.getElementById('progress-label').textContent =
      `Uploading "${file.name}" (${i+1}/${selectedFiles.length})…`;

    const formData = new FormData();
    formData.append('file', file);

    try {
      await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload');
        xhr.upload.onprogress = e => {
          if (e.lengthComputable) {
            const pct = Math.round(e.loaded / e.total * 100);
            progressBar.style.width = pct + '%';
            progressPct.textContent = pct + '%';
          }
        };
        xhr.onload = () => {
          const res = JSON.parse(xhr.responseText);
          if (xhr.status === 200) resolve(res);
          else reject(new Error(res.error || 'Upload failed'));
        };
        xhr.onerror = () => reject(new Error('Network error'));
        xhr.send(formData);
      });
    } catch (err) {
      setMsg(err.message, 'err');
    }
  }

  progressWrap.style.display = 'none';
  uploadBtn.textContent = 'Select a file first';
  uploadBtn.disabled = true;
  selectedFiles = [];
  fileInput.value = '';
  setMsg('✓ Upload complete!', 'ok');
  loadFiles();
}

// ── file list ──
async function loadFiles() {
  const res = await fetch('/files');
  const data = await res.json();
  renderFiles(data.files);
}

function renderFiles(files) {
  if (!files.length) {
    fileBody.innerHTML = '<tr class="empty-row"><td colspan="5">No files shared yet.</td></tr>';
    return;
  }
  fileBody.innerHTML = files.map(f => `
    <tr>
      <td class="fname">📄 ${esc(f.name)}</td>
      <td class="fsize">${fmtSize(f.size)}</td>
      <td class="ftime">${f.uploaded}</td>
      <td style="color:var(--muted); text-align:center">${f.downloads}</td>
      <td style="white-space:nowrap">
        <button class="btn-copy" onclick="copyLink('${f.id}')">🔗 Copy</button>
        <a href="/download/${f.id}" download="${esc(f.name)}">
          <button class="btn-dl">⬇ DL</button>
        </a>
        <button class="btn-del" onclick="deleteFile('${f.id}')">✕</button>
      </td>
    </tr>`).join('');
}

function copyLink(id) {
  const url = location.origin + '/download/' + id;
  navigator.clipboard.writeText(url).then(() => showToast('Link copied!'));
}

async function deleteFile(id) {
  if (!confirm('Remove this file from the session?')) return;
  await fetch('/delete/' + id, { method: 'DELETE' });
  loadFiles();
}

function showToast(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2000);
}

function setMsg(txt, cls) {
  msgEl.textContent = txt;
  msgEl.className = cls;
}

function fmtSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1024**2) return (b/1024).toFixed(1) + ' KB';
  if (b < 1024**3) return (b/1024**2).toFixed(1) + ' MB';
  return (b/1024**3).toFixed(2) + ' GB';
}

function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// initial load
loadFiles();
// auto-refresh every 15 s
setInterval(loadFiles, 15000);
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    file_id   = uuid.uuid4().hex
    safe_name = secure_filename(f.filename) or f"file_{file_id}"
    save_path = UPLOAD_FOLDER / file_id

    try:
        f.save(str(save_path))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    size = save_path.stat().st_size

    with registry_lock:
        file_registry[file_id] = {
            "name":        safe_name,
            "original":    f.filename,
            "path":        str(save_path),
            "size":        size,
            "uploaded_at": time.time(),
            "downloads":   0,
        }

    return jsonify({"id": file_id, "name": safe_name, "size": size})


@app.route("/files")
def list_files():
    with registry_lock:
        result = []
        for fid, info in file_registry.items():
            result.append({
                "id":        fid,
                "name":      info["name"],
                "size":      info["size"],
                "uploaded":  datetime.fromtimestamp(info["uploaded_at"]).strftime("%H:%M:%S"),
                "downloads": info["downloads"],
            })
    # newest first
    result.sort(key=lambda x: x["uploaded"], reverse=True)
    return jsonify({"files": result})


@app.route("/download/<file_id>")
def download(file_id):
    with registry_lock:
        info = file_registry.get(file_id)
        if not info:
            abort(404)
        info["downloads"] += 1
        path = info["path"]
        name = info["name"]

    return send_from_directory(
        directory=str(UPLOAD_FOLDER),
        path=file_id,
        as_attachment=True,
        download_name=name,
    )


@app.route("/delete/<file_id>", methods=["DELETE"])
def delete(file_id):
    with registry_lock:
        info = file_registry.pop(file_id, None)
    if info:
        try:
            Path(info["path"]).unlink(missing_ok=True)
        except Exception:
            pass
    return jsonify({"ok": True})


# ──────────────────────────────────────────────
# Error handlers
# ──────────────────────────────────────────────

@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "File exceeds 1 GB limit"}), 413


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "─"*52)
    print("  SessionShare  –  up to 1 GB per file")
    print("  Open → http://localhost:5000")
    print("  Files expire after 8 hours or on restart")
    print("─"*52 + "\n")
    app.run(host="dainty-crisp-410bd5.netlify.app/", port=5000, debug=False)
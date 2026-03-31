import os
import base64
import secrets
import random
import subprocess
import shutil
import re
import time
from urllib.parse import urlencode
import threading
import webbrowser
import requests
from flask import Flask, request, redirect, session, jsonify, render_template_string
browser_proc = None 
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-in-real-use")

SPOTIFY_CLIENT_ID = "EnterClientID"
SPOTIFY_CLIENT_SECRET = "EnterClientSecret"
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:5000/callback"
SPOTIFY_MARKET = "VN"

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

SCOPES = [
    "user-read-email",
    "user-read-private",
]

GENRE_SEARCH_TERMS = {
    "jazz": "genre:jazz",
    "lofi": "lofi beats",
    "ambient": "ambient chill",
    "classical": "genre:classical",
    "indie": "genre:indie",
    "rock": "genre:rock",
    "pop": "genre:pop",
    "kpop": "k-pop",
    "anime": "anime songs",
}

def open_browser():
    global browser_proc
    url = "http://127.0.0.1:5000"

    chromium_path = (
        shutil.which("chromium-browser")
        or shutil.which("chromium")
    )

    print("chromium_path =", chromium_path)

    try:
        if chromium_path:
            browser_proc = subprocess.Popen([
                chromium_path,
                "--kiosk",
                url
            ])
            print("Opened Chromium:", chromium_path)
            print("browser_proc pid =", browser_proc.pid)
        else:
            print("Chromium not found, falling back to default browser")
            webbrowser.open(url)
    except Exception as exc:
        print(f"Could not open browser automatically: {exc}")


def close_browser():
    global browser_proc
    print("close_browser called")
    print("browser_proc =", browser_proc)

    try:
        result = subprocess.run(
            ["pkill", "-f", "chromium.*127.0.0.1:5000"],
            capture_output=True,
            text=True,
            timeout=5
        )
        print("pkill returncode =", result.returncode)
        print("pkill stdout =", result.stdout)
        print("pkill stderr =", result.stderr)
    except Exception as exc:
        print(f"Could not close browser automatically: {exc}")

def ensure_config():
    if not SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_ID == "YOUR_SPOTIFY_CLIENT_ID":
        raise RuntimeError("Missing SPOTIFY_CLIENT_ID")
    if not SPOTIFY_CLIENT_SECRET or SPOTIFY_CLIENT_SECRET == "YOUR_SPOTIFY_CLIENT_SECRET":
        raise RuntimeError("Missing SPOTIFY_CLIENT_SECRET")


def basic_auth_header() -> str:
    creds = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    encoded = base64.b64encode(creds.encode("utf-8")).decode("utf-8")
    return f"Basic {encoded}"


def exchange_code_for_token(code: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": SPOTIFY_REDIRECT_URI,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def get_app_token() -> str:
    response = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def spotify_api(method: str, path: str, token: str, params=None, json_body=None):
    return requests.request(
        method=method,
        url=f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
        json=json_body,
        timeout=20,
    )


def spotify_api_with_retry(method: str, path: str, params=None, json_body=None):
    token = get_app_token()
    response = spotify_api(method, path, token, params=params, json_body=json_body)
    if response.status_code == 401:
        token = get_app_token()
        response = spotify_api(method, path, token, params=params, json_body=json_body)
    return response


def get_valid_user_token():
    access_token = session.get("spotify_access_token")
    refresh_token = session.get("spotify_refresh_token")
    expires_at = float(session.get("spotify_token_expires_at", 0))

    if access_token and time.time() < expires_at - 30:
        return access_token

    if refresh_token:
        refreshed = refresh_access_token(refresh_token)
        new_access_token = refreshed["access_token"]
        expires_in = int(refreshed.get("expires_in", 3600))
        session["spotify_access_token"] = new_access_token
        session["spotify_token_expires_at"] = time.time() + expires_in
        if refreshed.get("refresh_token"):
            session["spotify_refresh_token"] = refreshed["refresh_token"]
        return new_access_token

    return None


def simplify_track(item: dict) -> dict:
    images = item.get("album", {}).get("images", [])
    return {
        "id": item.get("id", ""),
        "uri": item.get("uri", ""),
        "name": item.get("name", "Unknown"),
        "artist": ", ".join(a.get("name", "") for a in item.get("artists", [])) or "Unknown artist",
        "cover": images[0]["url"] if images else "",
        "duration_ms": int(item.get("duration_ms", 0) or 0),
    }


def clamp_volume(value: int) -> int:
    return max(0, min(100, int(value)))


def is_amixer_available() -> bool:
    return shutil.which("amixer") is not None


def set_pi_volume(percent: int) -> dict:
    percent = clamp_volume(percent)

    if not is_amixer_available():
        raise RuntimeError("amixer not found. Install with: sudo apt install alsa-utils")

    possible_controls = ["Master", "PCM", "Speaker", "Headphone"]
    last_error = None

    for control in possible_controls:
        try:
            result = subprocess.run(
                ["amixer", "sset", control, f"{percent}%"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return {"ok": True, "volume_percent": percent, "control": control}
            last_error = result.stderr.strip() or result.stdout.strip()
        except Exception as exc:
            last_error = str(exc)

    raise RuntimeError(last_error or "Could not set volume with amixer")


def get_pi_volume() -> dict:
    if not is_amixer_available():
        return {"ok": False, "volume_percent": 100, "control": None}

    possible_controls = ["Master", "PCM", "Speaker", "Headphone"]

    for control in possible_controls:
        try:
            result = subprocess.run(
                ["amixer", "get", control],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                continue

            match = re.search(r"\[(\d{1,3})%\]", result.stdout)
            if match:
                return {
                    "ok": True,
                    "volume_percent": clamp_volume(int(match.group(1))),
                    "control": control,
                }
        except Exception:
            continue

    return {"ok": False, "volume_percent": 100, "control": None}


HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>BMO Spotify</title>
  <meta name="viewport" content="width=800, height=480, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@400;500;700&display=swap" rel="stylesheet">

  <style>
    :root{
      --bg:#a8d7d1;
      --panel:#dcefeb;
      --card:#eaf8f5;
      --border:#243b4a;
      --text:#15313a;
      --accent:#2d7f7c;
      --gold:#f2b134;
      --selected:#b8efe4;
      --selected-border:#1f7a76;
      --control:#10343a;
      --vol-panel:#10343a;
      --vol-track:#dcefeb;
      --vol-fill:#f2b134;
      --vol-thumb:#f7c45a;
      --player-blue:#0d57b7;
      --player-blue-dark:#093586;
    }

    *{
      box-sizing:border-box;
      user-select:none;
      -webkit-user-select:none;
      -webkit-tap-highlight-color:transparent;
    }

    html, body{
      margin:0;
      padding:0;
      width:800px;
      height:480px;
      overflow:hidden;
      background:var(--bg);
      color:var(--text);
      font-family:"Pixelify Sans", sans-serif;
    }

    body{
      display:block;
    }

    .app{
      width:800px;
      height:480px;
      padding:8px;
      display:grid;
      grid-template-rows:46px 56px 1fr;
      gap:8px;
      overflow:hidden;
    }

    .panel{
      background:var(--card);
      border:3px solid var(--border);
      border-radius:14px;
    }

    .header{
      display:flex;
      align-items:center;
      justify-content:center;
      padding:0 12px;
    }

    .title{
      font-size:30px;
      line-height:1;
      text-align:center;
    }

    .controls{
      display:grid;
      grid-template-columns:1fr 96px 96px 96px;
      gap:8px;
      align-items:center;
      padding:8px;
      min-width:0;
    }

    .field{
      height:100%;
      display:flex;
      align-items:center;
      gap:10px;
      padding:0 12px;
      border:3px solid var(--border);
      border-radius:12px;
      background:#f3fffc;
      font-size:19px;
      min-width:0;
      overflow:hidden;
    }

    .field select{
      border:none;
      outline:none;
      background:transparent;
      width:100%;
      font-family:inherit;
      font-size:19px;
      color:var(--text);
    }

    .btn{
      width:100%;
      height:100%;
      border:3px solid var(--border);
      border-radius:12px;
      background:var(--accent);
      color:white;
      font-family:inherit;
      font-size:18px;
      cursor:pointer;
    }

    .btn.gold{
      background:var(--gold);
      color:#1f2f34;
    }

    .content{
      display:grid;
      grid-template-columns:260px 1fr;
      gap:8px;
      min-height:0;
      overflow:hidden;
    }

    .sidebar,
    .player-shell{
      min-height:0;
      background:var(--panel);
      border:3px solid var(--border);
      border-radius:14px;
      padding:8px;
      overflow:hidden;
    }

    .results{
      display:flex;
      flex-direction:column;
      gap:8px;
      overflow-y:auto;
      height:100%;
      min-height:0;
      padding-right:2px;
    }

    .track{
      display:grid;
      grid-template-columns:48px 1fr auto;
      gap:8px;
      align-items:center;
      padding:7px;
      background:var(--card);
      border:2px solid var(--border);
      border-radius:12px;
      cursor:pointer;
      transition:all 0.15s ease;
      min-width:0;
    }

    .track:hover{
      background:#f4fffc;
    }

    .track.selected{
      background:var(--selected);
      border-color:var(--selected-border);
      box-shadow:inset 0 0 0 2px rgba(31,122,118,0.12);
    }

    .cover{
      width:48px;
      height:48px;
      border-radius:8px;
      object-fit:cover;
      border:2px solid var(--border);
      background:#cfe6e1;
    }

    .meta{
      min-width:0;
    }

    .track-name{
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
      font-size:20px;
      line-height:1.05;
    }

    .track-artist{
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
      font-size:16px;
      opacity:.85;
      margin-top:4px;
    }

    .play-mini{
      border:2px solid var(--border);
      background:var(--gold);
      color:#1f2f34;
      border-radius:10px;
      padding:7px 12px;
      font-family:inherit;
      font-size:17px;
      cursor:pointer;
    }

    .player-shell{
      display:grid;
      grid-template-columns:1fr 60px;
      gap:8px;
      min-height:0;
      align-items:stretch;
    }

    .player-main{
      display:grid;
      grid-template-rows:1fr 58px;
      gap:8px;
      min-height:0;
      overflow:hidden;
    }

    .embed-panel{
      position:relative;
      width:100%;
      min-height:0;
      background:var(--panel);
      border:2px solid var(--border);
      border-radius:14px;
      overflow:hidden;
      padding:10px;
    }

    .custom-player-card{
      width:100%;
      height:100%;
      min-height:0;
      background:var(--player-blue);
      border-radius:14px;
      padding:14px 16px;
      display:grid;
      grid-template-columns:142px minmax(0, 1fr) 44px;
      gap:12px;
      align-items:center;
      color:white;
      overflow:hidden;
    }

    .big-cover-wrap{
      width:142px;
      height:100%;
      display:flex;
      align-items:center;
      justify-content:center;
    }

    .big-cover{
      width:132px;
      height:132px;
      border-radius:12px;
      object-fit:cover;
      border:2px solid rgba(255,255,255,.16);
      background:#2f74c7;
      display:block;
    }

    .big-meta{
      min-width:0;
      height:100%;
      display:flex;
      flex-direction:column;
      justify-content:center;
      gap:11px;
      overflow:hidden;
    }

    .big-title{
      font-size:24px;
      line-height:1.05;
      font-weight:700;
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
    }

    .big-artist{
      font-size:17px;
      opacity:.94;
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
    }

    .spotify-save-row{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      width:100%;
      min-width:0;
    }

    .spotify-save{
      display:flex;
      align-items:center;
      gap:10px;
      font-size:14px;
      opacity:.98;
      min-width:0;
    }

    .spotify-plus{
      width:24px;
      height:24px;
      border-radius:50%;
      border:2px solid white;
      display:flex;
      align-items:center;
      justify-content:center;
      font-size:18px;
      line-height:1;
      flex:0 0 auto;
    }

    .big-progress-wrap{
      margin-top:auto;
      display:grid;
      grid-template-columns:minmax(0, 1fr) auto;
      gap:10px;
      align-items:center;
      min-width:0;
      width:100%;
    }

    .big-progress-bar{
      width:100%;
      min-width:0;
      height:6px;
      border-radius:999px;
      background:rgba(0,0,0,.18);
      overflow:hidden;
    }

    .big-progress-fill{
      width:0%;
      height:100%;
      background:var(--player-blue-dark);
      border-radius:999px;
      transition:width 0.2s linear;
    }

    .big-time{
      font-size:16px;
      white-space:nowrap;
      min-width:88px;
      text-align:right;
    }

    .big-right{
      height:100%;
      display:flex;
      flex-direction:column;
      align-items:center;
      justify-content:space-between;
      padding:2px 0;
    }

    .spotify-badge{
      font-size:22px;
      line-height:1;
    }

    .big-dots{
      font-size:24px;
      line-height:1;
      cursor:pointer;
      user-select:none;
    }

    .big-play{
      width:40px;
      height:40px;
      border:none;
      border-radius:50%;
      background:white;
      color:var(--player-blue);
      font-family:inherit;
      font-size:18px;
      cursor:pointer;
      display:flex;
      align-items:center;
      justify-content:center;
    }

    .embed-empty{
      position:absolute;
      inset:10px;
      display:flex;
      align-items:center;
      justify-content:center;
      text-align:center;
      font-size:24px;
      color:white;
      background:#1d2f32;
      border-radius:14px;
      padding:20px;
      pointer-events:none;
      z-index:5;
    }

    .control-bar{
      display:grid;
      grid-template-columns:repeat(4, 1fr);
      gap:8px;
      min-height:0;
    }

    .control-btn{
      border:3px solid var(--border);
      border-radius:12px;
      background:var(--control);
      color:white;
      font-family:inherit;
      font-size:19px;
      cursor:pointer;
      height:100%;
      line-height:1;
    }

    .control-btn.active{
      background:var(--gold);
      color:#1f2f34;
    }

    .volume-card{
      width:100%;
      height:100%;
      display:grid;
      grid-template-rows:24px 1fr 24px;
      align-items:center;
      justify-items:center;
      padding:8px 4px;
      border:2px solid var(--border);
      border-radius:14px;
      background:var(--vol-panel);
      color:white;
      min-height:0;
      overflow:hidden;
    }

    .vol-top{
      font-size:18px;
      line-height:1;
    }

    .vol-bottom{
      font-size:14px;
      line-height:1;
      color:#ffd36c;
    }

    .slider-area{
      width:100%;
      height:100%;
      display:flex;
      align-items:center;
      justify-content:center;
      min-height:0;
      padding:4px 0;
    }

    .vslider{
      position:relative;
      width:22px;
      height:100%;
      min-height:0;
      cursor:pointer;
      touch-action:none;
      display:flex;
      align-items:center;
      justify-content:center;
    }

    .vslider-track{
      position:absolute;
      width:10px;
      top:0;
      bottom:0;
      left:50%;
      transform:translateX(-50%);
      background:var(--vol-track);
      border:1px solid #213740;
      border-radius:999px;
    }

    .vslider-fill{
      position:absolute;
      width:10px;
      left:50%;
      bottom:0;
      transform:translateX(-50%);
      height:40%;
      background:var(--vol-fill);
      border-radius:999px;
    }

    .vslider-thumb{
      position:absolute;
      width:22px;
      height:22px;
      left:50%;
      bottom:40%;
      transform:translate(-50%, 50%);
      background:var(--vol-thumb);
      border:2px solid #243B4A;
      border-radius:50%;
      box-shadow:0 1px 2px rgba(0,0,0,.25);
    }

    #spotify-hidden-mount{
      position:absolute;
      left:-9999px;
      top:-9999px;
      width:300px;
      height:152px;
      opacity:0;
      pointer-events:none;
      overflow:hidden;
    }

    ::-webkit-scrollbar{
      width:8px;
    }

    ::-webkit-scrollbar-thumb{
      background:#7fa7a0;
      border-radius:999px;
    }

    ::-webkit-scrollbar-track{
      background:transparent;
    }
  </style>
</head>
<body>
  <div class="app">
    <div class="panel header">
      <div class="title">BMO Spotify</div>
    </div>

    <div class="panel controls">
      <div class="field">
        <span>🎵</span>
        <select id="genreSelect">
          <option value="jazz">jazz</option>
          <option value="lofi">lofi</option>
          <option value="ambient">ambient</option>
          <option value="classical">classical</option>
          <option value="indie">indie</option>
          <option value="rock">rock</option>
          <option value="pop">pop</option>
          <option value="kpop">kpop</option>
          <option value="anime">anime</option>
        </select>
      </div>

      <button class="btn" id="loadGenreBtn">Load</button>
      <button class="btn gold" id="loginBtn">Login</button>
      <button class="btn" id="exitBtn" style="background:#c83b3b; color:white;">Exit</button>
    </div>

    <div class="content">
      <div class="sidebar">
        <div class="results" id="resultsList"></div>
      </div>

      <div class="player-shell">
        <div class="player-main">
          <div class="embed-panel">
            <div class="custom-player-card">
              <div class="big-cover-wrap">
                <img id="bigCover" class="big-cover" src="" alt="">
              </div>

              <div class="big-meta">
                <div id="bigTitle" class="big-title">No track selected</div>
                <div id="bigArtist" class="big-artist">-</div>

                <div class="spotify-save-row">
                  <div class="spotify-save">
                    <div class="spotify-plus">+</div>
                    <div>Save on Spotify</div>
                  </div>
                </div>

                <div class="big-progress-wrap">
                  <div class="big-progress-bar">
                    <div id="bigProgressFill" class="big-progress-fill"></div>
                  </div>
                  <div id="bigTime" class="big-time">00:00 / 00:00</div>
                </div>
              </div>

              <div class="big-right">
                <div class="spotify-badge">🟢</div>
                <div class="big-dots" id="moreBtn">···</div>
                <button class="big-play" id="bigPlayBtn">▶</button>
              </div>
            </div>

            <div class="embed-empty" id="embedEmpty">Select a song</div>
          </div>

          <div class="control-bar">
            <button class="control-btn" id="prevBtn">⏮ Prev</button>
            <button class="control-btn" id="skipBtn">⏭ Skip</button>
            <button class="control-btn" id="loopBtn">🔁 Loop</button>
            <button class="control-btn" id="replayBtn">↺ Replay</button>
          </div>
        </div>

        <div class="volume-card">
          <div class="vol-top">🔊</div>

          <div class="slider-area">
            <div class="vslider" id="volumeSlider" aria-label="Volume slider">
              <div class="vslider-track"></div>
              <div class="vslider-fill" id="volumeFill"></div>
              <div class="vslider-thumb" id="volumeThumb"></div>
            </div>
          </div>

          <div class="vol-bottom" id="volumeValue">100</div>
        </div>
      </div>
    </div>
  </div>

  <div id="spotify-hidden-mount"></div>

  <script src="https://open.spotify.com/embed/iframe-api/v1" async></script>

  <script>
    let currentTracks = [];
    let currentTrackIndex = -1;
    let loopCurrentTrack = false;
    let loadCounter = 0;

    let embedController = null;
    let pendingUri = null;
    let pendingAutoplay = false;

    let advanceTimer = null;
    let progressTimer = null;
    let volumeSetTimer = null;

    let currentVolume = 100;
    let draggingVolume = false;

    let isPlaying = false;
    let currentProgressMs = 0;

    const genreSelect = document.getElementById("genreSelect");
    const loadGenreBtn = document.getElementById("loadGenreBtn");
    const loginBtn = document.getElementById("loginBtn");
    const exitBtn = document.getElementById("exitBtn");

    const resultsList = document.getElementById("resultsList");
    const embedEmpty = document.getElementById("embedEmpty");

    const prevBtn = document.getElementById("prevBtn");
    const skipBtn = document.getElementById("skipBtn");
    const loopBtn = document.getElementById("loopBtn");
    const replayBtn = document.getElementById("replayBtn");
    const bigPlayBtn = document.getElementById("bigPlayBtn");
    const moreBtn = document.getElementById("moreBtn");

    const bigCover = document.getElementById("bigCover");
    const bigTitle = document.getElementById("bigTitle");
    const bigArtist = document.getElementById("bigArtist");
    const bigProgressFill = document.getElementById("bigProgressFill");
    const bigTime = document.getElementById("bigTime");

    const volumeSlider = document.getElementById("volumeSlider");
    const volumeFill = document.getElementById("volumeFill");
    const volumeThumb = document.getElementById("volumeThumb");
    const volumeValue = document.getElementById("volumeValue");

    function escapeHtml(str) {
      return String(str)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function msToTime(ms) {
      const total = Math.max(0, Math.floor((ms || 0) / 1000));
      const m = Math.floor(total / 60);
      const s = total % 60;
      return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }

    async function apiGet(url) {
      const response = await fetch(url);
      let data = {};
      try {
        data = await response.json();
      } catch {
        data = { error: "Invalid server response" };
      }
      return { response, data };
    }

    async function apiPost(url, payload = {}) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      let data = {};
      try {
        data = await response.json();
      } catch {
        data = { error: "Invalid server response" };
      }
      return { response, data };
    }

    function updateVolumeUI(value) {
      currentVolume = Math.max(0, Math.min(100, Number(value) || 0));
      volumeValue.textContent = String(currentVolume);
      volumeFill.style.height = `${currentVolume}%`;
      volumeThumb.style.bottom = `${currentVolume}%`;
    }

    function clearAdvanceTimer() {
      if (advanceTimer) {
        clearTimeout(advanceTimer);
        advanceTimer = null;
      }
    }

    function clearProgressTimer() {
      if (progressTimer) {
        clearInterval(progressTimer);
        progressTimer = null;
      }
    }

    function getCurrentTrack() {
      if (currentTrackIndex < 0 || currentTrackIndex >= currentTracks.length) return null;
      return currentTracks[currentTrackIndex];
    }

    function updatePlayButton() {
      bigPlayBtn.textContent = isPlaying ? "⏸" : "▶";
    }

    function updateProgressUI() {
      const track = getCurrentTrack();
      if (!track) {
        bigProgressFill.style.width = "0%";
        bigTime.textContent = "00:00 / 00:00";
        return;
      }

      const duration = Math.max(1, track.duration_ms || 1);
      const percent = Math.max(0, Math.min(100, (currentProgressMs / duration) * 100));
      bigProgressFill.style.width = `${percent}%`;
      bigTime.textContent = `${msToTime(currentProgressMs)} / ${msToTime(duration)}`;
    }

    function startProgressTimer() {
      clearProgressTimer();

      const track = getCurrentTrack();
      if (!track) return;

      progressTimer = setInterval(() => {
        if (!isPlaying) return;
        currentProgressMs += 250;

        if (currentProgressMs >= track.duration_ms) {
          currentProgressMs = track.duration_ms;
          updateProgressUI();
          clearProgressTimer();
          return;
        }

        updateProgressUI();
      }, 250);
    }

    function scheduleAutoAdvance() {
      clearAdvanceTimer();

      const current = getCurrentTrack();
      if (!current || !current.duration_ms) return;

      const remaining = Math.max(0, current.duration_ms - currentProgressMs);
      const delay = Math.max(remaining + 1000, 1500);

      advanceTimer = setTimeout(() => {
        if (loopCurrentTrack) {
          replayCurrentTrack();
        } else {
          playNextTrack();
        }
      }, delay);
    }

    function updateSelectedRow() {
      document.querySelectorAll(".track").forEach((el, idx) => {
        el.classList.toggle("selected", idx === currentTrackIndex);
      });
    }

    function renderBigPlayer(track) {
      if (!track) {
        bigCover.src = "";
        bigTitle.textContent = "No track selected";
        bigArtist.textContent = "-";
        currentProgressMs = 0;
        updateProgressUI();
        embedEmpty.style.display = "flex";
        return;
      }

      bigCover.src = track.cover || "";
      bigTitle.textContent = track.name || "Unknown";
      bigArtist.textContent = track.artist || "Unknown artist";
      currentProgressMs = 0;
      updateProgressUI();
      embedEmpty.style.display = "none";
    }

    function loadUriInPlayer(uri, autoplay = false) {
      if (!uri) return;

      if (embedController) {
        embedController.loadUri(uri);
        if (autoplay) {
          setTimeout(() => {
            try {
              embedController.play();
            } catch (e) {}
          }, 300);
        }
      } else {
        pendingUri = uri;
        pendingAutoplay = autoplay;
      }
    }

    function setPlayingState(playing) {
      isPlaying = !!playing;
      updatePlayButton();

      if (isPlaying) {
        startProgressTimer();
        scheduleAutoAdvance();
      } else {
        clearAdvanceTimer();
      }
    }

    function playCurrentTrackFromStart() {
      const track = getCurrentTrack();
      if (!track) return;

      currentProgressMs = 0;
      updateProgressUI();
      loadUriInPlayer(track.uri, true);
      setPlayingState(true);
    }

    function replayCurrentTrack() {
      playCurrentTrackFromStart();
    }

    function togglePlayPause() {
      const track = getCurrentTrack();
      if (!track || !embedController) return;

      try {
        if (isPlaying) {
          embedController.pause();
          setPlayingState(false);
        } else {
          embedController.play();
          setPlayingState(true);
        }
      } catch (e) {
        console.log("Play/pause error:", e);
      }
    }

    async function selectTrack(index, autoplay = true) {
      if (index < 0 || index >= currentTracks.length) return;
      const track = currentTracks[index];
      if (!track || !track.uri) return;

      currentTrackIndex = index;
      updateSelectedRow();
      renderBigPlayer(track);
      loadUriInPlayer(track.uri, autoplay);

      if (autoplay) {
        setPlayingState(true);
      } else {
        setPlayingState(false);
      }
    }

    function renderResults(tracks) {
      clearAdvanceTimer();
      clearProgressTimer();

      currentTracks = tracks || [];
      currentTrackIndex = -1;
      resultsList.innerHTML = "";

      if (!currentTracks.length) {
        renderBigPlayer(null);
        resultsList.innerHTML = `
          <div class="track" style="cursor:default;">
            <div class="meta" style="grid-column:1 / -1; text-align:center; font-size:18px;">No tracks found</div>
          </div>
        `;
        return;
      }

      currentTracks.forEach((track, index) => {
        const item = document.createElement("div");
        item.className = "track";
        item.innerHTML = `
          <img class="cover" src="${escapeHtml(track.cover || "")}" alt="">
          <div class="meta">
            <div class="track-name">${escapeHtml(track.name || "Unknown")}</div>
            <div class="track-artist">${escapeHtml(track.artist || "Unknown artist")}</div>
          </div>
          <button class="play-mini">Open</button>
        `;

        item.addEventListener("click", () => {
          selectTrack(index, true);
        });

        item.querySelector(".play-mini").addEventListener("click", (e) => {
          e.stopPropagation();
          selectTrack(index, true);
        });

        resultsList.appendChild(item);
      });

      selectTrack(0, false);
    }

    async function checkLogin() {
      const { data } = await apiGet("/api/session_status");
      loginBtn.textContent = data.logged_in ? "Logout" : "Login";
      return data.logged_in;
    }

    async function loadGenreTracks(genre) {
      loadCounter += 1;
      const { response, data } = await apiGet(
        `/api/genre_tracks?genre=${encodeURIComponent(genre)}&seed=${loadCounter}`
      );

      if (!response.ok) {
        renderResults([]);
        return;
      }

      renderResults(data.tracks || []);
    }

    async function fetchCurrentVolume() {
      const { response, data } = await apiGet("/api/get_volume");
      if (response.ok && typeof data.volume_percent !== "undefined") {
        updateVolumeUI(data.volume_percent);
      } else {
        updateVolumeUI(100);
      }
    }

    function playRandomTrack() {
      if (!currentTracks.length) return;
      const index = Math.floor(Math.random() * currentTracks.length);
      selectTrack(index, true);
    }

    function playPrevTrack() {
      if (!currentTracks.length) return;

      if (loopCurrentTrack && currentTrackIndex >= 0) {
        replayCurrentTrack();
        return;
      }

      const newIndex = currentTrackIndex <= 0 ? currentTracks.length - 1 : currentTrackIndex - 1;
      selectTrack(newIndex, true);
    }

    function playNextTrack() {
      if (!currentTracks.length) return;

      if (loopCurrentTrack && currentTrackIndex >= 0) {
        replayCurrentTrack();
        return;
      }

      const newIndex = currentTrackIndex >= currentTracks.length - 1 ? 0 : currentTrackIndex + 1;
      selectTrack(newIndex, true);
    }

    function toggleLoop() {
      loopCurrentTrack = !loopCurrentTrack;
      loopBtn.classList.toggle("active", loopCurrentTrack);
    }

    function debounceSetVolume(volume) {
      if (volumeSetTimer) {
        clearTimeout(volumeSetTimer);
      }

      volumeSetTimer = setTimeout(async () => {
        const { response, data } = await apiPost("/api/set_volume", {
          volume_percent: volume
        });

        if (!response.ok) {
          console.log("System volume set failed:", data.error || "unknown error");
        }
      }, 80);
    }

    function setVolumeFromPointer(clientY) {
      const rect = volumeSlider.getBoundingClientRect();
      const y = clientY - rect.top;
      const pct = 100 - ((y / rect.height) * 100);
      const value = Math.max(0, Math.min(100, Math.round(pct)));
      updateVolumeUI(value);
      debounceSetVolume(value);
    }

    function pointerYFromEvent(e) {
      if (e.touches && e.touches.length) return e.touches[0].clientY;
      if (e.changedTouches && e.changedTouches.length) return e.changedTouches[0].clientY;
      return e.clientY;
    }

    volumeSlider.addEventListener("mousedown", (e) => {
      draggingVolume = true;
      setVolumeFromPointer(pointerYFromEvent(e));
    });

    window.addEventListener("mousemove", (e) => {
      if (!draggingVolume) return;
      setVolumeFromPointer(pointerYFromEvent(e));
    });

    window.addEventListener("mouseup", () => {
      draggingVolume = false;
    });

    volumeSlider.addEventListener("touchstart", (e) => {
      draggingVolume = true;
      setVolumeFromPointer(pointerYFromEvent(e));
      e.preventDefault();
    }, { passive: false });

    window.addEventListener("touchmove", (e) => {
      if (!draggingVolume) return;
      setVolumeFromPointer(pointerYFromEvent(e));
      e.preventDefault();
    }, { passive: false });

    window.addEventListener("touchend", () => {
      draggingVolume = false;
    });

    bigPlayBtn.addEventListener("click", togglePlayPause);
    prevBtn.addEventListener("click", playPrevTrack);
    skipBtn.addEventListener("click", playNextTrack);
    loopBtn.addEventListener("click", toggleLoop);
    replayBtn.addEventListener("click", replayCurrentTrack);

    moreBtn.addEventListener("click", () => {
      console.log("More button clicked");
    });

    loadGenreBtn.addEventListener("click", async () => {
      await loadGenreTracks(genreSelect.value);
    });

    exitBtn.addEventListener("click", async () => {
    exitBtn.disabled = true;
    exitBtn.textContent = "Exited";

    try {
      await fetch("/shutdown", { method: "POST" });
    } catch (e) {
      console.log("Shutdown request sent.");
    }
  });


    loginBtn.addEventListener("click", async () => {
      const loggedIn = await checkLogin();
      if (loggedIn) {
        window.location.href = "/logout";
      } else {
        window.location.href = "/login";
      }
    });

    window.onSpotifyIframeApiReady = (IFrameAPI) => {
      const element = document.getElementById("spotify-hidden-mount");

      const options = {
        width: "300",
        height: "152",
        uri: "spotify:track:4uUG5RXrOk84mYEfFvj3cK",
      };

      IFrameAPI.createController(element, options, (controller) => {
        embedController = controller;

        if (pendingUri) {
          const uri = pendingUri;
          const autoplay = pendingAutoplay;
          pendingUri = null;
          pendingAutoplay = false;
          loadUriInPlayer(uri, autoplay);
        }
      });
    };

    window.addEventListener("beforeunload", () => {
      clearAdvanceTimer();
      clearProgressTimer();
    });

    window.addEventListener("load", async () => {
      updateVolumeUI(100);
      updatePlayButton();
      renderBigPlayer(null);
      await fetchCurrentVolume();
      await checkLogin();
      await loadGenreTracks(genreSelect.value);
    });
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML_PAGE)


@app.route("/login")
def login():
    try:
        ensure_config()
    except Exception as exc:
        return f"Config error: {exc}", 500

    state = secrets.token_urlsafe(16)
    session["spotify_auth_state"] = state
    session.modified = True

    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "show_dialog": "true",
    }
    return redirect(f"{AUTH_URL}?{urlencode(params)}")


@app.route("/callback")
def callback():
    error = request.args.get("error")
    if error:
        return f"Spotify login error: {error}", 400

    returned_state = request.args.get("state", "")
    saved_state = session.get("spotify_auth_state")

    if not saved_state:
        return "State mismatch: session was lost or reset.", 400

    if returned_state != saved_state:
        return "State mismatch", 400

    code = request.args.get("code", "")
    if not code:
        return "Missing authorization code", 400

    try:
        token_data = exchange_code_for_token(code)
    except Exception as exc:
        return f"Token exchange failed: {exc}", 500

    session["spotify_access_token"] = token_data["access_token"]
    session["spotify_refresh_token"] = token_data.get("refresh_token")
    session["spotify_token_expires_at"] = time.time() + int(token_data.get("expires_in", 3600))
    session.pop("spotify_auth_state", None)

    return redirect("/")


@app.route("/logout")
def logout():
    session.pop("spotify_access_token", None)
    session.pop("spotify_refresh_token", None)
    session.pop("spotify_token_expires_at", None)
    session.pop("spotify_auth_state", None)
    return redirect("/")


@app.route("/api/session_status")
def session_status():
    token = get_valid_user_token()
    return jsonify({"logged_in": bool(token)})


@app.route("/api/get_volume")
def api_get_volume():
    try:
        data = get_pi_volume()
        return jsonify(data)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "volume_percent": 100}), 500


@app.route("/api/set_volume", methods=["POST"])
def api_set_volume():
    payload = request.get_json(silent=True) or {}

    try:
        volume_percent = int(payload.get("volume_percent", 100))
    except Exception:
        volume_percent = 100

    volume_percent = clamp_volume(volume_percent)

    try:
        result = set_pi_volume(volume_percent)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "volume_percent": volume_percent}), 500

@app.route("/shutdown", methods=["POST"])
def shutdown():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "Local requests only"}), 403

    shutdown_func = request.environ.get("werkzeug.server.shutdown")

    def stop_everything():
        time.sleep(0.3)
        close_browser()

        if shutdown_func is None:
            os._exit(0)
        else:
            shutdown_func()

    threading.Thread(target=stop_everything, daemon=True).start()

    return jsonify({"ok": True, "message": "Server shutting down..."})

@app.route("/api/genre_tracks")
def api_genre_tracks():
    genre = request.args.get("genre", "").strip().lower()
    seed = request.args.get("seed", "0").strip()

    if not genre:
        return jsonify({"error": "Missing genre"}), 400

    try:
        ensure_config()
        query = GENRE_SEARCH_TERMS.get(genre, genre)

        try:
            seed_int = int(seed)
        except Exception:
            seed_int = 0

        random_offset = (seed_int * 17 + random.randint(0, 20)) % 80

        response = spotify_api_with_retry(
            "GET",
            "/search",
            params={
                "q": query,
                "type": "track",
                "limit": 10,
                "offset": random_offset,
                "market": SPOTIFY_MARKET,
            },
        )

        try:
            data = response.json()
        except Exception:
            data = {}

        if not response.ok:
            error_msg = data.get("error", {}).get("message", "Spotify search failed")
            if isinstance(error_msg, dict):
                error_msg = "Spotify search failed"
            return jsonify({"error": str(error_msg)}), response.status_code

        items = data.get("tracks", {}).get("items", [])
        tracks = []
        seen_ids = set()

        for item in items:
            track_id = item.get("id")
            if not track_id or track_id in seen_ids:
                continue
            seen_ids.add(track_id)
            tracks.append(simplify_track(item))

        return jsonify({"genre": genre, "tracks": tracks})

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)
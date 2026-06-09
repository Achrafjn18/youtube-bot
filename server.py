"""
RepostAI Desktop App - Backend Server
Run this file to start the app, then open http://localhost:5000
"""

from flask import Flask, render_template, jsonify, request
from dotenv import load_dotenv
import subprocess
import threading
import datetime
import json
import os
import sys

load_dotenv()

app = Flask(__name__)

# Global state
bot_process = None
bot_logs = []
bot_status = "stopped"
stats = {
    "videos_processed": 0,
    "shorts_uploaded": 0,
    "channels_monitored": 0,
    "last_run": None
}

LOG_FILE = "repostai_logs.json"
STATS_FILE = "repostai_stats.json"

def load_persisted():
    global stats, bot_logs
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            stats.update(json.load(f))
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE) as f:
            bot_logs = json.load(f)[-100:]  # Keep last 100 logs

def save_stats():
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def add_log(message, level="info"):
    global bot_logs
    log = {
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "message": message,
        "level": level
    }
    bot_logs.append(log)
    bot_logs = bot_logs[-200:]  # Keep last 200
    with open(LOG_FILE, "w") as f:
        json.dump(bot_logs, f)

def run_bot():
    global bot_process, bot_status, stats
    bot_status = "running"
    add_log("🤖 RepostAI Bot started", "success")
    stats["last_run"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    save_stats()

    try:
        bot_process = subprocess.Popen(
            [sys.executable, "pipeline/main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=os.path.dirname(os.path.abspath(__file__))
        )

        for line in bot_process.stdout:
            line = line.strip()
            if not line:
                continue
            level = "info"
            if "ERROR" in line or "error" in line.lower():
                level = "error"
            elif "✅" in line or "Uploaded" in line or "Done" in line:
                level = "success"
                if "Uploaded" in line:
                    stats["shorts_uploaded"] += 1
                    save_stats()
            elif "⬇️" in line or "Processing" in line:
                level = "processing"
                if "Processing" in line:
                    stats["videos_processed"] += 1
                    save_stats()
            add_log(line, level)

        bot_process.wait()
    except Exception as e:
        add_log(f"Bot error: {str(e)}", "error")
    finally:
        bot_status = "stopped"
        add_log("Bot stopped", "warning")

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def get_status():
    return jsonify({
        "status": bot_status,
        "stats": stats,
        "log_count": len(bot_logs)
    })

@app.route("/api/logs")
def get_logs():
    since = request.args.get("since", 0, type=int)
    return jsonify(bot_logs[since:])

@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_status
    if bot_status == "running":
        return jsonify({"ok": False, "message": "Bot is already running"})
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Bot started!"})

@app.route("/api/stop", methods=["POST"])
def stop_bot():
    global bot_process, bot_status
    if bot_process and bot_process.poll() is None:
        bot_process.terminate()
        bot_status = "stopped"
        add_log("⛔ Bot stopped by user", "warning")
        return jsonify({"ok": True, "message": "Bot stopped"})
    return jsonify({"ok": False, "message": "Bot is not running"})

@app.route("/api/channels", methods=["GET"])
def get_channels():
    channels_file = "channels.json"
    if os.path.exists(channels_file):
        with open(channels_file) as f:
            return jsonify(json.load(f))
    default = [
        {"id": "UCpcTrCXbl4E3jKmQXV-oBgA", "name": "FIFA Official"},
        {"id": "UCCBFffCRRRkjFL9LXQQ9YDg", "name": "CBS Sports Golazo"},
        {"id": "UCNAf1k0yIjyGu3k9BwAg3lg", "name": "Sky Sports Football"}
    ]
    with open(channels_file, "w") as f:
        json.dump(default, f)
    return jsonify(default)

@app.route("/api/channels", methods=["POST"])
def save_channels():
    data = request.json
    with open("channels.json", "w") as f:
        json.dump(data, f)
    return jsonify({"ok": True})

@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify({
        "youtube_api_key": os.getenv("YOUTUBE_API_KEY", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "niche": "FIFA World Cup 2026"
    })

if __name__ == "__main__":
    load_persisted()
    print("\n" + "="*40)
    print("🤖 RepostAI is starting...")
    print("👉 Open your browser at: http://localhost:5000")
    print("="*40 + "\n")
    import webbrowser
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(debug=False, port=5000)
import os
from threading import Thread

from flask import Flask


app = Flask(__name__)


@app.get("/")
def home():
    return "Roblox Discord bot is running.", 200, {
        "Content-Type": "text/plain; charset=utf-8"
    }


@app.get("/healthz")
def healthz():
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}


def _run_server() -> None:
    port = int(os.getenv("PORT", "8080"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


def keep_alive() -> None:
    server_thread = Thread(
        target=_run_server,
        name="health-server",
        daemon=True,
    )
    server_thread.start()

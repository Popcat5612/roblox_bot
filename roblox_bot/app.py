import logging
import os
from threading import Thread

from flask import Flask, jsonify

from bot import bot, run_bot


logging.basicConfig(level=logging.INFO)
app = Flask(__name__)


def _run_discord_bot() -> None:
    try:
        run_bot()
    except Exception:
        logging.exception("Discord 봇이 종료됐습니다.")


bot_thread = Thread(
    target=_run_discord_bot,
    name="discord-bot",
    daemon=True,
)
bot_thread.start()


@app.get("/")
def home():
    return jsonify(
        {
            "service": "Roblox Discord Bot",
            "status": "ok",
            "discord_bot": "online" if bot.is_ready() else "starting",
        }
    )


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=False,
        use_reloader=False,
    )

"""
KOSPI 100 Backtest - Telegram Bot
핸드폰 텔레그램에서 /backtest 명령으로 백테스트 실행 & 결과 수신.

설정:
  1. @BotFather에서 봇 생성 → 토큰 발급
  2. .env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 추가
  3. python telegram_bot.py 로 실행

명령어:
  /start    - 봇 안내
  /backtest - 백테스트 실행 (시간 소요)
  /status   - 마지막 실행 상태 확인
  /results  - 최근 결과 요약 조회
"""
import os
import sys
import json
import time
import threading
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ── 상태 ──
bot_state = {
    "running": False,
    "last_run": None,
    "last_summary": None,
    "last_csv_path": None,
}

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_results")


# ── Telegram API 헬퍼 ──
def send_message(chat_id, text, parse_mode="HTML"):
    """텔레그램 메시지 전송 (4096자 제한 자동 분할)"""
    max_len = 4000
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    for chunk in chunks:
        requests.post(f"{API_BASE}/sendMessage", json={
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode
        })


def send_document(chat_id, file_path, caption=""):
    """텔레그램 파일 전송"""
    with open(file_path, "rb") as f:
        requests.post(
            f"{API_BASE}/sendDocument",
            data={"chat_id": chat_id, "caption": caption},
            files={"document": f}
        )


def get_updates(offset=None):
    """Polling으로 업데이트 가져오기"""
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        res = requests.get(f"{API_BASE}/getUpdates", params=params, timeout=35)
        return res.json().get("result", [])
    except Exception:
        return []


# ── 백테스트 실행 (백그라운드) ──
def run_backtest_async(chat_id):
    """백그라운드 스레드에서 백테스트 실행 후 결과 전송"""
    global bot_state
    bot_state["running"] = True

    send_message(chat_id,
        "🚀 <b>백테스트 시작!</b>\n\n"
        "📊 KOSPI 100 종목 · 2020년 4월\n"
        "⏱ 약 10~20분 소요됩니다.\n"
        "완료되면 자동으로 결과를 보내드립니다."
    )

    try:
        # backtest_april2020 모듈 임포트
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from backtest_april2020 import main
        summary, csv_path = main(output_dir=OUTPUT_DIR)

        bot_state["last_summary"] = summary
        bot_state["last_csv_path"] = csv_path
        bot_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 결과 전송
        send_message(chat_id,
            f"✅ <b>백테스트 완료!</b>\n"
            f"📅 {bot_state['last_run']}\n\n"
            f"<pre>{summary}</pre>"
        )

        # CSV 파일 전송
        if csv_path and os.path.exists(csv_path):
            send_document(chat_id, csv_path, caption="📥 백테스트 결과 CSV")

    except Exception as e:
        send_message(chat_id, f"❌ <b>백테스트 실패</b>\n\n<code>{str(e)}</code>")

    finally:
        bot_state["running"] = False


# ── 명령어 핸들러 ──
def handle_command(chat_id, command):
    """사용자 명령어 처리"""
    cmd = command.split("@")[0].strip().lower()

    if cmd == "/start":
        send_message(chat_id,
            "👋 <b>KOSPI 100 백테스트 봇</b>\n\n"
            "📈 2020년 4월 KOSPI 상위 100종목의\n"
            "주가를 ML 앙상블로 예측합니다.\n\n"
            "<b>명령어:</b>\n"
            "/backtest - 🚀 백테스트 실행\n"
            "/status - 📊 현재 상태 확인\n"
            "/results - 📋 최근 결과 조회\n"
        )

    elif cmd == "/backtest":
        if bot_state["running"]:
            send_message(chat_id, "⏳ 이미 백테스트가 실행 중입니다.\n/status 로 상태를 확인하세요.")
            return
        t = threading.Thread(target=run_backtest_async, args=(chat_id,), daemon=True)
        t.start()

    elif cmd == "/status":
        if bot_state["running"]:
            status_text = "🔄 <b>실행 중...</b>\n잠시 후 결과가 전송됩니다."
        elif bot_state["last_run"]:
            status_text = (
                f"✅ <b>마지막 실행 완료</b>\n"
                f"📅 {bot_state['last_run']}\n"
                f"📄 CSV: {'있음' if bot_state['last_csv_path'] else '없음'}"
            )
        else:
            status_text = "💤 <b>아직 실행된 백테스트가 없습니다.</b>\n/backtest 로 시작하세요."
        send_message(chat_id, status_text)

    elif cmd == "/results":
        if bot_state["last_summary"]:
            send_message(chat_id,
                f"📊 <b>최근 결과</b> ({bot_state['last_run']})\n\n"
                f"<pre>{bot_state['last_summary']}</pre>"
            )
            if bot_state["last_csv_path"] and os.path.exists(bot_state["last_csv_path"]):
                send_document(chat_id, bot_state["last_csv_path"], caption="📥 결과 CSV")
        else:
            send_message(chat_id, "📭 아직 결과가 없습니다.\n/backtest 로 먼저 실행하세요.")

    else:
        send_message(chat_id,
            "❓ 알 수 없는 명령어입니다.\n\n"
            "/start 를 입력해 사용법을 확인하세요."
        )


# ── 메인 폴링 루프 ──
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN이 .env에 설정되지 않았습니다.")
        print("   @BotFather에서 봇을 만들고 토큰을 .env에 추가하세요.")
        return

    print("=" * 50)
    print("🤖 KOSPI 100 Backtest Telegram Bot 시작")
    print(f"   Bot Token: ...{TELEGRAM_BOT_TOKEN[-10:]}")
    print("   /start, /backtest, /status, /results")
    print("=" * 50)

    offset = None
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message", {})
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")

            if not chat_id or not text:
                continue

            # CHAT_ID 제한 (설정된 경우)
            if TELEGRAM_CHAT_ID and str(chat_id) != str(TELEGRAM_CHAT_ID):
                send_message(chat_id, "⛔ 인증되지 않은 사용자입니다.")
                continue

            if text.startswith("/"):
                handle_command(chat_id, text)

        time.sleep(1)


if __name__ == "__main__":
    main()

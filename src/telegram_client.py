import logging
import requests
from config import TELEGRAM_API, TELEGRAM_BOT_TOKEN
from utils import log_step

logger = logging.getLogger("telegram_client")

@log_step(logger)
def send_message(chat_id: int, text: str, parse_mode: str = "HTML", disable_preview: bool = True) -> dict:
    """Send a text message to Telegram."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_preview
    }

    try:
        logger.info(f"Posting text message to chat {chat_id}")
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"HTTP request failed inside send_message: {e}")
        raise

@log_step(logger)
def send_poll(
    chat_id: int,
    question: str,
    options: list[str],
    correct_option_id: int,
    explanation: str = None,
    is_anonymous: bool = False
) -> dict:
    """Send a native Telegram Quiz Poll."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    url = f"{TELEGRAM_API}/sendPoll"
    
    # Enforce Telegram constraints (API will fail if exceeded)
    safe_question = question[:300] if len(question) > 300 else question
    safe_options = [opt[:100] for opt in options[:10]]
    safe_explanation = None
    if explanation:
        safe_explanation = explanation[:200] if len(explanation) > 200 else explanation

    payload = {
        "chat_id": chat_id,
        "question": safe_question,
        "options": safe_options,
        "type": "quiz",
        "correct_option_id": correct_option_id,
        "is_anonymous": is_anonymous,
    }

    if safe_explanation:
        payload["explanation"] = safe_explanation
        payload["explanation_parse_mode"] = "HTML"

    try:
        logger.info(f"Posting Telegram Quiz Poll to chat {chat_id}")
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"HTTP request failed inside send_poll: {e}")
        raise

@log_step(logger)
def send_chat_action(chat_id: int, action: str = "typing") -> None:
    """Send a chat action (like 'typing') to let users know the bot is thinking."""
    if not TELEGRAM_BOT_TOKEN:
        return
    
    url = f"{TELEGRAM_API}/sendChatAction"
    payload = {
        "chat_id": chat_id,
        "action": action
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.warning(f"Failed to send chat action {action} to {chat_id}: {e}")

if __name__ == "__main__":
    # Example usage
    chat_id = 973133568  # Replace with a valid chat ID
    send_message(chat_id, "Hello from the bot!")
    send_poll(chat_id, "What is 2 + 2?", ["3", "4", "5"], correct_option_id=1, explanation="2 + 2 equals 4.")
    send_chat_action(chat_id, "typing")
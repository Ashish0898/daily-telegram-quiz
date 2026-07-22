import os

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Webhook Security Token
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")

# GitHub LLM Configuration
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_ENDPOINT = "https://models.github.ai/inference"
MODEL_NAME = os.getenv("MODEL_NAME", "openai/gpt-4.1-nano")

# Supabase Database Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

# Admin User IDs (comma-separated integers in env)
ADMIN_USER_IDS = []
raw_admins = os.getenv("TELEGRAM_ADMIN_USER_IDS") or os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
for uid in raw_admins.split(","):
    uid = uid.strip()
    if uid.isdigit():
        ADMIN_USER_IDS.append(int(uid))

# Quiz Format Configuration: 'poll' (native) or 'inline' (message + buttons)
QUIZ_FORMAT = os.getenv("QUIZ_FORMAT", "poll").strip().lower()

# Admin Username for Access Requests (e.g. @your_username)
TELEGRAM_ADMIN_USERNAME = os.getenv("TELEGRAM_ADMIN_USERNAME", "").strip()

# Telegram Group / Community Link for unauthorized users
TELEGRAM_GROUP_LINK = os.getenv("TELEGRAM_GROUP_LINK", "").strip()


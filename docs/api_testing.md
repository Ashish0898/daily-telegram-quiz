# API Testing Guide

This guide explains how to manually trigger endpoints and simulate Telegram webhook requests using `curl` or the Python `requests` library.

---

## 🔒 Security Requirements
When testing webhook endpoints, you must authenticate your requests if `TELEGRAM_WEBHOOK_SECRET` is configured in your environment variables. 
Pass the webhook secret in the following header:
```http
X-Telegram-Bot-Api-Secret-Token: <YOUR_TELEGRAM_WEBHOOK_SECRET>
```
*Note: Any surrounding single (`'`) or double (`"`) quotes from environment variable definitions are automatically stripped by the server during verification.*

---

## 1. Simulate Telegram Webhook (/api/telegram)
Use this endpoint to simulate a Telegram user sending a command (e.g., `/quiz` or `/help`) to the bot. The endpoint requires a `POST` request with a JSON body structured like a native Telegram message.

### Python (`requests` library)
```python
import requests

url = "http://localhost:3001/api/telegram"  # Update with your deployment URL if testing in production
headers = {
    "Content-Type": "application/json",
    "X-Telegram-Bot-Api-Secret-Token": "your_webhook_secret_token"
}
payload = {
    "message": {
        "text": "/quiz",
        "from": {
            "id": 123456789,            # Must be an allowed User ID (or in TELEGRAM_ADMIN_USER_IDS)
            "username": "test_user"
        },
        "chat": {
            "id": 987654321             # Target Telegram Chat/Group ID
        }
    }
}

response = requests.post(url, json=payload, headers=headers)
print("Status:", response.status_code)
print("Response:", response.json())
```

### curl
```bash
curl -X POST http://localhost:3001/api/telegram \
  -H "Content-Type: application/json" \
  -H "X-Telegram-Bot-Api-Secret-Token: your_webhook_secret_token" \
  -d '{
    "message": {
      "text": "/quiz",
      "from": {
        "id": 123456789,
        "username": "test_user"
      },
      "chat": {
        "id": 987654321
      }
    }
  }'
```

---

## 2. Trigger Daily Quiz Cron Task (/api/quiz)
This endpoint generates a trivia question and posts it to the configured `TELEGRAM_CHAT_ID`. It supports both `GET` and `POST` requests and does not require security headers (as Vercel Crons run it via unauthenticated `GET` requests).

### Python (`requests` library)
```python
import requests

# Trigger via GET
response_get = requests.get("http://localhost:3001/api/quiz")
print("GET Response:", response_get.json())

# Trigger via POST
response_post = requests.post("http://localhost:3001/api/quiz")
print("POST Response:", response_post.json())
```

### curl
```bash
# Trigger via GET
curl -X GET http://localhost:3001/api/quiz

# Trigger via POST
curl -X POST http://localhost:3001/api/quiz
```

---

## 3. View Registered Allowed Users (/api/users)
This endpoint renders a HTML dashboard displaying the allowed users. It requires a query parameter specifying the `admin_id`. The user ID must be configured in `TELEGRAM_ADMIN_USER_IDS` or marked as an `admin` role in the database.

### curl (Retrieving raw HTML)
```bash
curl -X GET "http://localhost:3001/api/users?admin_id=<YOUR_ADMIN_USER_ID>"
```

### Python
```python
import requests

response = requests.get("http://localhost:3001/api/users", params={"admin_id": 123456789})
print("HTML Content Length:", len(response.text))
```

---

## 💡 Troubleshooting
* **`ignored_secret_mismatch` Response**: Ensure that you are passing the header `X-Telegram-Bot-Api-Secret-Token` exactly matching the `TELEGRAM_WEBHOOK_SECRET` environment variable.
* **`ignored_unauthorized_user` Response**: The user ID passed in `message.from.id` is not on the allowed list. Make sure the ID matches an ID in the `TELEGRAM_ADMIN_USER_IDS` variable or has been allowed via `/allow` command.
* **`500 Internal Server Error`**: Check server logs. This usually indicates that the database table setup has not been finalized (e.g. missing `public.quiz_history` or `public.allowed_users` tables). Follow [docs/supabase_setup.md](supabase_setup.md) to initialize the schema.

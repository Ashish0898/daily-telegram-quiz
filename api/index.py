import json
import os
import sys
import re
import html
import time
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("api")

# Load environment variables from .env file if present (useful for local development)
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip().strip("'").strip('"')
                if key not in os.environ:
                    os.environ[key] = val

# Add parent and src directories to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from src.config import TELEGRAM_CHAT_ID, TELEGRAM_WEBHOOK_SECRET, QUIZ_FORMAT
from src.telegram_client import send_message, send_poll, send_chat_action, answer_callback_query
from src.quiz_generator import generate_quiz
from src.db import (
    log_request,
    save_quiz_to_history,
    is_user_allowed,
    is_user_admin,
    allow_user,
    revoke_user,
    register_inactive_user_if_new,
    resolve_user_details,
    get_all_users
)

def parse_command(text: str) -> dict:
    """Parse commands sent from users."""
    if not text:
        return {"type": "help", "query": None}

    trimmed = text.strip()
    normalized = trimmed.lower()

    if normalized.startswith("/quiz"):
        return {"type": "quiz", "query": None}

    if normalized.startswith("/leaderboard") or normalized.startswith("/lb"):
        return {"type": "leaderboard", "query": None}

    if normalized.startswith("/help") or normalized.startswith("/start"):
        return {"type": "help", "query": None}

    if normalized.startswith("/allow"):
        query = re.sub(r"^/allow(@\w+)?\s*", "", trimmed, flags=re.IGNORECASE).strip()
        return {"type": "allow", "query": query or None}

    if normalized.startswith("/revoke"):
        query = re.sub(r"^/revoke(@\w+)?\s*", "", trimmed, flags=re.IGNORECASE).strip()
        return {"type": "revoke", "query": query or None}

    if normalized.startswith("/users"):
        return {"type": "users", "query": None}

    return {"type": "help", "query": None}

def build_help_message(is_admin: bool = False) -> str:
    """Build a dynamic help text."""
    msg = (
        "🧠 <b>Daily Trivia Quiz Bot</b> 🤖\n\n"
        "I generate and send interactive multiple-choice quiz polls!\n\n"
        "<b>Available Commands:</b>\n"
        "• /quiz — Generate and send a new interactive quiz right now.\n"
        "• /leaderboard — View current scores and standings.\n"
        "• /help — Show this help message."
    )
    if is_admin:
        msg += (
            "\n\n🛡️ <b>Admin Commands:</b>\n"
            "• /allow &lt;username_or_id&gt; [role] — Grant user access.\n"
            "• /revoke &lt;username_or_id&gt; — Revoke user access.\n"
            "• /users — List all registered users."
        )
    return msg

def build_leaderboard_message() -> str:
    """Retrieve leaderboard data and format it beautifully as HTML for Telegram."""
    from src.db import get_leaderboard_data, get_last_quiz_results
    
    # 1. Fetch last quiz champions
    last_quiz = get_last_quiz_results()
    champions_text = ""
    if last_quiz:
        correct = last_quiz.get("correct_players", [])
        if correct:
            champions_text = ", ".join(correct)
        else:
            champions_text = "No correct answers yet."
    else:
        champions_text = "No quizzes recorded."

    # 2. Fetch weekly leaderboard (last 7 days)
    weekly_lb = get_leaderboard_data(days=7)
    weekly_text = ""
    if weekly_lb:
        medals = ["🥇", "🥈", "🥉"]
        for idx, entry in enumerate(weekly_lb[:5]):
            rank = medals[idx] if idx < 3 else f"{idx + 1}."
            weekly_text += f"{rank} {entry['player']} — <b>{entry['correct']} pts</b> ({entry['accuracy']}% accuracy)\n"
    else:
        weekly_text = "No answers this week yet.\n"

    # 3. Fetch all-time leaderboard
    all_time_lb = get_leaderboard_data()
    all_time_text = ""
    if all_time_lb:
        medals = ["🏆", "🥈", "🥉"]
        for idx, entry in enumerate(all_time_lb[:5]):
            rank = medals[idx] if idx < 3 else f"{idx + 1}."
            all_time_text += f"{rank} {entry['player']} — <b>{entry['correct']} pts</b> (total: {entry['total']})\n"
    else:
        all_time_text = "No answers recorded yet.\n"

    msg = (
        "🏆 <b>QUIZ LEADERBOARD</b> 🏆\n\n"
        "🎯 <b>Last Quiz Champions:</b>\n"
        f"{champions_text}\n\n"
        "🔥 <b>Top Players (This Week):</b>\n"
        f"{weekly_text}\n"
        "👑 <b>All-Time Hall of Fame:</b>\n"
        f"{all_time_text}\n"
        "<i>Compete daily to improve your rank!</i>"
    )
    return msg


class handler(BaseHTTPRequestHandler):
    def send_json(self, status_code: int, data: dict):
        response_body = json.dumps(data).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(response_body)
        self.close_connection = True

    def send_html(self, status_code: int, html_content: str):
        response_body = html_content.encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(response_body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(response_body)
        self.close_connection = True

    def get_resolved_path(self) -> str:
        # Prefer Vercel matched path or forwarded URI headers to handle rewrites correctly
        matched_path = self.headers.get('x-matched-path') or self.headers.get('x-forwarded-uri')
        if matched_path:
            parsed_url = urlparse(matched_path)
        else:
            parsed_url = urlparse(self.path)
        return parsed_url.path.rstrip('/')

    def do_POST(self):
        path = self.get_resolved_path()

        if path in ('/api/telegram', '/api/index', '/api', '', '/api/index.py'):
            self.handle_telegram_webhook()
        elif path == '/api/quiz':
            self.handle_quiz_trigger()
        else:
            self.send_json(404, {"error": f"Path {self.path} not found"})

    def do_GET(self):
        path = self.get_resolved_path()

        if path == '':
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            index_html_path = os.path.join(root_dir, 'index.html')
            if os.path.exists(index_html_path):
                try:
                    with open(index_html_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                    self.send_header('Content-Length', str(len(html_content.encode('utf-8'))))
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(html_content.encode('utf-8'))
                    self.close_connection = True
                    return
                except Exception as e:
                    logger.error(f"Failed to read index.html: {e}")

        if path in ('', '/api', '/api/index', '/api/index.py'):
            self.send_json(200, {
                "name": "Daily Telegram Quiz Bot API",
                "status": "healthy",
                "endpoints": {
                    "webhook": "/api/telegram",
                    "quiz_scheduler": "/api/quiz",
                    "users_list": "/api/users"
                }
            })
        elif path == '/api/telegram':
            self.send_json(200, {
                "status": "active",
                "message": "Webhook endpoint is active. Please send POST requests from Telegram or simulate them using matching security headers."
            })
        elif path == '/api/quiz':
            self.handle_quiz_trigger()
        elif path == '/api/users':
            parsed_url = urlparse(self.path)
            self.handle_users_get(parsed_url.query)
        else:
            self.send_json(404, {"error": f"Path {self.path} not found"})

    def handle_telegram_webhook(self):
        start_time = time.time()
        logger.info("Incoming POST request to Telegram webhook.")

        user_id = None
        username = None
        chat_id = None
        command_text = None
        response_text = ""
        topic = None

        # Verify Telegram Secret Token for Webhook Security
        if TELEGRAM_WEBHOOK_SECRET:
            received_secret = self.headers.get('X-Telegram-Bot-Api-Secret-Token')
            clean_received = (received_secret or "").strip().strip("'").strip('"')
            clean_secret = TELEGRAM_WEBHOOK_SECRET.strip().strip("'").strip('"')
            if clean_received != clean_secret:
                logger.warning("Secret token mismatch. Request ignored.")
                self.send_json(200, {"ok": True, "reason": "ignored_secret_mismatch"})
                log_request(
                    endpoint="webhook",
                    status="ignored_secret_mismatch",
                    execution_time_ms=int((time.time() - start_time) * 1000)
                )
                return

        # Parse Request JSON Body
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        try:
            body = json.loads(post_data.decode('utf-8'))
        except Exception as e:
            logger.error("Failed to parse request body as JSON.")
            self.send_json(400, {"error": "Invalid JSON"})
            log_request(
                endpoint="webhook",
                status="invalid_json",
                error_message=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
            return

        # Handle Poll Answer updates (User votes in non-anonymous polls)
        if "poll_answer" in body:
            poll_answer = body["poll_answer"]
            poll_id = poll_answer.get("poll_id")
            user = poll_answer.get("user", {})
            user_id = user.get("id")
            username = user.get("username")
            option_ids = poll_answer.get("option_ids", [])
            
            if option_ids and user_id is not None:
                selected_option = option_ids[0]
                logger.info(f"Received poll answer: user_id={user_id}, username={username}, poll_id={poll_id}, option_id={selected_option}")
                from src.db import save_user_answer
                save_user_answer(poll_id, user_id, username, selected_option)
                
            self.send_json(200, {"ok": True})
            log_request(
                endpoint="webhook",
                status="poll_answer",
                user_id=user_id,
                username=username,
                command="poll_answer_received",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
            return

        # Handle Callback Query updates (User clicks inline keyboard buttons)
        if "callback_query" in body:
            callback_query = body["callback_query"]
            cb_id = callback_query.get("id")
            user = callback_query.get("from", {})
            user_id = user.get("id")
            username = user.get("username")
            data = callback_query.get("data", "")
            
            if data.startswith("qa:"):
                parts = data.split(":")
                if len(parts) == 4:
                    selected = int(parts[1])
                    correct = int(parts[2])
                    quiz_id = int(parts[3])
                    
                    # Check if user already answered this quiz
                    from src.db import has_user_answered
                    if has_user_answered(quiz_id, user_id):
                        answer_callback_query(cb_id, "⚠️ You have already answered this quiz! Only your first attempt is registered.", show_alert=True)
                        self.send_json(200, {"ok": True})
                        return
                    
                    is_correct = (selected == correct)
                    
                    # Save inline answer to database
                    from src.db import save_user_inline_answer
                    save_user_inline_answer(quiz_id, user_id, username, selected, is_correct)
                    
                    # Look up the explanation from quiz history if available
                    from src.db import get_quiz_explanation
                    explanation = get_quiz_explanation(quiz_id)
                    
                    emoji = "✅ Correct!" if is_correct else "❌ Incorrect!"
                    alert_text = f"{emoji}\n\n"
                    if explanation:
                        alert_text += explanation
                    else:
                        alert_text += f"The correct answer was option {chr(65 + correct)}."
                        
                    # Send flash alert popup to user
                    answer_callback_query(cb_id, alert_text, show_alert=True)
                    
            self.send_json(200, {"ok": True})
            log_request(
                endpoint="webhook",
                status="callback_query",
                user_id=user_id,
                username=username,
                command="callback_query_received",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
            return

        message = body.get("message") or body.get("edited_message")
        if not message or "text" not in message:
            logger.info("Ignoring webhook payload: no message body or no text content found.")
            self.send_json(200, {"ok": True, "reason": "no_text"})
            return

        from_user = message.get("from", {})
        user_id = from_user.get("id")
        username = from_user.get("username")
        
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        command_text = message.get("text", "").strip()

        # Check Allowlist: Allowed if the user is allowed, OR if the chat group is allowed
        is_allowed = False
        if user_id is not None:
            is_allowed = is_user_allowed(user_id)
        if not is_allowed and chat_id is not None:
            is_allowed = is_user_allowed(chat_id)

        is_start_cmd = command_text.lower().startswith("/start")

        # If user is not allowed and runs /start, record their ID as inactive for admins to approve later
        if not is_allowed and user_id is not None and is_start_cmd:
            register_inactive_user_if_new(user_id, username)

        if not is_allowed:
            logger.warning(f"Unauthorized access attempt by user_id: {user_id}, username: {username}")
            response_text = (
                f"⚠️ <b>Access Denied</b>\n\n"
                f"You are not authorized to use this bot. Please contact the administrator with your "
                f"User ID: <code>{user_id}</code>"
            )
            if chat_id:
                try:
                    send_message(chat_id, response_text)
                except Exception as e:
                    logger.error(f"Failed to send Access Denied response: {e}")

            self.send_json(200, {"ok": True, "reason": "ignored_unauthorized_user"})
            log_request(
                endpoint="webhook",
                status="access_denied",
                user_id=user_id,
                username=username,
                chat_id=chat_id,
                command=command_text,
                response_content=response_text,
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
            return

        # Core logic execution
        try:
            cmd = parse_command(command_text)
            is_admin = is_user_admin(user_id)
            cmd_type = cmd["type"]
            query = cmd["query"]

            if cmd_type == "help":
                response_text = build_help_message(is_admin)
                send_message(chat_id, response_text)
                topic = "help"

            elif cmd_type == "quiz":
                send_chat_action(chat_id, "upload_document") # "upload_document" / typing
                quiz_data = generate_quiz()
                
                # Save quiz to history first to get the database row ID
                quiz_id = save_quiz_to_history(
                    question=quiz_data["question"],
                    options=quiz_data["options"],
                    correct_option_id=quiz_data["correct_option_id"],
                    explanation=quiz_data["explanation"],
                    category=quiz_data["category"],
                    poll_id=None
                )
                
                if QUIZ_FORMAT == "inline":
                    text = (
                        f"🧠 <b>Daily Technical Trivia</b>\n"
                        f"Category: <code>{quiz_data['category']}</code>\n\n"
                        f"<b>{quiz_data['question']}</b>\n\n"
                        f"🇦 {quiz_data['options'][0]}\n"
                        f"🇧 {quiz_data['options'][1]}\n"
                    )
                    if len(quiz_data['options']) > 2:
                        text += f"🇨 {quiz_data['options'][2]}\n"
                    if len(quiz_data['options']) > 3:
                        text += f"🇩 {quiz_data['options'][3]}\n"
                    text += "\n<i>Tap a button below to submit your answer:</i>"

                    # Generate inline keyboard A, B, C, D
                    reply_markup = {
                        "inline_keyboard": [
                            [
                                {"text": "A", "callback_data": f"qa:0:{quiz_data['correct_option_id']}:{quiz_id}"},
                                {"text": "B", "callback_data": f"qa:1:{quiz_data['correct_option_id']}:{quiz_id}"},
                                {"text": "C", "callback_data": f"qa:2:{quiz_data['correct_option_id']}:{quiz_id}"},
                                {"text": "D", "callback_data": f"qa:3:{quiz_data['correct_option_id']}:{quiz_id}"}
                            ]
                        ]
                    }
                    send_message(chat_id, text, reply_markup=reply_markup)
                else:
                    # Send Quiz Poll
                    poll_resp = send_poll(
                        chat_id=chat_id,
                        question=quiz_data["question"],
                        options=quiz_data["options"],
                        correct_option_id=quiz_data["correct_option_id"],
                        explanation=quiz_data["explanation"],
                        is_anonymous=False # Not anonymous, lets them see who voted
                    )
                    
                    if poll_resp:
                        poll_id = poll_resp.get("result", {}).get("poll", {}).get("id")
                        if poll_id and quiz_id:
                            from src.db import save_poll_mapping
                            save_poll_mapping(poll_id, quiz_id)
                            
                            # Update the poll_id in quiz_history for consistency
                            try:
                                from src.db import get_supabase_client
                                client = get_supabase_client()
                                if client:
                                    client.table("quiz_history").update({"poll_id": poll_id}).eq("id", quiz_id).execute()
                            except Exception as e:
                                logger.error(f"Failed to update poll_id in history: {e}")

                
                response_text = f"Quiz Sent: '{quiz_data['question']}'"
                topic = quiz_data["category"]

            elif cmd_type == "leaderboard":
                send_chat_action(chat_id, "typing")
                response_text = build_leaderboard_message()
                send_message(chat_id, response_text)
                topic = "leaderboard"

            elif cmd_type == "allow":
                if not is_admin:
                    response_text = "⚠️ <b>Permission Denied</b>: This command is restricted to administrators."
                else:
                    parts = query.split() if query else []
                    target_identifier = parts[0] if len(parts) > 0 else None
                    role = parts[1] if len(parts) > 1 else "regular"

                    if role not in ("admin", "regular"):
                        role = "regular"

                    target_uid, target_uname = resolve_user_details(target_identifier)
                    if target_uid is None:
                        response_text = f"❌ Could not resolve user identifier '{target_identifier}'. Must be a numeric ID or username stored in Supabase."
                    else:
                        success, err = allow_user(target_uid, target_uname, role)
                        if success:
                            response_text = f"✅ User <code>{target_uid}</code> ({target_uname or 'Unknown'}) successfully allowed as <b>{role}</b>."
                        else:
                            response_text = f"❌ Failed to allow user: {err}"
                
                send_message(chat_id, response_text)
                topic = "allow_user"

            elif cmd_type == "revoke":
                if not is_admin:
                    response_text = "⚠️ <b>Permission Denied</b>: This command is restricted to administrators."
                else:
                    target_identifier = query
                    target_uid, target_uname = resolve_user_details(target_identifier)
                    if target_uid is None:
                        response_text = f"❌ Could not resolve user identifier '{target_identifier}'."
                    else:
                        success, err = revoke_user(target_uid)
                        if success:
                            response_text = f"✅ Access revoked for user <code>{target_uid}</code> ({target_uname or 'Unknown'})."
                        else:
                            response_text = f"❌ Failed to revoke user: {err}"
                
                send_message(chat_id, response_text)
                topic = "revoke_user"

            elif cmd_type == "users":
                if not is_admin:
                    response_text = "⚠️ <b>Permission Denied</b>."
                else:
                    users = get_all_users()
                    if not users:
                        response_text = "No users found in database."
                    else:
                        response_text = "👥 <b>Allowed Users List:</b>\n\n"
                        for u in users:
                            status_emoji = "✅" if u.get("is_active") else "❌"
                            role_emoji = "🛡️ admin" if u.get("role") == "admin" else "👤 regular"
                            uname = f"@{u.get('username')}" if u.get("username") else "No username"
                            response_text += (
                                f"{status_emoji} <code>{u.get('user_id')}</code> — {uname} ({role_emoji})\n"
                            )
                
                send_message(chat_id, response_text)
                topic = "list_users"

            self.send_json(200, {"ok": True})
            log_request(
                endpoint="webhook",
                status="success",
                user_id=user_id,
                username=username,
                chat_id=chat_id,
                command=command_text,
                response_content=response_text,
                topic=topic,
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            logger.exception("Error executing Telegram command webhook")
            self.send_json(500, {"error": str(e)})
            log_request(
                endpoint="webhook",
                status="error",
                user_id=user_id,
                username=username,
                chat_id=chat_id,
                command=command_text,
                error_message=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

    def handle_quiz_trigger(self):
        """Handle GET/POST requests from Vercel Crons or manual invokes to send daily quiz."""
        start_time = time.time()
        logger.info("Incoming GET/POST request for daily quiz cron scheduler.")

        try:
            # Generate Quiz once to share across all users
            quiz_data = generate_quiz()
            
            # Fetch active allowed users to send the quiz to
            active_users = [u for u in get_all_users() if u.get("is_active")]
            
            # Collect unique group chat IDs to send the quiz to (negative IDs)
            target_ids = set()
            for user in active_users:
                uid = user.get("user_id")
                if uid and int(uid) < 0:
                    target_ids.add(int(uid))


            # Also add the main TELEGRAM_CHAT_ID if configured
            if TELEGRAM_CHAT_ID:
                try:
                    target_ids.add(int(TELEGRAM_CHAT_ID))
                except ValueError:
                    pass

            if not target_ids:
                logger.error("No target chat or users found to send the quiz to.")
                self.send_json(400, {"error": "No active allowed users or TELEGRAM_CHAT_ID configured"})
                return

            sent_count = 0
            errors = []
            poll_ids = []
            
            # Save quiz to history first to get database ID (shared across both inline and poll formats)
            quiz_id = save_quiz_to_history(
                question=quiz_data["question"],
                options=quiz_data["options"],
                correct_option_id=quiz_data["correct_option_id"],
                explanation=quiz_data["explanation"],
                category=quiz_data["category"],
                poll_id=None
            )

            for chat_id in target_ids:
                try:
                    if QUIZ_FORMAT == "inline":
                        text = (
                            f"🧠 <b>Daily Technical Trivia</b>\n"
                            f"Category: <code>{quiz_data['category']}</code>\n\n"
                            f"<b>{quiz_data['question']}</b>\n\n"
                            f"🇦 {quiz_data['options'][0]}\n"
                            f"🇧 {quiz_data['options'][1]}\n"
                        )
                        if len(quiz_data['options']) > 2:
                            text += f"🇨 {quiz_data['options'][2]}\n"
                        if len(quiz_data['options']) > 3:
                            text += f"🇩 {quiz_data['options'][3]}\n"
                        text += "\n<i>Tap a button below to submit your answer:</i>"

                        reply_markup = {
                            "inline_keyboard": [
                                [
                                    {"text": "A", "callback_data": f"qa:0:{quiz_data['correct_option_id']}:{quiz_id}"},
                                    {"text": "B", "callback_data": f"qa:1:{quiz_data['correct_option_id']}:{quiz_id}"},
                                    {"text": "C", "callback_data": f"qa:2:{quiz_data['correct_option_id']}:{quiz_id}"},
                                    {"text": "D", "callback_data": f"qa:3:{quiz_data['correct_option_id']}:{quiz_id}"}
                                ]
                            ]
                        }
                        send_message(chat_id, text, reply_markup=reply_markup)
                    else:
                        poll_resp = send_poll(
                            chat_id=chat_id,
                            question=quiz_data["question"],
                            options=quiz_data["options"],
                            correct_option_id=quiz_data["correct_option_id"],
                            explanation=quiz_data["explanation"],
                            is_anonymous=False
                        )

                        # Save the poll ID returned for history and mapping lookup
                        if poll_resp:
                            p_id = poll_resp.get("result", {}).get("poll", {}).get("id")
                            if p_id:
                                poll_ids.append(p_id)
                                if quiz_id:
                                    from src.db import save_poll_mapping
                                    save_poll_mapping(p_id, quiz_id)
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Failed to send poll/message to chat {chat_id}: {e}")
                    errors.append(f"{chat_id}: {str(e)}")

            # If format was poll, update quiz_history with all generated poll IDs for backwards compatibility
            if QUIZ_FORMAT != "inline" and quiz_id and poll_ids:
                try:
                    from src.db import get_supabase_client
                    client = get_supabase_client()
                    if client:
                        client.table("quiz_history").update({"poll_id": ",".join(poll_ids)}).eq("id", quiz_id).execute()
                except Exception as e:
                    logger.error(f"Failed to update poll_id in quiz_history for quiz {quiz_id}: {e}")



            response_data = {
                "ok": True,
                "quiz": quiz_data["question"],
                "sent_count": sent_count,
            }
            if errors:
                response_data["errors"] = errors

            self.send_json(200, response_data)
            log_request(
                endpoint="quiz_scheduler",
                status="success" if sent_count > 0 else "error",
                chat_id=list(target_ids)[0] if target_ids else None,
                command="scheduler_run",
                response_content=json.dumps(response_data),
                topic=quiz_data["category"],
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            logger.exception("Error during daily quiz scheduler execution")
            self.send_json(500, {"error": str(e)})
            log_request(
                endpoint="quiz_scheduler",
                status="error",
                command="scheduler_run",
                error_message=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

    def handle_users_get(self, query_string: str):
        """Display allowed users in a styled dashboard page (similar to insights bot)."""
        start_time = time.time()
        logger.info("Incoming GET request to view registered allowed users dashboard.")

        query_params = parse_qs(query_string)
        admin_id_str = query_params.get("admin_id", [None])[0]

        if not admin_id_str:
            self.send_json(401, {"error": "Missing admin_id query parameter"})
            return

        try:
            admin_id = int(admin_id_str)
        except ValueError:
            self.send_json(400, {"error": "Invalid admin_id format"})
            return

        if not is_user_admin(admin_id):
            self.send_json(403, {"error": "Access Denied: user is not an administrator"})
            return

        try:
            users = get_all_users()
            rows_html = ""
            for u in users:
                uid = u.get("user_id")
                uname = f"@{u.get('username')}" if u.get("username") else "—"
                role = u.get("role", "regular")
                is_active = u.get("is_active", True)
                created = u.get("created_at", "—")

                if created != "—":
                    try:
                        # Clean up timestamp format
                        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        created = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                    except Exception:
                        pass

                role_badge = f'<span class="badge badge-admin">admin</span>' if role == 'admin' else f'<span class="badge badge-regular">regular</span>'
                status_badge = f'<span class="badge badge-active">active</span>' if is_active else f'<span class="badge badge-inactive">revoked</span>'
                
                rows_html += f"""
                <tr>
                    <td><code>{uid}</code></td>
                    <td>{html.escape(uname)}</td>
                    <td>{role_badge}</td>
                    <td>{status_badge}</td>
                    <td>{html.escape(created)}</td>
                </tr>
                """

            html_page = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>🛡️ Quiz Bot - Allowed Users</title>
    <style>
        body {{
            background-color: #0f172a;
            color: #e2e8f0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 40px 20px;
            display: flex;
            justify-content: center;
        }}
        .container {{
            max-width: 900px;
            width: 100%;
            background-color: #1e293b;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            padding: 30px;
            border: 1px solid #334155;
        }}
        h1 {{
            font-size: 24px;
            margin-top: 0;
            margin-bottom: 25px;
            color: #f8fafc;
            border-bottom: 2px solid #334155;
            padding-bottom: 15px;
        }}
        .table-responsive {{
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th, td {{
            padding: 12px 16px;
            border-bottom: 1px solid #334155;
        }}
        th {{
            background-color: #0f172a;
            color: #94a3b8;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 12px;
            letter-spacing: 0.05em;
        }}
        tr:hover {{
            background-color: #334155;
        }}
        code {{
            background-color: #0f172a;
            padding: 2px 6px;
            border-radius: 4px;
            color: #38bdf8;
            font-family: SFMono-Regular, Consolas, monospace;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 9999px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .badge-admin {{
            background-color: rgba(239, 68, 68, 0.2);
            color: #ef4444;
            border: 1px solid rgba(239, 68, 68, 0.4);
        }}
        .badge-regular {{
            background-color: rgba(59, 130, 246, 0.2);
            color: #3b82f6;
            border: 1px solid rgba(59, 130, 246, 0.4);
        }}
        .badge-active {{
            background-color: rgba(34, 197, 94, 0.2);
            color: #22c55e;
            border: 1px solid rgba(34, 197, 94, 0.4);
        }}
        .badge-inactive {{
            background-color: rgba(107, 114, 128, 0.2);
            color: #9ca3af;
            border: 1px solid rgba(107, 114, 128, 0.4);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🛡️ Registered Users Control List - Quiz Bot</h1>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>User ID</th>
                        <th>Username</th>
                        <th>Role</th>
                        <th>Status</th>
                        <th>Registered At</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""
            self.send_html(200, html_page)

        except Exception as e:
            logger.exception("Error rendering users control list dashboard")
            self.send_json(500, {"error": str(e)})

if __name__ == '__main__':
    from http.server import HTTPServer
    port = int(os.getenv("PORT", 3001)) # Default to port 3001 to avoid conflict with insights bot on 3000
    server = HTTPServer(('0.0.0.0', port), handler)
    print(f"Starting Quiz Bot server on http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

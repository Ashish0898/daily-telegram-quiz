import os
import logging
from supabase import create_client, Client
from src.config import SUPABASE_URL, SUPABASE_KEY, ADMIN_USER_IDS
from src.utils import log_step

logger = logging.getLogger("db")

_client = None

def get_supabase_client() -> Client:
    """Initialize and return the Supabase client."""
    global _client
    if _client is not None:
        return _client

    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.warning("Supabase credentials not configured. Skipping database operations.")
        return None

    try:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        return None

def log_request(
    endpoint: str,
    status: str,
    user_id: int = None,
    username: str = None,
    chat_id: int = None,
    command: str = None,
    error_message: str = None,
    execution_time_ms: int = None,
    response_content: str = None,
    topic: str = None
) -> None:
    """Log execution audits to Supabase 'request_audit' table."""
    client = get_supabase_client()
    if not client:
        return

    payload = {
        "endpoint": endpoint,
        "status": status,
        "user_id": user_id,
        "username": username,
        "chat_id": chat_id,
        "command": command,
        "error_message": error_message,
        "execution_time_ms": execution_time_ms,
        "response_content": response_content,
        "topic": topic
    }

    try:
        client.table("request_audit").insert(payload).execute()
        logger.info(f"Audited request to Supabase for endpoint: {endpoint}")
    except Exception as e:
        logger.error(f"Failed to insert audit log: {e}")

@log_step(logger)
def save_quiz_to_history(
    question: str,
    options: list[str],
    correct_option_id: int,
    explanation: str = None,
    category: str = None,
    poll_id: str = None
) -> int | None:
    """Log a sent quiz to the 'quiz_history' table in Supabase and return the row ID."""
    client = get_supabase_client()
    if not client:
        return None

    payload = {
        "question": question,
        "options": options,
        "correct_option_id": correct_option_id,
        "explanation": explanation,
        "category": category,
        "poll_id": poll_id
    }

    try:
        response = client.table("quiz_history").insert(payload).execute()
        logger.info("Saved quiz item to Supabase quiz_history.")
        if response.data and len(response.data) > 0:
            return response.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Failed to save quiz to history: {e}")
        raise

@log_step(logger)
def is_user_allowed(user_id: int) -> bool:
    """Check if a Telegram user ID is present and active in Supabase allowed_users."""
    if user_id in ADMIN_USER_IDS:
        logger.info(f"User {user_id} is in config ADMIN_USER_IDS. Access allowed.")
        return True

    client = get_supabase_client()
    if not client:
        # Fallback: if database is not set, allow admin IDs in config
        return len(ADMIN_USER_IDS) == 0 or user_id in ADMIN_USER_IDS

    try:
        response = client.table("allowed_users").select("is_active").eq("user_id", user_id).execute()
        if response.data and len(response.data) > 0:
            active = response.data[0].get("is_active", True)
            logger.info(f"DB allowlist lookup result for {user_id}: active={active}")
            return active
        logger.info(f"User {user_id} not found in DB allowlist.")
        return False
    except Exception as e:
        logger.warning(f"Could not query 'allowed_users' in Supabase: {e}. Falling back to admin config check.")
        return user_id in ADMIN_USER_IDS

@log_step(logger)
def is_user_admin(user_id: int) -> bool:
    """Check if a Telegram user ID is an admin."""
    if user_id in ADMIN_USER_IDS:
        return True

    client = get_supabase_client()
    if not client:
        return user_id in ADMIN_USER_IDS

    try:
        response = client.table("allowed_users").select("role").eq("user_id", user_id).execute()
        if response.data and len(response.data) > 0:
            role = response.data[0].get("role")
            return role == "admin"
        return False
    except Exception as e:
        logger.error(f"Failed to check admin status: {e}")
        return False

@log_step(logger)
def allow_user(user_id: int, username: str = None, role: str = "regular") -> tuple[bool, str | None]:
    """Upsert an allowed user in Supabase allowed_users."""
    client = get_supabase_client()
    if not client:
        return False, "Database connection not available"

    payload = {
        "user_id": user_id,
        "role": role,
        "is_active": True
    }
    if username:
        payload["username"] = username.lstrip('@')

    try:
        client.table("allowed_users").upsert(payload).execute()
        return True, None
    except Exception as e:
        logger.exception(f"Failed to allow user {user_id}")
        return False, str(e)

@log_step(logger)
def revoke_user(user_id: int) -> tuple[bool, str | None]:
    """Deactivate a user in the 'allowed_users' table."""
    client = get_supabase_client()
    if not client:
        return False, "Database connection not available"

    try:
        client.table("allowed_users").update({"is_active": False}).eq("user_id", user_id).execute()
        return True, None
    except Exception as e:
        logger.exception(f"Failed to revoke user {user_id}")
        return False, str(e)

@log_step(logger)
def register_inactive_user_if_new(user_id: int, username: str = None) -> bool:
    """Register a new user in database as inactive, awaiting authorization."""
    client = get_supabase_client()
    if not client:
        return False

    try:
        response = client.table("allowed_users").select("user_id").eq("user_id", user_id).execute()
        if response.data and len(response.data) > 0:
            return False

        payload = {
            "user_id": user_id,
            "is_active": False,
            "role": "regular"
        }
        if username:
            payload["username"] = username.lstrip('@')

        client.table("allowed_users").insert(payload).execute()
        logger.info(f"Registered new inactive user: {user_id} (username: {username})")
        return True
    except Exception as e:
        logger.exception(f"Failed to register inactive user {user_id}")
        return False

@log_step(logger)
def resolve_user_details(identifier: str) -> tuple[int | None, str | None]:
    """Resolve identifier (numeric ID or username) to (user_id, username)."""
    if not identifier:
        return None, None

    identifier = identifier.strip()
    client = get_supabase_client()
    if not client:
        # Without DB, can only resolve numeric strings
        if identifier.isdigit():
            return int(identifier), None
        return None, None

    if identifier.isdigit():
        user_id = int(identifier)
        try:
            response = client.table("allowed_users").select("username").eq("user_id", user_id).execute()
            if response.data and len(response.data) > 0:
                return user_id, response.data[0].get("username")
        except Exception:
            pass
        return user_id, None

    username = identifier.lstrip('@')
    try:
        response = client.table("allowed_users").select("user_id, username").eq("username", username).execute()
        if response.data and len(response.data) > 0:
            row = response.data[0]
            return row.get("user_id"), row.get("username")

        response = client.table("allowed_users").select("user_id, username").ilike("username", username).execute()
        if response.data and len(response.data) > 0:
            row = response.data[0]
            return row.get("user_id"), row.get("username")
    except Exception as e:
        logger.error(f"Failed to resolve username {username}: {e}")

    return None, None

@log_step(logger)
def get_all_users() -> list[dict]:
    """Retrieve all users on the allowlist."""
    client = get_supabase_client()
    if not client:
        return []

    try:
        response = client.table("allowed_users").select("*").execute()
        return response.data or []
    except Exception as e:
        logger.error(f"Failed to retrieve allowed users: {e}")
        return []

@log_step(logger)
def save_user_answer(poll_id: str, user_id: int, username: str, selected_option_id: int) -> bool:
    """Save a user's quiz poll answer to Supabase."""
    client = get_supabase_client()
    if not client:
        return False

    # Look up the correct answer from quiz history using poll_id
    is_correct = None
    try:
        response = client.table("quiz_history").select("correct_option_id").eq("poll_id", poll_id).execute()
        if response.data and len(response.data) > 0:
            correct_option_id = response.data[0].get("correct_option_id")
            if correct_option_id is not None:
                is_correct = (selected_option_id == correct_option_id)
    except Exception as e:
        logger.error(f"Failed to lookup correctness for poll {poll_id}: {e}")

    payload = {
        "poll_id": poll_id,
        "user_id": user_id,
        "selected_option_id": selected_option_id,
        "is_correct": is_correct
    }
    if username:
        payload["username"] = username.lstrip('@')

    try:
        client.table("user_quiz_answers").upsert(payload, on_conflict="poll_id,user_id").execute()
        logger.info(f"Successfully saved answer in DB for user {user_id} on poll {poll_id} (is_correct={is_correct})")
        return True
    except Exception as e:
        logger.error(f"Failed to save user answer to DB: {e}")
        return False


@log_step(logger)
def save_user_inline_answer(quiz_id: int, user_id: int, username: str, selected_option_id: int, is_correct: bool) -> bool:
    """Save a user's inline keyboard quiz answer to Supabase."""
    client = get_supabase_client()
    if not client:
        return False

    payload = {
        "quiz_id": quiz_id,
        "user_id": user_id,
        "selected_option_id": selected_option_id,
        "is_correct": is_correct
    }
    if username:
        payload["username"] = username.lstrip('@')

    try:
        client.table("user_quiz_answers").upsert(payload, on_conflict="quiz_id,user_id").execute()
        logger.info(f"Successfully saved inline answer in DB for user {user_id} on quiz {quiz_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to save user inline answer to DB: {e}")
        return False

@log_step(logger)
def get_quiz_explanation(quiz_id: int) -> str | None:
    """Retrieve explanation for a quiz from history by its ID."""
    client = get_supabase_client()
    if not client:
        return None

    try:
        response = client.table("quiz_history").select("explanation").eq("id", quiz_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0].get("explanation")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch explanation for quiz {quiz_id}: {e}")
        return None

@log_step(logger)
def has_user_answered(quiz_id: int, user_id: int) -> bool:
    """Check if a user has already answered a specific quiz."""
    client = get_supabase_client()
    if not client:
        return False

    try:
        response = client.table("user_quiz_answers").select("id").eq("quiz_id", quiz_id).eq("user_id", user_id).execute()
        return len(response.data) > 0
    except Exception as e:
        logger.error(f"Failed to check if user answered quiz {quiz_id}: {e}")
        return False

@log_step(logger)
def get_leaderboard_data(days: int = None) -> list[dict]:
    """Retrieve aggregated player leaderboard data, optionally filtered by days."""
    client = get_supabase_client()
    if not client:
        return []

    try:
        query = client.table("user_quiz_answers").select("user_id, username, is_correct, created_at")
        if days is not None:
            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.gte("created_at", cutoff.isoformat())

        response = query.execute()
        rows = response.data or []

        stats = {}
        for r in rows:
            user_id = r.get("user_id")
            username = r.get("username")
            is_correct = r.get("is_correct")

            player = f"@{username}" if username else f"User {user_id}"
            if not player:
                continue

            if player not in stats:
                stats[player] = {"correct": 0, "total": 0}

            stats[player]["total"] += 1
            if is_correct:
                stats[player]["correct"] += 1

        leaderboard = []
        for player, data in stats.items():
            correct = data["correct"]
            total = data["total"]
            accuracy = round((correct / total) * 100, 1) if total > 0 else 0.0
            leaderboard.append({
                "player": player,
                "correct": correct,
                "total": total,
                "accuracy": accuracy
            })

        # Sort by correct answers desc, then accuracy desc
        leaderboard.sort(key=lambda x: (x["correct"], x["accuracy"]), reverse=True)
        return leaderboard
    except Exception as e:
        logger.error(f"Failed to retrieve leaderboard data: {e}")
        return []

@log_step(logger)
def get_last_quiz_results() -> dict | None:
    """Retrieve details and voter breakdown for the most recently sent quiz."""
    client = get_supabase_client()
    if not client:
        return None

    try:
        # Get the latest quiz from history
        response = client.table("quiz_history").select("*").order("created_at", desc=True).limit(1).execute()
        if not response.data or len(response.data) == 0:
            return None

        quiz = response.data[0]
        quiz_id = quiz.get("id")
        poll_id = quiz.get("poll_id")
        question = quiz.get("question")

        # Fetch answers for this quiz
        query = client.table("user_quiz_answers").select("user_id, username, is_correct")
        if poll_id:
            query = query.eq("poll_id", poll_id)
        else:
            query = query.eq("quiz_id", quiz_id)

        ans_response = query.execute()
        answers = ans_response.data or []

        correct_players = []
        incorrect_players = []

        for ans in answers:
            username = ans.get("username")
            user_id = ans.get("user_id")
            player = f"@{username}" if username else f"User {user_id}"

            if ans.get("is_correct"):
                correct_players.append(player)
            else:
                incorrect_players.append(player)

        return {
            "question": question,
            "correct_players": correct_players,
            "incorrect_players": incorrect_players,
            "total_answers": len(answers)
        }
    except Exception as e:
        logger.error(f"Failed to retrieve last quiz results: {e}")
        return None


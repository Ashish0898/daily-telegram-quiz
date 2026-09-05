import os
import re
import random
import requests
import json
import logging
from datetime import datetime, timezone
try:
    from src.config import (
        GEMINI_ENDPOINT, GEMINI_API_KEY, MODEL_NAME,
        OPENROUTER_ENDPOINT, OPENROUTER_API_KEY, OPENROUTER_MODEL,
        GROQ_ENDPOINT, GROQ_API_KEY, GROQ_MODEL,
        QUIZ_ENGINE_VERSION
    )
    from src.utils import log_step
except ImportError:
    from config import (
        GEMINI_ENDPOINT, GEMINI_API_KEY, MODEL_NAME,
        OPENROUTER_ENDPOINT, OPENROUTER_API_KEY, OPENROUTER_MODEL,
        GROQ_ENDPOINT, GROQ_API_KEY, GROQ_MODEL,
        QUIZ_ENGINE_VERSION
    )
    from utils import log_step

# V2 engine imports
try:
    from src.quiz_selector import build_question_blueprint
    from src.quiz_validator import validate_question_candidate
    from src.quiz_critic import (
        CRITIC_SYSTEM_PROMPT,
        format_candidate_for_critic,
        evaluate_critic_response,
        QUIZ_CRITIC_PROMPT_VERSION
    )
    from src.deduplication import generate_question_fingerprint, check_is_duplicate
    from src.question_modes import get_mode_instruction, get_difficulty_instruction
except ImportError:
    from quiz_selector import build_question_blueprint
    from quiz_validator import validate_question_candidate
    from quiz_critic import (
        CRITIC_SYSTEM_PROMPT,
        format_candidate_for_critic,
        evaluate_critic_response,
        QUIZ_CRITIC_PROMPT_VERSION
    )
    from deduplication import generate_question_fingerprint, check_is_duplicate
    from question_modes import get_mode_instruction, get_difficulty_instruction

QUIZ_GENERATOR_PROMPT_VERSION = "v2.0"
FALLBACKS_FILE_PATH = os.path.join(os.path.dirname(__file__), "fallbacks.json")

logger = logging.getLogger("quiz_generator")


def _call_gemini_direct(api_key: str, model: str, system_prompt: str, user_prompt: str, temperature: float) -> str:
    base_url = GEMINI_ENDPOINT.rstrip('/')
    if not base_url.endswith('/models'):
        base_url = f"{base_url}/models"
    url = f"{base_url}/{model}:generateContent?key={api_key}"
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}]
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json"
        }
    }
    logger.info(f"Sending request to Google Gemini API (model: {model})")
    response = requests.post(url, headers=headers, json=payload, timeout=20)
    response.raise_for_status()
    result_json = response.json()
    
    candidates = result_json.get("candidates", [])
    if not candidates:
        raise ValueError("No candidates returned from Gemini API")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("No content parts returned from Gemini API")
    return parts[0].get("text", "").strip()


def _call_openai_compatible(endpoint: str, api_key: str, model: str, system_prompt: str, user_prompt: str, temperature: float, provider_name: str = "LLM") -> str:
    url = endpoint if endpoint.startswith("http") else f"{endpoint}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"}
    }
    logger.info(f"Sending request to {provider_name} API (model: {model})")
    response = requests.post(url, headers=headers, json=payload, timeout=20)
    response.raise_for_status()
    result_json = response.json()
    return result_json["choices"][0]["message"]["content"].strip()


SEEDS_FILE_PATH = os.path.join(os.path.dirname(__file__), "seeds.json")
try:
    with open(SEEDS_FILE_PATH, "r", encoding="utf-8") as f:
        SEEDS_DATA = json.load(f)
        TRACKS_DATA = SEEDS_DATA.get("tracks", {})
        THEME_SCHEDULE = {int(k): v for k, v in SEEDS_DATA.get("schedule", {}).items()}
except Exception as e:
    logger.error(f"Failed to load seeds.json: {e}")
    TRACKS_DATA = {}
    THEME_SCHEDULE = {
        i: {
            "category": "Cognitive Reasoning & System Design",
            "track": "cognitive",
            "seeds": ["Mental Models in Tech", "System Design Trade-offs", "Code Snippet Deduction"]
        } for i in range(7)
    }


TRACK_PROMPTS = {
    "cognitive": (
        "TRACK: Cognitive Reasoning, Quantitative Logic & Mental Models.\n"
        "Guidelines:\n"
        "- Generate a question testing Quantitative Logic & Set Overlap (e.g., Venn diagram / Inclusion-Exclusion like 'In a group of 100 people, 60 use Python, 50 use Java, how many use both?', Pigeonhole Principle, or Rate & Work math), Cognitive Reflection (where the intuitive gut reaction is wrong, e.g. bat and ball / widget math), a Probability Paradox (e.g. False Positive Base Rate Fallacy, Monty Hall, Birthday Paradox), a Behavioral Game Theory Dilemma (e.g. Prisoner's Dilemma, Nash Equilibrium, Perverse Incentives), or an applied Mental Model (Chesterton's Fence, Goodhart's Law, Braess's Paradox).\n"
        "- The candidate should be able to solve it through clear logic and reflection, experiencing an 'Aha!' moment upon seeing the answer."
    ),
    "code": (
        "TRACK: Practical Coding, 'Guess the Output' & Bug Spotting.\n"
        "Guidelines:\n"
        "- Include a short, clean, realistic 3-6 line code snippet (Python, SQL, or Concurrency/Async) directly in the question.\n"
        "- Test a practical edge case, such as: mutable default arguments, late-binding in closures, shallow vs deep copy mutations, integer caching & identity vs equality, async event loop blocking, or NULL evaluation in SQL NOT IN.\n"
        "- Ask: 'What is the output of this snippet?' or 'What subtle bug or runtime behavior will occur?'"
    ),
    "sysdesign": (
        "TRACK: Senior System Design, Scalability Dilemmas & Incident Diagnostics.\n"
        "Guidelines:\n"
        "- Pose a concrete, realistic production scenario or postmortem investigation (e.g. why a service crashed at 00:00 UTC, how to mitigate a Cache Stampede under 50k QPS, LSM-Tree vs B-Tree write amplification trade-offs, or database replication lag mitigation).\n"
        "- Test applied architectural reasoning and trade-offs rather than textbook definitions."
    ),
    "algo": (
        "TRACK: Algorithmic Pattern Recognition & Complexity Intuition.\n"
        "Guidelines:\n"
        "- Test pattern recognition for high-scale problems (e.g. 'You need to find the rolling median from a continuous stream of metrics. Which data structure combination achieves O(1) median retrieval?').\n"
        "- Compare optimal data structures and algorithmic approaches (Sliding Window vs Monotonic Stack vs Two Heaps vs Topological Sort) rather than asking for obscure mathematical proofs."
    )
}


def _clean_math_text(text: str) -> str:
    """Clean up raw LaTeX dollar signs and common LaTeX commands for clean Telegram rendering."""
    if not text:
        return text
    # Strip LaTeX math delimiters ($...$ or $$...$$)
    text = re.sub(r'\$\$([^\$]+)\$\$', r'\1', text)
    text = re.sub(r'\$([^\$]+)\$', r'\1', text)

    # Common LaTeX macro replacements
    replacements = [
        (r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1/\2)'),
        (r'\\cos', 'cos'),
        (r'\\sin', 'sin'),
        (r'\\tan', 'tan'),
        (r'\\log', 'log'),
        (r'\\ln', 'ln'),
        (r'\\cdot', '·'),
        (r'\\times', '×'),
        (r'\\dots', '...'),
        (r'\\circ', '°'),
        (r'\\le', '≤'),
        (r'\\ge', '≥'),
        (r'\\ne', '≠'),
        (r'\\approx', '≈'),
        (r'\\sqrt\{([^}]+)\}', r'√(\1)'),
        (r'\\pi', 'π'),
        (r'\\theta', 'θ'),
        (r'\^2', '²'),
        (r'\^3', '³'),
        (r'\^4', '⁴'),
        (r'\^t', 'ᵗ'),
        (r'\^n', 'ⁿ'),
        (r'\^x', 'ˣ'),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)
    return text.strip()


def _call_llm_pipeline(system_prompt: str, user_prompt: str, temperature: float = 0.7) -> tuple[str | None, str | None, str | None]:
    """
    Execute prompt across configured providers: Gemini Direct -> OpenRouter -> Groq.
    Returns (raw_content, provider_name, model_name).
    """
    providers_to_try = []

    # 1. Gemini Direct (primary)
    if GEMINI_API_KEY:
        for m in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]:
            providers_to_try.append(
                (f"Gemini Direct ({m})", m, lambda mod=m: _call_gemini_direct(GEMINI_API_KEY, mod, system_prompt, user_prompt, temperature))
            )

    # 2. OpenRouter (if configured)
    if OPENROUTER_API_KEY:
        providers_to_try.append(
            ("OpenRouter", OPENROUTER_MODEL, lambda: _call_openai_compatible(OPENROUTER_ENDPOINT, OPENROUTER_API_KEY, OPENROUTER_MODEL, system_prompt, user_prompt, temperature, "OpenRouter"))
        )

    # 3. Groq (if configured)
    if GROQ_API_KEY:
        providers_to_try.append(
            ("Groq", GROQ_MODEL, lambda: _call_openai_compatible(GROQ_ENDPOINT, GROQ_API_KEY, GROQ_MODEL, system_prompt, user_prompt, temperature, "Groq"))
        )

    for provider_name, model_name, provider_fn in providers_to_try:
        try:
            raw_content = provider_fn()
            if raw_content:
                logger.info(f"Successfully received response from '{provider_name}'")
                return raw_content, provider_name, model_name
        except Exception as err:
            logger.warning(f"LLM Provider '{provider_name}' failed: {err}")

    return None, None, None


@log_step(logger)
def generate_quiz(track: str = None, topic: str = None, user_id: int = None) -> dict:
    """
    Generate a high-quality interview, reasoning, or custom domain quiz.
    If topic is provided, generates an engaging question for that custom topic.
    If track is provided ('cognitive', 'code', 'sysdesign', 'algo'), generates for that track.
    Otherwise, picks from today's weekday schedule.
    """
    if QUIZ_ENGINE_VERSION == "v2":
        return generate_quiz_v2(track=track, topic=topic, user_id=user_id)

    weekday = datetime.now(timezone.utc).weekday()

    if topic:
        selected_track = "custom"
        topic_clean = topic.strip()
        math_keywords = ["calculus", "trig", "algebra", "geometry", "math", "derivative", "integral", "matrix", "vector", "statistic", "probability"]
        if any(k in topic_clean.lower() for k in math_keywords):
            category = f"Mathematics: {topic_clean.title()}"
        else:
            category = f"Topic: {topic_clean.title()}"
        selected_seed = topic_clean.title()
        track_guideline = (
            f"TOPIC: {topic_clean}.\n"
            f"- Generate a crisp, engaging multiple-choice question on {topic_clean} testing conceptual understanding, core intuition, or a clever problem.\n"
            f"- Focus on conceptual clarity, visual/geometric deduction, or an 'Aha!' insight rather than tedious multi-page algebraic grinding."
        )
    elif track and track in TRACKS_DATA:
        track_info = TRACKS_DATA[track]
        category = track_info.get("name", track.capitalize())
        seeds_list = track_info.get("seeds", ["General problem solving"])
        selected_seed = random.choice(seeds_list)
        selected_track = track
        track_guideline = TRACK_PROMPTS.get(selected_track, TRACK_PROMPTS["cognitive"])
    elif track and track in TRACK_PROMPTS:
        selected_track = track
        category = track.capitalize()
        selected_seed = "Practical problem solving"
        track_guideline = TRACK_PROMPTS.get(selected_track, TRACK_PROMPTS["cognitive"])
    elif track and track not in ("workout", "all"):
        # The user passed a custom topic in the track parameter (e.g. track="calculus")
        selected_track = "custom"
        topic_clean = track.strip()
        math_keywords = ["calculus", "trig", "algebra", "geometry", "math", "derivative", "integral", "matrix", "vector", "statistic", "probability"]
        if any(k in topic_clean.lower() for k in math_keywords):
            category = f"Mathematics: {topic_clean.title()}"
        else:
            category = f"Topic: {topic_clean.title()}"
        selected_seed = topic_clean.title()
        track_guideline = (
            f"TOPIC: {topic_clean}.\n"
            f"- Generate a crisp, engaging multiple-choice question on {topic_clean} testing conceptual understanding, core intuition, or a clever problem.\n"
            f"- Focus on conceptual clarity, visual/geometric deduction, or an 'Aha!' insight rather than tedious multi-page algebraic grinding."
        )
    else:
        # Fall back to weekday schedule
        theme = THEME_SCHEDULE.get(weekday, THEME_SCHEDULE.get(0))
        category = theme["category"]
        selected_track = theme.get("track", "cognitive")
        seeds_list = theme.get("seeds", ["System design and reasoning"])
        selected_seed = random.choice(seeds_list)
        track_guideline = TRACK_PROMPTS.get(selected_track, TRACK_PROMPTS["cognitive"])

    # Fetch recent questions from the database to prevent duplicates
    recent_questions = []
    try:
        try:
            from src.db import get_recent_questions
        except ImportError:
            from db import get_recent_questions
        recent_questions = get_recent_questions(category, limit=12)
    except Exception as e:
        logger.warning(f"Could not retrieve recent questions from database: {e}")

    logger.info(f"Generating quiz for track: '{selected_track}' | Category: '{category}' | Seed: '{selected_seed}'")

    system_prompt = (
        "You are an expert technical interviewer, cognitive puzzle designer, and staff software assessment engineer. "
        "Your task is to generate a single highly engaging, accurate multiple-choice question that tests logical reasoning, cognitive deduction, code analysis, or system architecture trade-offs. "
        "CRITICAL: Avoid obscure textbook trivia, pedantic syntax memorization, or academic proofs. Every question must be rewarding, solvable through deduction, intuition, or engineering experience, and deliver an 'Aha!' moment upon resolution. "
        "CRITICAL FORMATTING: Telegram does NOT render LaTeX ($...$ or \\frac). Do NOT use dollar signs ($) or LaTeX macros. Use clean Unicode characters (e.g. ², ³, °, π, θ, √, ·, /) or clean plain text / inline <code> tags for all formulas. "
        "You MUST respond ONLY with a valid JSON object matching the requested schema. Do NOT include markdown formatting or commentary outside the JSON."
    )

    user_prompt = (
        f"Generate an engaging multiple-choice question.\n"
        f"- Category: {category}\n"
        f"- Concept Focus: {selected_seed}\n"
        f"- {track_guideline}\n\n"
    )

    if recent_questions:
        exclusion_list = "\n".join([f"- {q}" for q in recent_questions])
        user_prompt += (
            f"PREVENT DUPLICATES (Do NOT repeat or closely resemble these recently asked questions):\n"
            f"{exclusion_list}\n\n"
        )

    user_prompt += (
        "CRITICAL SCHEMA & CONSTRAINTS:\n"
        "1. Exactly 4 options in the 'options' list.\n"
        "2. Exactly 1 correct option indicated by 'correct_option_id' (0, 1, 2, or 3).\n"
        "3. The 3 incorrect distractors must be plausible intuition traps or common misconceptions (not silly or obviously wrong).\n"
        "4. Keep the question crisp and direct (max 320 chars, including any code snippet).\n"
        "5. Each option must be concise (max 80 chars).\n"
        "6. Explanation must clearly explain WHY the correct option is right and WHY the intuitive trap was wrong (max 200 chars).\n"
        "7. Response must be strictly formatted JSON with no trailing commas:\n\n"
        "{\n"
        "  \"question\": \"Your question or code puzzle text?\",\n"
        "  \"options\": [\"Option A\", \"Option B\", \"Option C\", \"Option D\"],\n"
        "  \"correct_option_id\": 0,\n"
        "  \"explanation\": \"Crisp explanation of why option A is correct.\",\n"
        "  \"category\": \"" + category + "\",\n"
        "  \"track\": \"" + selected_track + "\"\n"
        "}"
    )

    temperature = random.uniform(0.6, 0.85)

    providers_to_try = []

    # 1. Gemini Direct (primary)
    if GEMINI_API_KEY:
        for m in ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]:
            providers_to_try.append(
                (f"Gemini Direct ({m})", lambda mod=m: _call_gemini_direct(GEMINI_API_KEY, mod, system_prompt, user_prompt, temperature))
            )

    # 2. OpenRouter (if configured)
    if OPENROUTER_API_KEY:
        providers_to_try.append(
            ("OpenRouter", lambda: _call_openai_compatible(OPENROUTER_ENDPOINT, OPENROUTER_API_KEY, OPENROUTER_MODEL, system_prompt, user_prompt, temperature, "OpenRouter"))
        )

    # 3. Groq (if configured)
    if GROQ_API_KEY:
        providers_to_try.append(
            ("Groq", lambda: _call_openai_compatible(GROQ_ENDPOINT, GROQ_API_KEY, GROQ_MODEL, system_prompt, user_prompt, temperature, "Groq"))
        )

    raw_content = None
    last_error = None

    for provider_name, provider_fn in providers_to_try:
        try:
            raw_content = provider_fn()
            if raw_content:
                logger.info(f"Successfully received quiz response from provider '{provider_name}'")
                break
        except Exception as err:
            logger.warning(f"LLM Provider '{provider_name}' failed: {err}")
            last_error = err

    if not raw_content:
        logger.warning(f"All LLM providers failed ({last_error}). Using curated cognitive fallback question.")
        return _get_curated_fallback(selected_track)

    try:
        # Strip markdown formatting if present
        if raw_content.startswith("```"):
            raw_content = raw_content.strip("`").replace("json", "", 1).strip()

        quiz_data = json.loads(raw_content)

        required_keys = ["question", "options", "correct_option_id", "explanation"]
        for key in required_keys:
            if key not in quiz_data:
                raise ValueError(f"Missing required key '{key}' in LLM response")

        if not isinstance(quiz_data["options"], list) or len(quiz_data["options"]) < 4:
            raise ValueError("Options must be a list of at least 4 items")

        correct_idx = int(quiz_data["correct_option_id"])
        if correct_idx < 0 or correct_idx >= len(quiz_data["options"]):
            raise ValueError(f"correct_option_id {correct_idx} out of range")

        quiz_data["correct_option_id"] = correct_idx
        quiz_data["question"] = _clean_math_text(str(quiz_data["question"]))
        quiz_data["options"] = [_clean_math_text(str(opt)) for opt in quiz_data["options"][:4]]
        quiz_data["explanation"] = _clean_math_text(str(quiz_data["explanation"]))
        quiz_data["category"] = str(quiz_data.get("category", category)).strip()
        quiz_data["track"] = selected_track

        logger.info(f"Generated question successfully: '{quiz_data['question'][:50]}...'")
        return quiz_data

    except Exception as e:
        logger.warning(f"Failed to parse LLM quiz response: {e}. Falling back to curated question.")
        return _get_curated_fallback(selected_track)


def _get_curated_fallback(track: str = "cognitive") -> dict:
    """Provide high-quality curated fallback from fallbacks.json or built-in library."""
    selected_track = track if track in ["cognitive", "code", "sysdesign", "algo", "curiosity"] else "cognitive"

    if os.path.exists(FALLBACKS_FILE_PATH):
        try:
            with open(FALLBACKS_FILE_PATH, "r", encoding="utf-8") as f:
                fallbacks_data = json.load(f)
                track_fallbacks = fallbacks_data.get(selected_track, fallbacks_data.get("cognitive", []))
                if track_fallbacks:
                    choice = dict(random.choice(track_fallbacks))
                    choice["track"] = selected_track
                    choice["quality_status"] = "curated_fallback"
                    return choice
        except Exception as e:
            logger.warning(f"Could not load fallbacks.json ({e}). Using built-in fallbacks.")

    fallbacks = {
        "cognitive": {
            "question": "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost?",
            "options": ["$0.10", "$0.05", "$0.01", "$0.15"],
            "correct_option_id": 1,
            "explanation": "If the ball is $0.05, the bat is $1.05 ($1.00 more), totaling $1.10. Intuition impulsively says $0.10.",
            "category": "Cognitive Reasoning",
            "track": "cognitive",
            "concept_id": "cognitive_reflection",
            "reasoning_mode": "intuition_trap",
            "difficulty": 2,
            "quality_status": "curated_fallback"
        },
        "code": {
            "question": "What is the output of this Python snippet?\n\ndef fn(val, acc=[]):\n    acc.append(val)\n    return len(acc)\n\nprint(fn('a'), fn('b'))",
            "options": ["1 1", "1 2", "2 2", "Error"],
            "correct_option_id": 1,
            "explanation": "Default list arguments are evaluated once at function definition and mutated across subsequent calls.",
            "category": "Practical Coding",
            "track": "code",
            "concept_id": "python_mutable_defaults",
            "reasoning_mode": "predict",
            "difficulty": 2,
            "quality_status": "curated_fallback"
        },
        "sysdesign": {
            "question": "A backend service experiences massive latency spikes every night at exactly 00:00 UTC despite near-zero user traffic. What is the most probable architectural cause?",
            "options": ["Thundering herd of scheduled cron jobs", "Database connection pool leak", "Memory fragmentation compaction", "DNS TTL expiration storm"],
            "correct_option_id": 0,
            "explanation": "Unjittered cron jobs configured at midnight trigger simultaneously across all nodes, overwhelming backend services.",
            "category": "Senior System Design",
            "track": "sysdesign",
            "concept_id": "circuit_breaker_jitter",
            "reasoning_mode": "diagnose",
            "difficulty": 2,
            "quality_status": "curated_fallback"
        },
        "algo": {
            "question": "You need to continuously calculate the median of a high-throughput incoming data stream of numbers. Which data structure pair gives optimal O(1) median retrieval?",
            "options": ["Two Heaps (Max Heap + Min Heap)", "Two Balanced BSTs", "Segment Tree + Binary Index Tree", "Circular Queue + Hash Map"],
            "correct_option_id": 0,
            "explanation": "Maintaining a Max-Heap for the smaller half and a Min-Heap for the larger half allows O(1) median lookups and O(log N) inserts.",
            "category": "Algorithmic Patterns",
            "track": "algo",
            "concept_id": "streaming_two_heaps",
            "reasoning_mode": "pattern_recognition",
            "difficulty": 3,
            "quality_status": "curated_fallback"
        },
        "curiosity": {
            "question": "Why did standardizing time zones become critically necessary in the late 19th century?",
            "options": ["Railways required unified timetables to prevent single-track collisions", "Astronomers requested solar noon alignment", "Telegraph lines could only transmit UTC", "Factory labor laws mandated identical shifts"],
            "correct_option_id": 0,
            "explanation": "Hundreds of conflicting local solar times caused train dispatch chaos and fatal head-on collisions.",
            "category": "Intellectual Curiosity & Mechanisms",
            "track": "curiosity",
            "concept_id": "railway_time_zones",
            "reasoning_mode": "curiosity",
            "difficulty": 2,
            "quality_status": "curated_fallback"
        }
    }
    return fallbacks.get(selected_track, fallbacks["cognitive"])


@log_step(logger)
def generate_quiz_v2(track: str = None, topic: str = None, user_id: int = None) -> dict:
    """
    V2 Quiz Generator:
    1. Builds question blueprint with concept, reasoning mode, and difficulty constraints.
    2. Generates 3 candidates in a single prompt.
    3. Runs deterministic rule validation on candidates.
    4. Evaluates valid candidate with adversarial LLM critic.
    5. Returns candidate on pass, retries up to 2 attempts, or falls back to curated library.
    """
    # 1. Fetch recent history for cooldown and deduplication
    recent_metadata = []
    recent_questions = []
    try:
        try:
            from src.db import get_recent_quizzes_metadata, get_recent_questions, get_user_concept_mastery_map
        except ImportError:
            from db import get_recent_quizzes_metadata, get_recent_questions, get_user_concept_mastery_map

        recent_metadata = get_recent_quizzes_metadata(limit=30)
        recent_questions = [m.get("question") for m in recent_metadata if m.get("question")]
        if not recent_questions:
            recent_questions = get_recent_questions(limit=15)
    except Exception as e:
        logger.warning(f"Failed to query recent quiz history: {e}")

    # User concept mastery
    user_mastery_map = {}
    if user_id is not None:
        try:
            user_mastery_map = get_user_concept_mastery_map(user_id)
        except Exception as e:
            logger.warning(f"Failed to query user mastery: {e}")

    # 2. Build blueprint
    blueprint = build_question_blueprint(
        track=track,
        topic=topic,
        recent_history=recent_metadata,
        user_concept_mastery=user_mastery_map
    )
    logger.info(f"[V2] Selected Blueprint: Concept='{blueprint.get('concept_name')}', Mode='{blueprint.get('reasoning_mode')}', Diff={blueprint.get('difficulty')}")

    selected_track = blueprint.get("track", "cognitive")
    mode_instruction = get_mode_instruction(blueprint.get("reasoning_mode"))
    diff_instruction = get_difficulty_instruction(blueprint.get("difficulty"))

    # 3. System and User Prompt for Candidate Generation
    system_prompt = (
        "You are an expert technical interviewer, cognitive puzzle designer, and senior engineering assessment director.\n"
        "Your task is to generate 3 CANDIDATE multiple-choice questions for the specified concept and reasoning mode.\n"
        "CRITICAL REQUIREMENTS:\n"
        "- Require applied reasoning, logic deduction, or system diagnosis. Avoid pure fact memorization.\n"
        "- Do NOT reuse familiar canonical textbook examples (e.g. standard bat & ball, standard 3 doors Monty Hall).\n"
        "- Create a novel, realistic scenario.\n"
        "- Ensure exactly one option is objectively correct and defensible.\n"
        "- Distractors must represent plausible, realistic intuition traps or common senior misconceptions.\n"
        "- Telegram Poll Constraints:\n"
        "  * Question: max 300 characters.\n"
        "  * Options: exactly 4 options, each max 100 characters.\n"
        "  * Explanation: STRICTLY 150-195 characters (max 200). Clearly state WHY the right answer is correct and the trap.\n"
        "  * NO raw LaTeX dollar signs ($) or LaTeX macros. Use clean Unicode or plain text.\n"
        "Response must be valid JSON ONLY matching schema:\n"
        "{\n"
        "  \"candidates\": [\n"
        "    {\n"
        "      \"question\": \"...\",\n"
        "      \"options\": [\"Option A\", \"Option B\", \"Option C\", \"Option D\"],\n"
        "      \"correct_option_id\": 0,\n"
        "      \"explanation\": \"...\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    user_prompt = (
        f"Generate 3 candidate questions for:\n"
        f"- Concept: {blueprint.get('concept_name')}\n"
        f"- Subtopic Focus: {blueprint.get('primary_subtopic')}\n"
        f"- {mode_instruction}\n"
        f"- {diff_instruction}\n"
        f"- Objective: {blueprint.get('objective')}\n"
        f"- Avoid Patterns: {', '.join(blueprint.get('avoid_patterns', []))}\n\n"
    )
    if recent_questions:
        exclusion_list = "\n".join([f"- {q[:80]}" for q in recent_questions[:10]])
        user_prompt += f"EXCLUDE & DO NOT DUPLICATE THESE RECENT QUESTIONS:\n{exclusion_list}\n\n"

    # Generation loop: max 2 attempts to maintain fast Vercel execution
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        temperature = random.uniform(0.65, 0.85)
        raw_content, provider_name, model_name = _call_llm_pipeline(system_prompt, user_prompt, temperature)

        if not raw_content:
            logger.warning(f"[V2] Attempt {attempt}: LLM providers failed to return content")
            continue

        try:
            cleaned_json_str = raw_content.strip()
            if cleaned_json_str.startswith("```"):
                cleaned_json_str = cleaned_json_str.strip("`").replace("json", "", 1).strip()

            parsed = json.loads(cleaned_json_str)
            candidates = parsed.get("candidates") if isinstance(parsed, dict) and "candidates" in parsed else [parsed]
            if not isinstance(candidates, list):
                candidates = [candidates]

            logger.info(f"[V2] Attempt {attempt}: Received {len(candidates)} candidates from {provider_name} ({model_name})")

            for cand_idx, candidate in enumerate(candidates):
                if not isinstance(candidate, dict):
                    continue

                # Clean math and text
                candidate["question"] = _clean_math_text(str(candidate.get("question", "")))
                candidate["options"] = [_clean_math_text(str(o)) for o in candidate.get("options", [])[:4]]
                candidate["explanation"] = _clean_math_text(str(candidate.get("explanation", "")))

                # 1. Deterministic rule validation
                val_result = validate_question_candidate(candidate)
                if not val_result.is_valid:
                    logger.info(f"[V2] Candidate {cand_idx} failed deterministic validation: {val_result.issues}")
                    continue

                # 2. Deduplication check
                is_dup, dup_reason = check_is_duplicate(candidate["question"], recent_questions)
                if is_dup:
                    logger.info(f"[V2] Candidate {cand_idx} rejected as duplicate: {dup_reason}")
                    continue

                # 3. LLM Critic evaluation
                critic_prompt = format_candidate_for_critic(candidate, blueprint)
                critic_raw, _, critic_model = _call_llm_pipeline(CRITIC_SYSTEM_PROMPT, critic_prompt, temperature=0.2)

                if critic_raw:
                    try:
                        critic_result = evaluate_critic_response(critic_raw)
                        logger.info(f"[V2] Candidate {cand_idx} critic score: {critic_result.get('overall_score')}, passed: {critic_result.get('pass')}")
                        if not critic_result.get("pass"):
                            logger.info(f"[V2] Candidate {cand_idx} rejected by critic: {critic_result.get('issues')}")
                            continue

                        # Candidate PASSED both deterministic checks and critic
                        fingerprint = generate_question_fingerprint(candidate["question"])
                        candidate["concept_id"] = blueprint.get("concept_id")
                        candidate["reasoning_mode"] = blueprint.get("reasoning_mode")
                        candidate["difficulty"] = blueprint.get("difficulty")
                        candidate["question_fingerprint"] = fingerprint
                        candidate["quality_score"] = critic_result.get("overall_score", 85)
                        candidate["generation_attempt"] = attempt
                        candidate["generation_model"] = model_name or "gemini"
                        candidate["quality_status"] = "critic_passed"
                        candidate["interview_relevance"] = blueprint.get("interview_relevance", 8)
                        candidate["cognitive_value"] = blueprint.get("cognitive_value", 8)
                        candidate["category"] = blueprint.get("category", "Cognitive Reasoning")
                        candidate["track"] = selected_track
                        candidate["critic_review"] = critic_result

                        logger.info(f"[V2] Successfully generated & verified question on attempt {attempt}: '{candidate['question'][:50]}...'")
                        return candidate
                    except Exception as crit_err:
                        logger.warning(f"[V2] Critic parsing failed ({crit_err}). Permitting candidate that passed deterministic checks.")
                        fingerprint = generate_question_fingerprint(candidate["question"])
                        candidate["concept_id"] = blueprint.get("concept_id")
                        candidate["reasoning_mode"] = blueprint.get("reasoning_mode")
                        candidate["difficulty"] = blueprint.get("difficulty")
                        candidate["question_fingerprint"] = fingerprint
                        candidate["quality_score"] = 75
                        candidate["generation_attempt"] = attempt
                        candidate["generation_model"] = model_name or "gemini"
                        candidate["quality_status"] = "deterministic_passed"
                        candidate["interview_relevance"] = blueprint.get("interview_relevance", 8)
                        candidate["cognitive_value"] = blueprint.get("cognitive_value", 8)
                        candidate["category"] = blueprint.get("category", "Cognitive Reasoning")
                        candidate["track"] = selected_track
                        return candidate
                else:
                    # Critic unavailable, but passed strict deterministic rules
                    logger.warning("[V2] Critic LLM unavailable; candidate passed strict deterministic validation.")
                    fingerprint = generate_question_fingerprint(candidate["question"])
                    candidate["concept_id"] = blueprint.get("concept_id")
                    candidate["reasoning_mode"] = blueprint.get("reasoning_mode")
                    candidate["difficulty"] = blueprint.get("difficulty")
                    candidate["question_fingerprint"] = fingerprint
                    candidate["quality_score"] = 75
                    candidate["generation_attempt"] = attempt
                    candidate["generation_model"] = model_name or "gemini"
                    candidate["quality_status"] = "deterministic_passed"
                    candidate["interview_relevance"] = blueprint.get("interview_relevance", 8)
                    candidate["cognitive_value"] = blueprint.get("cognitive_value", 8)
                    candidate["category"] = blueprint.get("category", "Cognitive Reasoning")
                    candidate["track"] = selected_track
                    return candidate

        except Exception as parse_err:
            logger.warning(f"[V2] Attempt {attempt} failed during candidate processing: {parse_err}")

    logger.warning("[V2] All generation attempts exhausted or rejected by critic. Using curated fallback.")
    fallback = dict(_get_curated_fallback(selected_track))
    if "concept_id" not in fallback:
        fallback["concept_id"] = blueprint.get("concept_id")
        fallback["reasoning_mode"] = blueprint.get("reasoning_mode")
        fallback["difficulty"] = blueprint.get("difficulty")
    fallback["quality_status"] = "curated_fallback"
    fallback["question_fingerprint"] = generate_question_fingerprint(fallback["question"])
    return fallback


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for t in ["cognitive", "code", "sysdesign", "algo"]:
        print(f"\n================ TRACK: {t.upper()} ================")
        q = generate_quiz(track=t)
        print(json.dumps(q, indent=2))
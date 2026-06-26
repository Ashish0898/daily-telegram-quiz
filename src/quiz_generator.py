import os
import random
import requests
import json
import logging
from datetime import datetime, timezone
from config import GITHUB_ENDPOINT, GITHUB_TOKEN, MODEL_NAME
from utils import log_step

logger = logging.getLogger("quiz_generator")

# Weekday theme mapping (0=Monday, 6=Sunday)
THEME_SCHEDULE = {
    0: {
        "category": "Data Structures",
        "seed": "arrays, hash tables, linked lists, binary trees, heaps, graphs, tries"
    },
    1: {
        "category": "Algorithms & Complexity",
        "seed": "Big O time/space complexity, sorting, binary search, recursion, dynamic programming, sliding window, two-pointers"
    },
    2: {
        "category": "Databases & SQL",
        "seed": "indexing, execution plans, SQL joins, ACID properties, database isolation levels, sharding, replication, NoSQL trade-offs"
    },
    3: {
        "category": "System Design & Architecture",
        "seed": "caching strategies (LRU/LFU), load balancing, DNS, TCP vs UDP, CDN, microservices, rate limiting, message queues, event-driven design"
    },
    4: {
        "category": "Programming Languages & Runtimes",
        "seed": "garbage collection mechanisms, memory management (stack vs heap), concurrency vs parallelism, JavaScript event loop, Python GIL, Go channels"
    },
    5: {
        "category": "DevOps, Git & Linux",
        "seed": "Docker containers, CI/CD pipeline principles, git rebase vs merge, linux process scheduling, file system permissions, shell commands"
    },
    6: {
        "category": "Tech History & Riddles",
        "seed": "famous computer scientists, classic logic riddles, Turing machines, historic software bugs, cryptography basics (RSA/AES)"
    }
}

EXCLUDE_CLICHES = (
    "Avoid extremely basic or common textbook questions (e.g., 'What does HTML stand for?' or 'What is Big O of binary search?'). "
    "Make questions challenging, equivalent to intermediate-to-advanced technical interview questions."
)

@log_step(logger)
def generate_quiz() -> dict:
    """
    Call GitHub LLM to generate a single high-quality technical interview question.
    Determines the category and topic automatically based on the current day of the week.
    Returns a dictionary matching the schema:
    {
      "question": str,
      "options": list[str],
      "correct_option_id": int,
      "explanation": str,
      "category": str
    }
    """
    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not configured")

    # Determine topic based on today's weekday
    weekday = datetime.now(timezone.utc).weekday()
    theme = THEME_SCHEDULE[weekday]
    category = theme["category"]
    seed = theme["seed"]

    logger.info(f"Preparing LLM prompt for daily category: '{category}'")

    system_prompt = (
        "You are an expert technical interviewer and software engineering assessment designer. "
        "Your task is to generate a single highly engaging, accurate multiple-choice question. "
        "You MUST respond ONLY with a valid JSON object. Do not include markdown code block formatting like ```json or any explanations outside the JSON."
    )

    user_prompt = (
        f"Generate a technical software engineering multiple-choice question.\n"
        f"- Today's Category: {category}\n"
        f"- Concept Seeds: {seed}\n"
        f"- Target Difficulty: Intermediate to Advanced (suitable for a mid-to-senior engineer interview)\n\n"
        f"CRITICAL CONSTRAINTS:\n"
        f"1. The question must be a multiple choice query with exactly 4 options.\n"
        f"2. Only one option must be correct. The other three options must be plausible distractors (not obviously wrong).\n"
        f"3. The correct_option_id must be the 0-indexed index of the correct answer (0, 1, 2, or 3).\n"
        f"4. Keep the question short and direct: maximum 300 characters.\n"
        f"5. Each option must be concise: maximum 80 characters.\n"
        f"6. The explanation must explain WHY the correct option is right and/or why the others are incorrect: maximum 200 characters.\n"
        f"7. {EXCLUDE_CLICHES}\n"
        f"8. Ensure the JSON schema is precisely formatted as shown below:\n\n"
        "{\n"
        "  \"question\": \"Your technical question?\",\n"
        "  \"options\": [\"Option A\", \"Option B\", \"Option C\", \"Option D\"],\n"
        "  \"correct_option_id\": 0,\n"
        "  \"explanation\": \"A concise technical explanation of the correct choice.\",\n"
        "  \"category\": \"Category name\"\n"
        "}"
    )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GITHUB_TOKEN}"
    }

    temperature = random.uniform(0.7, 1.0)
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": temperature,
        "model": MODEL_NAME
    }

    try:
        url = f"{GITHUB_ENDPOINT}/chat/completions"
        logger.info(f"Sending request to GitHub LLM API (model: {MODEL_NAME})")
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        
        result_json = response.json()
        raw_content = result_json["choices"][0]["message"]["content"].strip()
        
        # Strip code block wrappers if any
        if raw_content.startswith("```"):
            raw_content = raw_content.strip("`").replace("json", "", 1).strip()

        logger.info("Successfully received LLM response. Parsing JSON...")
        quiz_data = json.loads(raw_content)

        # Validate structure
        required_keys = ["question", "options", "correct_option_id", "explanation", "category"]
        for key in required_keys:
            if key not in quiz_data:
                raise ValueError(f"Missing required key '{key}' in LLM response")

        if not isinstance(quiz_data["options"], list) or len(quiz_data["options"]) < 4:
            raise ValueError("Options must be a list of exactly 4 items")

        correct_idx = int(quiz_data["correct_option_id"])
        if correct_idx < 0 or correct_idx >= len(quiz_data["options"]):
            raise ValueError(f"correct_option_id {correct_idx} is out of bounds for options")
        
        # Enforce exact string formatting and trimming
        quiz_data["correct_option_id"] = correct_idx
        quiz_data["question"] = str(quiz_data["question"]).strip()
        quiz_data["options"] = [str(opt).strip() for opt in quiz_data["options"]]
        quiz_data["explanation"] = str(quiz_data["explanation"]).strip()
        quiz_data["category"] = str(quiz_data["category"]).strip()

        logger.info(f"Generated question successfully: '{quiz_data['question'][:40]}...'")
        return quiz_data

    except Exception as e:
        logger.warning(f"Error generating quiz from LLM: {e}. Falling back to default question.")
        # High quality fallback question based on weekday if LLM fails
        fallbacks = {
            0: {
                "question": "Which data structure is typically used to implement Breadth-First Search (BFS) on a graph?",
                "options": ["Stack", "Queue", "Max Heap", "Binary Search Tree"],
                "correct_option_id": 1,
                "explanation": "BFS explores nodes level by level, requiring a FIFO (First-In, First-Out) Queue to track nodes.",
                "category": "Data Structures"
            },
            1: {
                "question": "What is the worst-case time complexity of searching in a Hash Table with collision handling via chaining?",
                "options": ["O(1)", "O(log N)", "O(N)", "O(N log N)"],
                "correct_option_id": 2,
                "explanation": "In the worst-case, all elements hash to the same bucket, turning it into a linked list search which is O(N).",
                "category": "Algorithms & Complexity"
            },
            2: {
                "question": "Which database isolation level guarantees complete prevention of Dirty Reads, Non-repeatable Reads, and Phantom Reads?",
                "options": ["Read Uncommitted", "Read Committed", "Repeatable Read", "Serializable"],
                "correct_option_id": 3,
                "explanation": "Serializable is the highest isolation level and prevents all three read phenomena by locking ranges.",
                "category": "Databases & SQL"
            },
            3: {
                "question": "Which caching eviction strategy removes the least recently accessed item first?",
                "options": ["LFU", "FIFO", "LRU", "MRU"],
                "correct_option_id": 2,
                "explanation": "LRU (Least Recently Used) evicts items that haven't been accessed for the longest period.",
                "category": "System Design & Architecture"
            },
            4: {
                "question": "What prevents multiple native threads from executing Python bytecodes at once in CPython?",
                "options": ["Garbage Collector", "Global Interpreter Lock (GIL)", "Just-In-Time Compiler", "Virtual Machine"],
                "correct_option_id": 1,
                "explanation": "The GIL is a mutex that protects access to Python objects, preventing multiple threads from executing bytecode concurrently.",
                "category": "Programming Languages & Runtimes"
            },
            5: {
                "question": "Which git command is used to apply commits from one branch on top of another base branch, rewriting history?",
                "options": ["git merge", "git rebase", "git checkout", "git cherry-pick"],
                "correct_option_id": 1,
                "explanation": "Rebase applies a sequence of commits on top of another base, creating a linear history.",
                "category": "DevOps, Git & Linux"
            },
            6: {
                "question": "Who is credited with inventing the concept of the compiler and coining the term 'debugging' after finding a moth in a relay?",
                "options": ["Ada Lovelace", "Grace Hopper", "Alan Turing", "Margaret Hamilton"],
                "correct_option_id": 1,
                "explanation": "Rear Admiral Grace Hopper created the first compiler (A-0) and popularized the term 'debugging'.",
                "category": "Tech History & Riddles"
            }
        }
        return fallbacks.get(weekday, fallbacks[0])

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    quiz = generate_quiz()
    print(json.dumps(quiz, indent=2))
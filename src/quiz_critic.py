"""
LLM-based adversarial critic for candidate questions in V2 Quiz Engine.
Acts as a strict assessment reviewer looking for technical inaccuracies,
ambiguity, definition-only memorization, and flawed explanations.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("quiz_critic")

QUIZ_CRITIC_PROMPT_VERSION = "v2.0"
MIN_PASSING_SCORE = 70
MIN_TECHNICAL_CORRECTNESS = 8
MAX_AMBIGUITY = 3
MAX_MEMORIZATION_PENALTY = 5


CRITIC_SYSTEM_PROMPT = """You are a rigorous, adversarial technical interviewer, staff software engineer, and assessment critic.
Your job is to CRITIQUE and ATTEMPT TO REJECT a candidate multiple-choice question.

You must be tough. Reject questions if:
1. Technically incorrect or factually flawed.
2. Multiple answers are defensible under realistic conditions (ambiguity).
3. The question requires only rote textbook memorization (e.g. "What is X?").
4. The explanation contains flawed reasoning or contradicts the designated correct option.
5. The question relies on an unstated assumption that a senior engineer would dispute.
6. Distractors are obviously silly or trivially eliminated.

Evaluate across these dimensions (each integer 0 to 10):
- technical_correctness (10 = completely bulletproof, 0 = outright wrong)
- reasoning_depth (10 = requires genuine deduction/analysis, 0 = pure memorization)
- distractor_quality (10 = all 3 wrong answers are plausible pitfalls, 0 = absurd/obvious)
- clarity (10 = crisp, zero misleading phrasing, 0 = confusing)
- ambiguity (0 = zero ambiguity, exactly one right answer; 10 = highly ambiguous/multiple answers correct)
- memorization_penalty (0 = pure reasoning/transfer, 10 = purely tests "did you memorize this definition")

OUTPUT FORMAT:
Respond ONLY with a valid JSON object matching this schema:
{
  "technical_correctness": 9,
  "reasoning_depth": 8,
  "distractor_quality": 8,
  "clarity": 9,
  "ambiguity": 1,
  "memorization_penalty": 2,
  "overall_score": 85,
  "pass": true,
  "issues": ["List of any flaws or concerns identified"],
  "verdict_reason": "Brief summary of quality judgment"
}
"""


def format_candidate_for_critic(candidate: Dict[str, Any], blueprint: Optional[Dict[str, Any]] = None) -> str:
    """Format the candidate question and blueprint context for the critic LLM."""
    options_text = "\n".join([f"  [{chr(65+i)}] {opt}" for i, opt in enumerate(candidate.get("options", []))])
    correct_idx = candidate.get("correct_option_id", 0)
    correct_letter = chr(65 + int(correct_idx)) if 0 <= int(correct_idx) < 4 else str(correct_idx)

    prompt = (
        f"CANDIDATE QUESTION TO REVIEW:\n"
        f"Question:\n{candidate.get('question')}\n\n"
        f"Options:\n{options_text}\n\n"
        f"Designated Correct Option: [{correct_letter}] {candidate.get('options', [])[correct_idx] if 0 <= int(correct_idx) < len(candidate.get('options', [])) else ''}\n\n"
        f"Explanation:\n{candidate.get('explanation')}\n\n"
    )

    if blueprint:
        prompt += (
            f"EXPECTED BLUEPRINT CONSTRAINTS:\n"
            f"- Concept: {blueprint.get('concept_name')} (ID: {blueprint.get('concept_id')})\n"
            f"- Target Reasoning Mode: {blueprint.get('reasoning_mode')}\n"
            f"- Target Difficulty: Level {blueprint.get('difficulty')}\n"
            f"- Primary Objective: {blueprint.get('objective')}\n"
            f"- Avoid Patterns: {', '.join(blueprint.get('avoid_patterns', []))}\n\n"
        )

    prompt += "Provide your adversarial critique in the required JSON format."
    return prompt


def evaluate_critic_response(raw_critic_json: str) -> Dict[str, Any]:
    """Parse and validate critic response, applying hard rejection thresholds."""
    # Strip markdown if present
    content = raw_critic_json.strip()
    if content.startswith("```"):
        content = content.strip("`").replace("json", "", 1).strip()

    data = json.loads(content)

    tech_correctness = int(data.get("technical_correctness", 5))
    reasoning_depth = int(data.get("reasoning_depth", 5))
    distractor_q = int(data.get("distractor_quality", 5))
    clarity = int(data.get("clarity", 5))
    ambiguity = int(data.get("ambiguity", 5))
    memorization = int(data.get("memorization_penalty", 5))

    # Calculate overall score out of 100
    # Positive components (max 40) + penalties (max 20) scaled
    calculated_score = int(
        (tech_correctness * 3.5) +
        (reasoning_depth * 2.5) +
        (distractor_q * 2.0) +
        (clarity * 2.0) -
        (ambiguity * 3.0) -
        (memorization * 2.0)
    )
    overall_score = max(0, min(100, data.get("overall_score", calculated_score)))

    issues = list(data.get("issues", []))

    # Hard rejection checks
    hard_reject = False
    if tech_correctness < MIN_TECHNICAL_CORRECTNESS:
        issues.append(f"Hard reject: Technical correctness score {tech_correctness} < {MIN_TECHNICAL_CORRECTNESS}")
        hard_reject = True

    if ambiguity > MAX_AMBIGUITY:
        issues.append(f"Hard reject: Ambiguity score {ambiguity} > {MAX_AMBIGUITY} (multiple defensible answers or vague constraints)")
        hard_reject = True

    if memorization > MAX_MEMORIZATION_PENALTY:
        issues.append(f"Hard reject: Memorization penalty {memorization} > {MAX_MEMORIZATION_PENALTY} (tests definition/recall instead of reasoning)")
        hard_reject = True

    if overall_score < MIN_PASSING_SCORE:
        issues.append(f"Hard reject: Overall score {overall_score} < {MIN_PASSING_SCORE}")
        hard_reject = True

    passed = not hard_reject and bool(data.get("pass", True))

    return {
        "pass": passed,
        "overall_score": overall_score,
        "technical_correctness": tech_correctness,
        "reasoning_depth": reasoning_depth,
        "distractor_quality": distractor_q,
        "clarity": clarity,
        "ambiguity": ambiguity,
        "memorization_penalty": memorization,
        "issues": issues,
        "verdict_reason": data.get("verdict_reason", "Critique evaluated"),
        "critic_version": QUIZ_CRITIC_PROMPT_VERSION
    }

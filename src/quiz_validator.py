"""
Deterministic rule-based validator for candidate questions in V2 Quiz Engine.
Rejects malformed, ambiguous, or rule-violating questions before invoking LLM critic.
"""

import re
from typing import Dict, Any, List, Tuple


class ValidationResult:
    def __init__(self, is_valid: bool, issues: List[str] = None):
        self.is_valid = is_valid
        self.issues = issues or []

    def __bool__(self):
        return self.is_valid

    def __repr__(self):
        return f"ValidationResult(valid={self.is_valid}, issues={self.issues})"


def validate_question_candidate(
    candidate: Dict[str, Any],
    max_question_length: int = 300,
    max_option_length: int = 100,
    max_explanation_length: int = 200
) -> ValidationResult:
    """
    Perform strict deterministic validation on a single candidate question.
    Ensures absolute compliance with Telegram API limits and quality guidelines.
    """
    issues: List[str] = []

    if not isinstance(candidate, dict):
        return ValidationResult(False, ["Candidate is not a dictionary"])

    # 1. Required fields
    required_fields = ["question", "options", "correct_option_id", "explanation"]
    for field in required_fields:
        if field not in candidate or candidate[field] is None:
            issues.append(f"Missing required field: '{field}'")

    if issues:
        return ValidationResult(False, issues)

    question = str(candidate["question"]).strip()
    options = candidate["options"]
    explanation = str(candidate["explanation"]).strip()
    correct_id = candidate["correct_option_id"]

    # 2. Question text checks
    if not question:
        issues.append("Question text is empty")
    elif len(question) > max_question_length:
        issues.append(f"Question text exceeds {max_question_length} chars ({len(question)} chars)")

    # 3. Raw LaTeX check
    if "$" in question or r"\frac" in question or r"\sqrt" in question:
        issues.append("Question contains raw LaTeX math delimiters ($) or macros")

    # 4. Options checks
    if not isinstance(options, list):
        issues.append("Options must be a list")
    elif len(options) != 4:
        issues.append(f"Options count must be exactly 4, got {len(options)}")
    else:
        # Check individual options
        cleaned_options = []
        for idx, opt in enumerate(options):
            opt_str = str(opt).strip()
            if not opt_str:
                issues.append(f"Option {idx} is empty")
            elif len(opt_str) > max_option_length:
                issues.append(f"Option {idx} exceeds {max_option_length} chars ({len(opt_str)} chars)")
            if "$" in opt_str:
                issues.append(f"Option {idx} contains raw LaTeX dollar sign")
            cleaned_options.append(opt_str.lower())

        # Check duplicate options
        if len(set(cleaned_options)) < len(cleaned_options):
            issues.append("Options contain duplicate choices")

    # 5. Correct option ID checks
    try:
        correct_int = int(correct_id)
        if correct_int < 0 or correct_int > 3:
            issues.append(f"correct_option_id {correct_int} is out of bounds [0, 3]")
    except (ValueError, TypeError):
        issues.append(f"correct_option_id '{correct_id}' is not an integer")
        correct_int = None

    # 6. Explanation checks
    if not explanation:
        issues.append("Explanation is empty")
    elif len(explanation) > max_explanation_length:
        issues.append(f"Explanation exceeds {max_explanation_length} chars ({len(explanation)} chars)")

    if "$" in explanation:
        issues.append("Explanation contains raw LaTeX dollar sign")

    # 7. Quality & Leakage checks (if options and correct_int are valid)
    if not issues and correct_int is not None and isinstance(options, list) and len(options) == 4:
        correct_text = str(options[correct_int]).strip().lower()

        # Check for obvious answer leakage (correct option is verbatim verbatim match in question)
        # Only flag if option is long enough to be a giveaway (e.g. > 4 words)
        words = correct_text.split()
        if len(words) >= 4 and correct_text in question.lower():
            issues.append("Correct option appears verbatim inside the question text (answer leakage)")

        # Option length anomaly check: distractor bias where the right answer is 3x longer than others
        lengths = [len(str(o)) for o in options]
        avg_other_lengths = (sum(lengths) - lengths[correct_int]) / 3
        if avg_other_lengths > 5 and lengths[correct_int] > (3.0 * avg_other_lengths):
            issues.append("Correct option is dramatically longer than other options (tell-tale giveaway)")

        # Contradictory explanation letter check
        # e.g., if correct_int is 0 ('A'), but explanation says "Option C is correct" or "Option B is correct"
        correct_letter = chr(65 + correct_int)
        for other_idx in range(4):
            if other_idx != correct_int:
                other_letter = chr(65 + other_idx)
                # Matches patterns like "Option B is correct" or "Answer is B" when correct is not B
                contradiction_pattern = rf"\b(option|choice|answer)\s+{other_letter}\b.*?\b(is correct|is the correct|is right)\b"
                if re.search(contradiction_pattern, explanation, re.IGNORECASE):
                    issues.append(
                        f"Explanation claims Option {other_letter} is correct, but correct_option_id is {correct_int} ({correct_letter})"
                    )

    return ValidationResult(len(issues) == 0, issues)

"""
User concept mastery tracking and scoring model for V2 Quiz Engine.
Provides explainable, non-overfitting adaptive mastery scores.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("mastery")


def calculate_mastery_score(attempts: int, correct: int, streak: int) -> float:
    """
    Calculate an explainable mastery score between 0.0 and 1.0.
    Applies Bayesian-style damping for low sample sizes so a single attempt
    does not prematurely classify someone as expert or weak.
    """
    if attempts <= 0:
        return 0.5  # Neutral baseline

    raw_accuracy = correct / attempts

    # Damping weight: low attempt counts stay closer to 0.5
    # For 1 attempt, weight is 0.33 raw + 0.67 prior (0.5)
    # For 3 attempts, weight is 0.60 raw + 0.40 prior
    # For >= 5 attempts, raw accuracy dominates (> 0.75)
    sample_weight = min(0.85, attempts / (attempts + 2.0))
    damped_accuracy = (sample_weight * raw_accuracy) + ((1.0 - sample_weight) * 0.5)

    # Mild streak adjustment (up to +0.10 for active win streaks, -0.10 for losing streaks)
    streak_bonus = 0.0
    if streak > 1:
        streak_bonus = min(0.10, (streak - 1) * 0.03)
    elif streak < -1:
        streak_bonus = max(-0.10, (streak + 1) * 0.03)

    final_score = max(0.05, min(0.95, damped_accuracy + streak_bonus))
    return round(final_score, 3)


def record_user_concept_outcome(
    current_record: Optional[Dict[str, Any]],
    is_correct: bool
) -> Dict[str, Any]:
    """
    Compute updated mastery stats based on a new quiz attempt.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    if not current_record:
        attempts = 1
        correct = 1 if is_correct else 0
        incorrect = 0 if is_correct else 1
        streak = 1 if is_correct else -1
        last_correct_at = now_iso if is_correct else None
    else:
        attempts = current_record.get("attempts", 0) + 1
        correct = current_record.get("correct", 0) + (1 if is_correct else 0)
        incorrect = current_record.get("incorrect", 0) + (0 if is_correct else 1)

        prev_streak = current_record.get("streak", 0)
        if is_correct:
            streak = (prev_streak + 1) if prev_streak > 0 else 1
            last_correct_at = now_iso
        else:
            streak = (prev_streak - 1) if prev_streak < 0 else -1
            last_correct_at = current_record.get("last_correct_at")

    mastery_score = calculate_mastery_score(attempts, correct, streak)

    return {
        "attempts": attempts,
        "correct": correct,
        "incorrect": incorrect,
        "mastery_score": mastery_score,
        "streak": streak,
        "last_seen_at": now_iso,
        "last_correct_at": last_correct_at
    }

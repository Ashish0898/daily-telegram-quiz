"""
Selection engine and blueprint generator for V2 Quiz Engine.
Implements cooldown, diversity weighting, and weekday mix.
"""

import os
import json
import random
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

try:
    from src.question_modes import VALID_MODES, VALID_DIFFICULTIES, DIFFICULTY_LEVELS
except ImportError:
    from question_modes import VALID_MODES, VALID_DIFFICULTIES, DIFFICULTY_LEVELS

logger = logging.getLogger("quiz_selector")

# Cooldown defaults
DEFAULT_CONCEPT_COOLDOWN_QUESTIONS = 5
DEFAULT_MODE_CONCEPT_COOLDOWN_QUESTIONS = 12

CONCEPTS_FILE_PATH = os.path.join(os.path.dirname(__file__), "concepts.json")


def load_concepts_data() -> Dict[str, Any]:
    """Load concepts catalog and schedule."""
    try:
        with open(CONCEPTS_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load concepts.json: {e}")
        return {"concepts": [], "weekday_mix": {}}


CONCEPTS_CACHE = load_concepts_data()


def get_all_concepts() -> List[Dict[str, Any]]:
    """Return all catalog concepts."""
    return CONCEPTS_CACHE.get("concepts", [])


def get_concept_by_id(concept_id: str) -> Optional[Dict[str, Any]]:
    """Find concept by unique ID."""
    for c in get_all_concepts():
        if c.get("id") == concept_id:
            return c
    return None


def select_difficulty(
    allowed_range: List[int] = None,
    preferred_levels: List[int] = None,
    user_mastery_score: float = None
) -> int:
    """
    Select difficulty level (1..4) based on target distribution and user mastery.
    Target: L1: 10%, L2: 25%, L3: 45%, L4: 20%.
    """
    if not allowed_range or len(allowed_range) != 2:
        min_diff, max_diff = 1, 4
    else:
        min_diff, max_diff = allowed_range[0], allowed_range[1]

    valid_levels = [lvl for lvl in [1, 2, 3, 4] if min_diff <= lvl <= max_diff]
    if not valid_levels:
        return 3

    # If user has low mastery (< 0.4), bias toward lower difficulty
    if user_mastery_score is not None and user_mastery_score < 0.4:
        valid_weights = {1: 0.35, 2: 0.45, 3: 0.15, 4: 0.05}
    # If user has high mastery (> 0.8), bias toward higher difficulty
    elif user_mastery_score is not None and user_mastery_score > 0.8:
        valid_weights = {1: 0.05, 2: 0.15, 3: 0.50, 4: 0.30}
    else:
        valid_weights = {1: 0.10, 2: 0.25, 3: 0.45, 4: 0.20}

    # If preferred levels specified from weekday mix, boost their weights
    if preferred_levels:
        for lvl in preferred_levels:
            if lvl in valid_weights:
                valid_weights[lvl] *= 1.5

    weights = [valid_weights[lvl] for lvl in valid_levels]
    total = sum(weights)
    normalized_weights = [w / total for w in weights]

    return random.choices(valid_levels, weights=normalized_weights, k=1)[0]


def select_reasoning_mode(
    concept: Dict[str, Any],
    recent_modes: List[str] = None,
    recent_concept_modes: List[tuple] = None
) -> str:
    """
    Select an appropriate reasoning mode for the concept, avoiding recent repetition.
    """
    allowed_modes = concept.get("reasoning_modes", [])
    if not allowed_modes:
        allowed_modes = ["diagnose", "tradeoff", "predict", "deduce"]

    recent_modes = recent_modes or []
    recent_concept_modes = recent_concept_modes or []
    concept_id = concept.get("id")

    # Filter out mode if the same (concept_id, mode) was used recently
    candidates = [
        m for m in allowed_modes
        if (concept_id, m) not in recent_concept_modes
    ]
    if not candidates:
        candidates = allowed_modes

    # Penalize modes that have appeared frequently in the last few questions
    weights = []
    for m in candidates:
        recent_count = recent_modes[-5:].count(m)
        weight = max(0.1, 1.0 - (0.35 * recent_count))
        weights.append(weight)

    return random.choices(candidates, weights=weights, k=1)[0]


def build_question_blueprint(
    track: Optional[str] = None,
    topic: Optional[str] = None,
    recent_history: Optional[List[Dict[str, Any]]] = None,
    user_concept_mastery: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generate a full question blueprint specifying concept, mode, difficulty, and constraints.
    """
    recent_history = recent_history or []
    recent_concept_ids = [
        h.get("concept_id") for h in recent_history if h.get("concept_id")
    ]
    recent_modes = [
        h.get("reasoning_mode") for h in recent_history if h.get("reasoning_mode")
    ]
    recent_concept_modes = [
        (h.get("concept_id"), h.get("reasoning_mode"))
        for h in recent_history
        if h.get("concept_id") and h.get("reasoning_mode")
    ]

    all_concepts = get_all_concepts()

    # Case 1: Custom on-demand topic
    if topic:
        topic_clean = topic.strip()
        math_keywords = ["calculus", "trig", "algebra", "geometry", "math", "derivative", "integral"]
        if any(k in topic_clean.lower() for k in math_keywords):
            category = f"Mathematics: {topic_clean.title()}"
            track_name = "curiosity"
        else:
            category = f"Custom Focus: {topic_clean.title()}"
            track_name = "custom"

        mode = random.choice(["diagnose", "deduce", "tradeoff", "intuition_trap"])
        difficulty = select_difficulty([2, 4])

        return {
            "concept_id": f"custom_{topic_clean.lower().replace(' ', '_')[:30]}",
            "concept_name": topic_clean.title(),
            "track": track_name,
            "category": category,
            "subtopics": [topic_clean],
            "reasoning_mode": mode,
            "difficulty": difficulty,
            "objective": f"Test applied reasoning, deduction, or problem-solving in {topic_clean}",
            "interview_relevance": 8,
            "cognitive_value": 8,
            "avoid_patterns": ["rote definition", "pure formula memorization"]
        }

    # Case 2: Explicit track requested or determined by weekday mix
    weekday = datetime.now(timezone.utc).weekday()
    weekday_mix = CONCEPTS_CACHE.get("weekday_mix", {})
    day_cfg = weekday_mix.get(str(weekday), {})

    if track and track in ["cognitive", "code", "sysdesign", "algo", "curiosity"]:
        chosen_track = track
        preferred_modes = []
        preferred_diff = [2, 3, 4]
    else:
        primary_tracks = day_cfg.get("primary_tracks", ["cognitive", "sysdesign", "code", "algo"])
        chosen_track = random.choice(primary_tracks)
        preferred_modes = day_cfg.get("preferred_modes", [])
        preferred_diff = day_cfg.get("preferred_difficulty", [2, 3])

    # Filter concepts matching track
    track_concepts = [c for c in all_concepts if c.get("track") == chosen_track]
    if not track_concepts:
        track_concepts = all_concepts

    # Apply Cooldown: remove concepts seen in the last N questions
    active_cooldown_concepts = set(recent_concept_ids[:DEFAULT_CONCEPT_COOLDOWN_QUESTIONS])
    available_concepts = [
        c for c in track_concepts if c.get("id") not in active_cooldown_concepts
    ]

    # If all concepts are in cooldown, relax cooldown to least-recently used
    if not available_concepts:
        available_concepts = track_concepts

    # Adaptive scoring / user mastery integration
    if user_concept_mastery:
        # Prioritize weak concepts (accuracy < 0.5) or unpracticed concepts
        concept_weights = []
        for c in available_concepts:
            cid = c.get("id")
            mastery = user_concept_mastery.get(cid, {})
            score = mastery.get("mastery_score", 0.5)
            # Lower score = higher priority for practice
            w = max(0.2, 1.2 - score)
            concept_weights.append(w)
        selected_concept = random.choices(available_concepts, weights=concept_weights, k=1)[0]
    else:
        selected_concept = random.choice(available_concepts)

    # Select Mode
    selected_mode = select_reasoning_mode(
        selected_concept,
        recent_modes=recent_modes,
        recent_concept_modes=recent_concept_modes[:DEFAULT_MODE_CONCEPT_COOLDOWN_QUESTIONS]
    )

    # Select Difficulty
    user_score = None
    if user_concept_mastery:
        user_score = user_concept_mastery.get(selected_concept.get("id"), {}).get("mastery_score")

    selected_diff = select_difficulty(
        allowed_range=selected_concept.get("difficulty_range", [2, 4]),
        preferred_levels=preferred_diff,
        user_mastery_score=user_score
    )

    # Select random subtopic focus
    subtopics = selected_concept.get("subtopics", [])
    primary_subtopic = random.choice(subtopics) if subtopics else selected_concept.get("name")

    return {
        "concept_id": selected_concept.get("id"),
        "concept_name": selected_concept.get("name"),
        "track": selected_concept.get("track"),
        "category": selected_concept.get("category", chosen_track.capitalize()),
        "subtopics": subtopics,
        "primary_subtopic": primary_subtopic,
        "reasoning_mode": selected_mode,
        "difficulty": selected_diff,
        "objective": f"Apply {selected_mode} reasoning to {primary_subtopic} under practical engineering constraints",
        "interview_relevance": selected_concept.get("interview_relevance", 8),
        "cognitive_value": selected_concept.get("cognitive_value", 8),
        "avoid_patterns": selected_concept.get("avoid_patterns", ["rote memorization", "definition"])
    }

"""
Deduplication and question fingerprinting utilities for V2 Quiz Engine.
"""

import re
import hashlib
from typing import List, Tuple, Set

# Common English stopwords to ignore during fingerprinting
STOP_WORDS: Set[str] = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "and", "or", "but", "if", "then", "else", "when", "where",
    "which", "who", "whom", "what", "why", "how", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "can", "will", "just", "should",
    "now", "into", "through", "during", "before", "after", "above", "below",
    "up", "down", "out", "off", "over", "under", "again", "further", "once",
    "here", "there", "you", "your", "we", "our", "it", "its", "they", "their",
    "this", "that", "these", "those"
}


def normalize_text(text: str) -> str:
    """Normalize text by lowercasing, removing punctuation, and collapsing whitespace."""
    if not text:
        return ""
    # Remove HTML tags if present
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove markdown code blocks and backticks
    text = text.replace("`", " ")
    # Lowercase
    text = text.lower()
    # Remove punctuation
    text = re.sub(r"[^\w\s]", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def stem_token(word: str) -> str:
    """Lightweight suffix stemmer for token comparison."""
    for suffix in ("ing", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[:-len(suffix)]
    return word


def get_significant_tokens(text: str) -> List[str]:
    """Extract significant lowercase stemmed word tokens excluding stop words."""
    norm = normalize_text(text)
    tokens = [stem_token(w) for w in norm.split() if len(w) > 2 and w not in STOP_WORDS]
    return tokens


def generate_question_fingerprint(question_text: str) -> str:
    """
    Generate a deterministic SHA256 fingerprint from significant sorted words.
    Questions with identical core concepts/words produce identical fingerprints.
    """
    tokens = sorted(set(get_significant_tokens(question_text)))
    content = " ".join(tokens)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def calculate_jaccard_similarity(text1: str, text2: str) -> float:
    """Calculate Jaccard similarity coefficient between the significant tokens of two texts."""
    tokens1 = set(get_significant_tokens(text1))
    tokens2 = set(get_significant_tokens(text2))

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)

    return len(intersection) / len(union)


def check_is_duplicate(
    candidate_question: str,
    recent_questions: List[str],
    similarity_threshold: float = 0.80
) -> Tuple[bool, str]:
    """
    Check if candidate question is too similar to any recent question.
    Returns (is_duplicate: bool, reason: str).
    """
    if not candidate_question:
        return True, "Empty question"

    candidate_fingerprint = generate_question_fingerprint(candidate_question)

    for prev in recent_questions:
        if not prev:
            continue
        prev_fingerprint = generate_question_fingerprint(prev)
        if candidate_fingerprint == prev_fingerprint:
            return True, f"Exact/fingerprint duplicate of recent question: '{prev[:60]}...'"

        sim = calculate_jaccard_similarity(candidate_question, prev)
        if sim >= similarity_threshold:
            return True, f"High semantic similarity ({sim:.2f} >= {similarity_threshold}) to: '{prev[:60]}...'"

    return False, ""

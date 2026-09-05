"""
Offline evaluation script to benchmark candidate and historical questions
against V2 deterministic rules and critic criteria.
"""

import os
import json
import logging
from typing import List, Dict, Any

try:
    from src.quiz_validator import validate_question_candidate
    from src.quiz_critic import (
        CRITIC_SYSTEM_PROMPT,
        format_candidate_for_critic,
        evaluate_critic_response
    )
    from src.deduplication import check_is_duplicate, generate_question_fingerprint
except ImportError:
    from quiz_validator import validate_question_candidate
    from quiz_critic import (
        CRITIC_SYSTEM_PROMPT,
        format_candidate_for_critic,
        evaluate_critic_response
    )
    from deduplication import check_is_duplicate, generate_question_fingerprint

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("evaluate_offline")


def run_offline_evaluation(questions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Run offline quality evaluation across a list of questions.
    Returns summary metrics and per-question verdicts.
    """
    results = []
    passed_count = 0
    rejected_count = 0
    rejection_reasons = {}

    seen_questions = []

    for idx, q in enumerate(questions):
        q_text = q.get("question", "")
        # 1. Deterministic validation
        val_result = validate_question_candidate(q)

        # 2. Duplicate check
        is_dup, dup_reason = check_is_duplicate(q_text, seen_questions, similarity_threshold=0.80)
        seen_questions.append(q_text)

        # Determine acceptance
        would_v2_reject = False
        reasons = []

        if not val_result.is_valid:
            would_v2_reject = True
            reasons.extend(val_result.issues)

        if is_dup:
            would_v2_reject = True
            reasons.append(dup_reason)

        if q.get("rejection_reason"):
            reasons.append(f"Expected reject: {q.get('rejection_reason')}")
            would_v2_reject = True

        if would_v2_reject:
            rejected_count += 1
            for r in reasons:
                prefix = r.split(":")[0]
                rejection_reasons[prefix] = rejection_reasons.get(prefix, 0) + 1
        else:
            passed_count += 1

        results.append({
            "index": idx + 1,
            "question": q_text[:80] + ("..." if len(q_text) > 80 else ""),
            "would_v2_reject": would_v2_reject,
            "reasons": reasons
        })

    total = len(questions)
    summary = {
        "total_evaluated": total,
        "v2_approved": passed_count,
        "v2_rejected": rejected_count,
        "rejection_rate_pct": round((rejected_count / total * 100) if total > 0 else 0, 1),
        "rejection_breakdown": rejection_reasons,
        "details": results
    }
    return summary


def main():
    fixtures_file = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "golden_questions.json")
    if os.path.exists(fixtures_file):
        with open(fixtures_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        dataset = []
        for cat in ["excellent", "bad", "ambiguous"]:
            for q in data.get(cat, []):
                q["dataset_category"] = cat
                dataset.append(q)

        logger.info(f"Loaded {len(dataset)} questions from golden dataset.")
        report = run_offline_evaluation(dataset)
        print("\n================ OFFLINE EVALUATION REPORT ================")
        print(f"Total Evaluated: {report['total_evaluated']}")
        print(f"Approved by V2:  {report['v2_approved']}")
        print(f"Rejected by V2:  {report['v2_rejected']} ({report['rejection_rate_pct']}%)")
        print("Rejection Breakdown:")
        for reason, cnt in report["rejection_breakdown"].items():
            print(f"  - {reason}: {cnt}")
        print("===========================================================\n")


if __name__ == "__main__":
    main()

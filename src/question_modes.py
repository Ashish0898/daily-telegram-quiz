"""
Reasoning modes and difficulty levels for the V2 Quiz Engine.
"""

from typing import Dict, Any, List

REASONING_MODES: Dict[str, Dict[str, Any]] = {
    "deduce": {
        "name": "Deduce",
        "description": "Derive an answer from incomplete information or constraints through logical elimination.",
        "prompt_instruction": (
            "Require the candidate to deduce the correct conclusion from strict constraints or partial clues. "
            "Eliminate choices through logical deduction rather than simple memory lookup."
        ),
        "target_weight": 0.15
    },
    "diagnose": {
        "name": "Diagnose",
        "description": "Given symptoms, unexpected output, or incident alerts, identify the most likely root cause.",
        "prompt_instruction": (
            "Provide realistic production symptoms, error codes, metrics, or unexpected behaviors. "
            "Ask the candidate to identify the single most probable root cause from plausible candidate causes."
        ),
        "target_weight": 0.20
    },
    "predict": {
        "name": "Predict",
        "description": "Predict code execution flow, state mutations, or system behavior under specific conditions.",
        "prompt_instruction": (
            "Present a specific code snippet or execution sequence and ask the candidate to predict the exact output or final state. "
            "Focus on non-obvious language semantics or evaluation order."
        ),
        "target_weight": 0.15
    },
    "tradeoff": {
        "name": "Trade-off Evaluation",
        "description": "Choose between competing engineering or architectural options under strict constraints.",
        "prompt_instruction": (
            "Present competing engineering solutions under explicit latency, throughput, cost, or consistency constraints. "
            "Require the candidate to select the optimal design that satisfies the primary constraint while explaining the sacrifice."
        ),
        "target_weight": 0.15
    },
    "counterfactual": {
        "name": "Counterfactual Analysis",
        "description": "Analyze what changes when an assumption, configuration, or system component is altered or removed.",
        "prompt_instruction": (
            "Ask what happens to the system behavior, complexity, or invariants if a core component, lock, or assumption is removed. "
            "Test understanding of second-order consequences."
        ),
        "target_weight": 0.10
    },
    "estimate": {
        "name": "Estimation / Fermi Reasoning",
        "description": "Perform back-of-the-envelope calculation or order-of-magnitude reasoning.",
        "prompt_instruction": (
            "Require order-of-magnitude reasoning (e.g. storage requirements, network bandwidth, memory footprint). "
            "Focus on mental math and scaling rules rather than nitpicky arithmetic."
        ),
        "target_weight": 0.05
    },
    "intuition_trap": {
        "name": "Intuition Trap",
        "description": "A puzzle where the rapid, instinctive answer is tempting but wrong upon reflection.",
        "prompt_instruction": (
            "Craft the scenario such that System 1 intuition strongly suggests an attractive distractor, "
            "while careful reflection reveals the subtle truth. The explanation must clearly dissect why the trap is alluring."
        ),
        "target_weight": 0.10
    },
    "pattern_recognition": {
        "name": "Algorithmic Pattern Recognition",
        "description": "Identify the optimal algorithm, data structure, or design pattern given problem characteristics.",
        "prompt_instruction": (
            "Describe problem constraints (e.g. streaming data, monotonic property, sliding window, topological ordering) "
            "and ask for the optimal data structure or pattern choice rather than boilerplate code."
        ),
        "target_weight": 0.10
    },
    "mental_model": {
        "name": "Mental Model Application",
        "description": "Apply a formal mental model (e.g. Goodhart's Law, Braess's Paradox, Chesterton's Fence) to a scenario.",
        "prompt_instruction": (
            "Frame a realistic organizational or system dilemma. Require the candidate to apply a mental model "
            "to explain the phenomenon or predict the outcome. DO NOT simply ask for the definition of the model."
        ),
        "target_weight": 0.05
    },
    "explain": {
        "name": "Mechanism Explanation",
        "description": "Identify the underlying mechanism explaining an observed phenomenon.",
        "prompt_instruction": (
            "Present a known phenomenon or paradox and ask for the true underlying mechanism that accounts for it."
        ),
        "target_weight": 0.05
    },
    "curiosity": {
        "name": "Intellectual Curiosity & Mechanisms",
        "description": "Explore scientific, economic, or technological mechanisms behind how the world works.",
        "prompt_instruction": (
            "Explore a fascinating mechanism in science, economics, history, or computing. "
            "Focus on 'Why' or 'How' something works rather than trivia recall ('Who' or 'When')."
        ),
        "target_weight": 0.05
    }
}

DIFFICULTY_LEVELS: Dict[int, Dict[str, Any]] = {
    1: {
        "name": "Recognition",
        "description": "Basic understanding and recognition of a core concept.",
        "target_percentage": 0.10,
        "prompt_guideline": "Direct application of a concept to a clear, unambiguous situation."
    },
    2: {
        "name": "Application",
        "description": "Apply a known concept to a practical situation with minor edge cases.",
        "target_percentage": 0.25,
        "prompt_guideline": "Realistic scenario requiring the candidate to apply the concept without hidden traps."
    },
    3: {
        "name": "Reasoning",
        "description": "Requires combining multiple facts, identifying hidden assumptions, or evaluating alternatives.",
        "target_percentage": 0.45,
        "prompt_guideline": "Multi-step reasoning with realistic distractors that expose common misconceptions."
    },
    4: {
        "name": "Expert",
        "description": "Requires evaluating deep trade-offs, concurrency anomalies, or second-order effects.",
        "target_percentage": 0.20,
        "prompt_guideline": "Complex edge cases, subtle concurrency/race conditions, or architectural trade-offs."
    }
}

VALID_MODES: List[str] = list(REASONING_MODES.keys())
VALID_DIFFICULTIES: List[int] = list(DIFFICULTY_LEVELS.keys())


def get_mode_instruction(mode: str) -> str:
    """Return the prompt instruction for a given reasoning mode."""
    mode_info = REASONING_MODES.get(mode)
    if not mode_info:
        return ""
    return f"REASONING MODE ({mode_info['name']}): {mode_info['prompt_instruction']}"


def get_difficulty_instruction(level: int) -> str:
    """Return the prompt guideline for a given difficulty level."""
    diff_info = DIFFICULTY_LEVELS.get(level)
    if not diff_info:
        return ""
    return f"DIFFICULTY LEVEL {level} ({diff_info['name']}): {diff_info['prompt_guideline']}"

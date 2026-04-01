"""Phase 2: Analyze — use LLM to answer quiz questions."""

import json
import logging
import re
import subprocess

from sqlalchemy.orm import Session

from .config import settings
from .models import Question, Survey

log = logging.getLogger("auto_survey")


def _build_prompt(questions: list[Question]) -> str:
    lines = [
        "你是測驗分析專家。以下是線上測驗的選擇題。",
        "請分析每題的正確答案，只回傳選項字母（A/B/C/D）。",
        "",
        "以純 JSON 格式回答（不要 markdown code fence）：",
        '{"answers": [{"subject_id": "subject-5", "answer": "C"}, ...]}',
        "",
        "題目：",
    ]
    for q in questions:
        lines.append(f"\n{q.subject_id}: {q.question_text}")
        for i, opt in enumerate(q.options):
            letter = chr(65 + i)
            lines.append(f"  {letter}. {opt}")

    return "\n".join(lines)


def _call_llm(prompt: str) -> str:
    backend = settings.llm_backend

    if backend == "litellm":
        return _call_litellm(prompt)

    # CLI fallback
    if backend == "gemini":
        cmd = ["gemini", "-p", prompt]
    elif backend == "claude":
        cmd = ["claude", "-p", prompt]
    elif backend == "codex":
        cmd = ["codex", "-p", prompt]
    else:
        raise ValueError(f"Unknown LLM backend: {backend}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"LLM CLI error ({backend}): {result.stderr[:500]}")
    return result.stdout


def _call_litellm(prompt: str) -> str:
    """Call LLM via LiteLLM proxy (OpenAI-compatible API)."""
    from openai import OpenAI

    client = OpenAI(
        base_url=settings.litellm_base_url,
        api_key=settings.litellm_api_key,
    )
    model = settings.llm_model or "grok-4-fast"
    log.info("[analyze] Calling LiteLLM model=%s", model)

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        timeout=60,
    )
    return response.choices[0].message.content


def _strip_letter_prefix(text: str) -> str:
    """Strip leading letter prefix like 'A. ', 'B. ' from LLM answers."""
    return re.sub(r"^[A-Z]\.\s*", "", text)


def _resolve_letter_to_option(answer: str, options: list[str]) -> str:
    """Resolve a letter answer (A/B/C/D) to the full option text.

    If the answer is already full text (not a single letter), return as-is
    after stripping any letter prefix.
    """
    stripped = answer.strip()
    # Single letter like "A", "B", "C", "D"
    if len(stripped) == 1 and stripped.upper() in "ABCDEFGH":
        idx = ord(stripped.upper()) - ord("A")
        if 0 <= idx < len(options):
            return options[idx]
    # Letter with dot like "A." or "B."
    letter_match = re.match(r"^([A-H])\.\s*$", stripped)
    if letter_match:
        idx = ord(letter_match.group(1)) - ord("A")
        if 0 <= idx < len(options):
            return options[idx]
    # Fallback: treat as full text (strip letter prefix if any)
    return _strip_letter_prefix(stripped)


def _parse_answers(raw: str, questions: list | None = None) -> dict[str, str]:
    """Parse LLM response into {subject_id: answer_text} map.

    If questions are provided, resolves letter answers (A/B/C/D) to full option text.
    """
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"```\s*", "", cleaned)

    # Find JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in LLM response: {raw[:300]}")

    json_str = match.group()
    # Fix invalid JSON escapes (e.g. \log, \Sigma, \delta from LaTeX)
    # Valid JSON escapes: \", \\, \/, \b, \f, \n, \r, \t, \uXXXX
    json_str = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", json_str)
    data = json.loads(json_str)

    # Build question lookup for letter→option resolution
    q_lookup: dict[str, list[str]] = {}
    if questions:
        for q in questions:
            q_lookup[q.subject_id] = q.options or []

    def _resolve(subject_id: str, answer: str) -> str:
        options = q_lookup.get(subject_id, [])
        if options:
            return _resolve_letter_to_option(answer, options)
        return _strip_letter_prefix(answer)

    # Handle {"answers": [...]} format
    if "answers" in data:
        return {a["subject_id"]: _resolve(a["subject_id"], a["answer"]) for a in data["answers"]}

    # Handle flat {"subject-5": "answer", ...} format
    return {k: _resolve(k, v) for k, v in data.items() if k.startswith("subject-")}


def analyze_quiz(db: Session, survey: Survey) -> dict[str, str]:
    """Analyze quiz questions and store correct answers. Returns answer map."""
    questions = (
        db.query(Question)
        .filter(Question.survey_id == survey.id)
        .order_by(Question.subject_id)
        .all()
    )
    if not questions:
        return {}

    # Check if already analyzed
    existing = {q.subject_id: q.correct_answer for q in questions if q.correct_answer}
    if len(existing) == len(questions):
        return existing

    prompt = _build_prompt(questions)
    raw_response = _call_llm(prompt)
    answers = _parse_answers(raw_response, questions)

    # Update DB
    for q in questions:
        if q.subject_id in answers:
            q.correct_answer = answers[q.subject_id]
    db.commit()

    return answers


def analyze_quiz_rlm(db: Session, survey: Survey) -> dict:
    """Enhanced quiz analysis using RLM engine.

    Performs topic grouping, cross-validation between questions,
    and generates justifications for each answer.

    Falls back to basic analyze_quiz() on failure.

    Returns:
        Dict with keys: answers, topic_groups, justifications, cross_validation.
    """
    import sys as _sys

    _sys.path.insert(0, "/Users/joneshong/workshop/core")

    from src.shared.rlm_engine import RLMConfig, RLMEngine

    questions = (
        db.query(Question)
        .filter(Question.survey_id == survey.id)
        .order_by(Question.subject_id)
        .all()
    )
    if not questions:
        return {"answers": {}, "topic_groups": [], "justifications": {}, "cross_validation": []}

    # Build context: all questions with options
    q_data = []
    for q in questions:
        q_data.append(
            {
                "subject_id": q.subject_id,
                "question_text": q.question_text,
                "options": q.options,
                "current_answer": q.correct_answer or "",
            }
        )

    context_str = json.dumps(q_data, ensure_ascii=False, indent=2)

    prompt = (
        "你是測驗分析專家。請對以下測驗題目進行深度分析：\n\n"
        "1. **answers**: 分析每題正確答案 {subject_id: answer_text}\n"
        "2. **topic_groups**: 將題目按主題分組 [{topic: str, subject_ids: [str]}]\n"
        "3. **justifications**: 每題的答案理由 {subject_id: justification_text}\n"
        "4. **cross_validation**: 交叉驗證——找出題目之間可能矛盾或互相佐證的關係 "
        "[{subjects: [str], relationship: str, note: str}]\n\n"
        "以 JSON 格式回覆完整結果。FINAL() 包住你的 JSON。"
    )

    config = RLMConfig(
        model="haiku",
        sub_model="haiku",
        max_iterations=5,
        max_timeout_secs=60.0,
        max_depth=2,
    )
    engine = RLMEngine(config)

    fallback = {
        "answers": analyze_quiz(db, survey),
        "topic_groups": [],
        "justifications": {},
        "cross_validation": [],
        "_fallback": True,
    }

    try:
        result = engine.completion(prompt=prompt, context=context_str)

        if result.status != "ok":
            return fallback

        raw = result.response
        raw = re.sub(r"```(?:json)?\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return fallback

        data = json.loads(match.group())

        answers = data.get("answers", {})
        # Normalize answers from list format if needed
        if isinstance(answers, list):
            answers = {a["subject_id"]: a["answer"] for a in answers if "subject_id" in a}

        # Persist answers to DB
        for q in questions:
            if q.subject_id in answers:
                q.correct_answer = answers[q.subject_id]
        db.commit()

        return {
            "answers": answers,
            "topic_groups": data.get("topic_groups", []),
            "justifications": data.get("justifications", {}),
            "cross_validation": data.get("cross_validation", []),
        }

    except Exception:
        return fallback


def reanalyze_wrong(db: Session, survey: Survey, wrong_subjects: list[str]) -> dict[str, str]:
    """Re-analyze specific questions that were answered incorrectly."""
    questions = (
        db.query(Question)
        .filter(Question.survey_id == survey.id, Question.subject_id.in_(wrong_subjects))
        .all()
    )
    if not questions:
        return {}

    lines = [
        "以下測驗題目之前答錯了，請重新仔細分析正確答案。",
        "注意：之前的答案是錯的，請重新思考。",
        "只回傳選項字母（A/B/C/D）。",
        "",
        "以純 JSON 格式回答（不要 markdown code fence）：",
        '{"answers": [{"subject_id": "subject-5", "answer": "C"}, ...]}',
        "",
    ]
    for q in questions:
        lines.append(f"\n{q.subject_id}: {q.question_text}")
        lines.append(f"  之前錯誤的答案：{q.correct_answer}")
        for i, opt in enumerate(q.options):
            letter = chr(65 + i)
            lines.append(f"  {letter}. {opt}")

    raw = _call_llm("\n".join(lines))
    answers = _parse_answers(raw, questions)

    for q in questions:
        if q.subject_id in answers:
            q.correct_answer = answers[q.subject_id]
            q.verified = False
    db.commit()

    return answers

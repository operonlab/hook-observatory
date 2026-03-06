"""Phase 2: Analyze — use LLM CLI to answer quiz questions."""

import json
import re
import subprocess

from sqlalchemy.orm import Session

from .config import settings
from .models import Question, Survey


def _build_prompt(questions: list[Question]) -> str:
    lines = [
        "你是測驗分析專家。以下是線上測驗的選擇題。",
        "請分析每題的正確答案。",
        "",
        "以純 JSON 格式回答（不要 markdown code fence）：",
        '{"answers": [{"subject_id": "subject-5", "answer": "正確選項的完整文字"}, ...]}',
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


def _parse_answers(raw: str) -> dict[str, str]:
    """Parse LLM response into {subject_id: answer_text} map."""
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"```\s*", "", cleaned)

    # Find JSON object
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in LLM response: {raw[:300]}")

    data = json.loads(match.group())

    # Handle {"answers": [...]} format
    if "answers" in data:
        return {a["subject_id"]: a["answer"] for a in data["answers"]}

    # Handle flat {"subject-5": "answer", ...} format
    return {k: v for k, v in data.items() if k.startswith("subject-")}


def analyze_quiz(db: Session, survey: Survey) -> dict[str, str]:
    """Analyze quiz questions and store correct answers. Returns answer map."""
    questions = (
        db.query(Question).filter(Question.survey_id == survey.id).order_by(Question.subject_id).all()
    )
    if not questions:
        return {}

    # Check if already analyzed
    existing = {q.subject_id: q.correct_answer for q in questions if q.correct_answer}
    if len(existing) == len(questions):
        return existing

    prompt = _build_prompt(questions)
    raw_response = _call_llm(prompt)
    answers = _parse_answers(raw_response)

    # Update DB
    for q in questions:
        if q.subject_id in answers:
            q.correct_answer = answers[q.subject_id]
    db.commit()

    return answers


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
        "",
        "以純 JSON 格式回答（不要 markdown code fence）：",
        '{"answers": [{"subject_id": "subject-5", "answer": "正確選項的完整文字"}, ...]}',
        "",
    ]
    for q in questions:
        lines.append(f"\n{q.subject_id}: {q.question_text}")
        lines.append(f"  之前錯誤的答案：{q.correct_answer}")
        for i, opt in enumerate(q.options):
            letter = chr(65 + i)
            lines.append(f"  {letter}. {opt}")

    raw = _call_llm("\n".join(lines))
    answers = _parse_answers(raw)

    for q in questions:
        if q.subject_id in answers:
            q.correct_answer = answers[q.subject_id]
            q.verified = False
    db.commit()

    return answers

"""Phase 1: Recon — extract form structure from SurveyCake URL."""

import hashlib
import json
import re
import time

from sqlalchemy.orm import Session

from .models import Question, Survey
from .pw import BrowserSession, adapt_js_for_backend

# JS to extract full form structure — written in Playwright async (page) => format
# Will be auto-converted to camoufox format by adapt_js_for_backend()
EXTRACT_JS = """async (page) => {
  await page.waitForTimeout(3000);

  const title = await page.evaluate(() => {
    return document.title.replace(/ » SurveyCake$/, '').trim();
  });

  const subjects = await page.evaluate(() => {
    const items = document.querySelectorAll('[data-qa]');
    const subjects = [];
    let currentSubject = null;

    for (const el of items) {
      const qa = el.getAttribute('data-qa');
      if (qa.startsWith('subject-') && !qa.startsWith('subject-type-')) {
        if (currentSubject) subjects.push(currentSubject);
        const numMatch = qa.match(/subject-(\\d+)/);
        currentSubject = {
          id: qa,
          num: numMatch ? parseInt(numMatch[1]) : 0,
          text: el.innerText.replace(/^\\d+\\n/, '').split('\\n')[0].trim(),
          fullText: el.innerText.trim(),
          type: 'unknown',
          options: [],
          hasInput: false
        };
      } else if (qa.startsWith('option-') && currentSubject) {
        currentSubject.options.push(qa.replace('option-', ''));
        currentSubject.type = 'radio';
      } else if (qa.startsWith('subject-type-') && currentSubject) {
        if (qa.includes('TXTSHORT') || qa.includes('TXTLONG')) {
          currentSubject.hasInput = true;
          if (currentSubject.options.length === 0) currentSubject.type = 'text';
        }
      }
    }
    if (currentSubject) subjects.push(currentSubject);
    return subjects;
  });

  const bodyText = await page.evaluate(() => document.body.innerText);
  return JSON.stringify({ title, subjects, bodyText });
}"""


def recon_survey(pw: BrowserSession, url: str) -> dict:
    """Open URL and extract form structure. Returns parsed structure."""
    pw.open(url)
    time.sleep(3)  # Wait for page to load

    # Adapt JS for the backend
    adapted_js = adapt_js_for_backend(EXTRACT_JS, pw.backend)
    raw = pw.run_code(adapted_js, timeout=30)

    # Parse result
    text = raw.strip()

    # Camoufox returns raw result; Playwright wraps in "### Result"
    if "### Result" in text:
        result_section = re.search(r"### Result\s*\n(.*?)(?=\n###|\Z)", text, re.DOTALL)
        if result_section:
            text = result_section.group(1).strip()

    # Strip quotes if present
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]

    # Parse JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from within text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise RuntimeError(f"Failed to parse form structure: {text[:500]}")


def classify_subjects(subjects: list[dict]) -> dict:
    """Classify subjects into form fields vs quiz questions."""
    company_field = None
    name_field = None
    email_field = None
    consent_field = None
    quiz_questions = []

    for s in subjects:
        text_lower = s["text"].lower()
        if "公司" in text_lower and s["type"] == "radio":
            company_field = s
        elif "姓名" in text_lower and s["type"] == "text":
            name_field = s
        elif "mail" in text_lower.lower() and s["type"] == "text":
            email_field = s
        elif "同意" in s.get("fullText", "") or "個資" in s.get("fullText", ""):
            consent_field = s
        elif s["type"] == "radio" and len(s["options"]) >= 2:
            quiz_questions.append(s)

    return {
        "company": company_field,
        "name": name_field,
        "email": email_field,
        "consent": consent_field,
        "questions": quiz_questions,
    }


def save_survey(
    db: Session, url: str, survey_type: str, structure: dict, classified: dict
) -> Survey:
    """Save or update survey and questions in DB."""
    url_hash = hashlib.md5(url.encode()).hexdigest()

    survey = db.query(Survey).filter(Survey.url_hash == url_hash).first()
    if survey:
        # Update existing
        survey.raw_content = structure.get("bodyText")
        survey.title = structure.get("title")
        company = classified.get("company")
        if company:
            survey.company_options = company.get("options", [])
        # Preserve correct_answer from existing questions before re-insert
        old_qs = db.query(Question).filter(Question.survey_id == survey.id).all()
        preserved_answers = {
            q.subject_id: (q.correct_answer, q.verified) for q in old_qs if q.correct_answer
        }
        db.query(Question).filter(Question.survey_id == survey.id).delete()
    else:
        preserved_answers = {}
        company = classified.get("company")
        survey = Survey(
            url=url,
            url_hash=url_hash,
            title=structure.get("title"),
            type=survey_type,
            raw_content=structure.get("bodyText"),
            company_options=company.get("options", []) if company else [],
        )
        db.add(survey)
        db.flush()

    for q in classified["questions"]:
        correct_answer, verified = preserved_answers.get(q["id"], (None, False))
        db.add(
            Question(
                survey_id=survey.id,
                subject_id=q["id"],
                question_text=q["text"],
                options=q["options"],
                correct_answer=correct_answer,
                verified=verified,
            )
        )

    db.commit()
    db.refresh(survey)
    return survey

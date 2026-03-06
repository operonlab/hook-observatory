"""Phase 1: Recon — extract form structure from SurveyCake URL."""

import hashlib
import json
import re

from sqlalchemy.orm import Session

from .models import Question, Survey
from .pw import PlaywrightSession

# JS to extract full form structure (all DOM access via page.evaluate)
EXTRACT_JS = r"""async (page) => {
  await page.waitForTimeout(3000);

  const data = await page.evaluate(() => {
    const title = document.title.replace(/ » SurveyCake$/, '').trim();

    const items = document.querySelectorAll('[data-qa]');
    const subjects = [];
    let currentSubject = null;

    for (const el of items) {
      const qa = el.getAttribute('data-qa');
      if (qa.startsWith('subject-') && !qa.startsWith('subject-type-')) {
        if (currentSubject) subjects.push(currentSubject);
        const numMatch = qa.match(/subject-(\d+)/);
        currentSubject = {
          id: qa,
          num: numMatch ? parseInt(numMatch[1]) : 0,
          text: el.innerText.replace(/^\d+\n/, '').split('\n')[0].trim(),
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

    const bodyText = document.body.innerText;
    return { title, subjects, bodyText };
  });

  return data;
}"""


def recon_survey(pw: PlaywrightSession, url: str) -> dict:
    """Open URL and extract form structure. Returns parsed structure."""
    pw.open(url)
    raw = pw.run_code(EXTRACT_JS, timeout=30)

    # Playwright CLI returns: ### Result\n{json}\n### Ran Playwright code...
    # Find the JSON object between "### Result" and next "###"
    result_section = re.search(r"### Result\s*\n(.*?)(?=\n###|\Z)", raw, re.DOTALL)
    if not result_section:
        raise RuntimeError(f"Failed to extract form structure from: {raw[:500]}")

    text = result_section.group(1).strip()

    # The CLI may return as JS object representation or JSON
    # Try direct JSON parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from within quotes (CLI wraps strings in quotes)
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
        # Delete old questions and re-insert
        db.query(Question).filter(Question.survey_id == survey.id).delete()
    else:
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
        db.add(
            Question(
                survey_id=survey.id,
                subject_id=q["id"],
                question_text=q["text"],
                options=q["options"],
            )
        )

    db.commit()
    db.refresh(survey)
    return survey

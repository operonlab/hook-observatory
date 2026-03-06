"""Phase 3: Fill — generate and execute Playwright fill scripts."""

import re

from sqlalchemy.orm import Session

from .models import Person, Submission, Survey
from .pw import PlaywrightSession


def _build_fill_script(
    person: Person,
    survey: Survey,
    answers: dict[str, str] | None = None,
) -> str:
    """Generate JavaScript for Playwright CLI run-code to fill the form."""
    company = person.company
    company_options = survey.company_options or []

    # Determine company selection strategy
    if company in company_options:
        company_click = f"await page.click('[data-qa=\"option-{company}\"]');"
        company_fill = ""
    else:
        # Select "其他" and fill text input
        company_click = "await page.click('[data-qa=\"option-其他\"]');"
        company_fill = f"""
    await page.waitForTimeout(500);
    const otherInput = page.locator('[data-qa="subject-1"] input[type="text"], [data-qa="subject-1"] textarea, [data-qa="option-其他"] ~ input, [data-qa="option-其他"] ~ div input').first();
    if (await otherInput.count() > 0) {{
      await otherInput.fill('{_js_escape(company)}');
    }} else {{
      const inputs = page.locator('input[placeholder*="填入"], input[placeholder*="輸入"]');
      const count = await inputs.count();
      for (let i = 0; i < count; i++) {{
        if (await inputs.nth(i).isVisible()) {{
          await inputs.nth(i).fill('{_js_escape(company)}');
          break;
        }}
      }}
    }}"""

    # Build answer clicks for quiz
    answer_clicks = ""
    if answers:
        for subject_id, answer_text in answers.items():
            escaped = _js_escape(answer_text)
            answer_clicks += f"""
    await page.click('[data-qa="option-{escaped}"]');
    await page.waitForTimeout(300);"""

    name_escaped = _js_escape(person.name)
    email_escaped = _js_escape(person.email)

    script = f"""async (page) => {{
    // 1. Select company
    {company_click}
    {company_fill}
    await page.waitForTimeout(300);

    // 2. Fill name (subject-3) + email (subject-4)
    const nameField = page.locator('[data-qa="subject-3"] input, [data-qa="subject-3"] textarea').first();
    if (await nameField.count() > 0) {{
      await nameField.fill('{name_escaped}');
    }}
    await page.waitForTimeout(200);

    const emailField = page.locator('[data-qa="subject-4"] input, [data-qa="subject-4"] textarea').first();
    if (await emailField.count() > 0) {{
      await emailField.fill('{email_escaped}');
    }}
    await page.waitForTimeout(300);

    // 3. Answer quiz questions (if any)
    {answer_clicks}

    // 4. Consent checkbox
    const consent = page.locator('[data-qa*="本人已詳閱"], [data-qa*="同意"]').first();
    if (await consent.count() > 0) {{
      await consent.click();
      await page.waitForTimeout(200);
    }}

    // 5. Random delay before submit (simulate human)
    const delay = Math.floor(Math.random() * 5000) + 1000;
    await page.waitForTimeout(delay);

    // 6. Submit
    await page.locator('text=送出').first().click();
    await page.waitForTimeout(1000);

    // 7. Handle confirmation dialog
    const confirmBtns = ['text=確定送出', 'text=確定', 'text=確認', 'text=OK'];
    for (const sel of confirmBtns) {{
      const btn = page.locator(sel).first();
      if (await btn.count() > 0 && await btn.isVisible()) {{
        await btn.click();
        break;
      }}
    }}
    await page.waitForTimeout(3000);

    // 8. Extract score (quiz only)
    const bodyText = await page.evaluate(() => document.body.innerText);
    return bodyText;
  }}"""
    return script


def _js_escape(s: str) -> str:
    """Escape string for JavaScript single-quoted string."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")


def _extract_score(page_text: str) -> int | None:
    """Extract score from post-submission page text."""
    patterns = [
        r"成績[為是]?\s*[:：]?\s*(\d+)",
        r"分數[為是]?\s*[:：]?\s*(\d+)",
        r"得到\s*(\d+)\s*分",
        r"(\d+)\s*分",
        r"Score\s*[:：]?\s*(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, page_text)
        if m:
            score = int(m.group(1))
            if 0 <= score <= 100:
                return score
    return None


def fill_form(
    pw: PlaywrightSession,
    db: Session,
    survey: Survey,
    person: Person,
    answers: dict[str, str] | None = None,
) -> Submission:
    """Fill the form for one person. Returns the Submission record."""
    # Check if already submitted
    existing = (
        db.query(Submission)
        .filter(Submission.survey_id == survey.id, Submission.person_id == person.id)
        .first()
    )
    if existing and existing.status == "success":
        return existing

    script = _build_fill_script(person, survey, answers)

    try:
        pw.open(survey.url)
        raw_output = pw.run_code(script, timeout=90)

        # Parse result text from Playwright CLI output
        result_text = ""
        result_match = re.search(r"### Result\s*\n(.*?)(?=\n###|\Z)", raw_output, re.DOTALL)
        if result_match:
            result_text = result_match.group(1).strip().strip('"')
        else:
            result_text = raw_output

        score = _extract_score(result_text) if survey.type == "quiz" else None

        submission = existing or Submission(
            survey_id=survey.id,
            person_id=person.id,
        )
        submission.status = "success"
        submission.score = score
        submission.answers_snapshot = answers
        submission.error_message = None

        if not existing:
            db.add(submission)
        db.commit()
        db.refresh(submission)
        return submission

    except Exception as e:
        submission = existing or Submission(
            survey_id=survey.id,
            person_id=person.id,
        )
        submission.status = "failed"
        submission.error_message = str(e)[:500]

        if not existing:
            db.add(submission)
        db.commit()
        db.refresh(submission)
        return submission

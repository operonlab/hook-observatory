"""Phase 3: Fill — generate and execute Playwright fill scripts."""

import logging
import re

from sqlalchemy.orm import Session

from .models import Person, Submission, Survey
from .pw import BrowserSession, adapt_js_for_backend

log = logging.getLogger("auto_survey")


def _build_fill_script(
    person: Person,
    survey: Survey,
    answers: dict[str, str] | None = None,
) -> str:
    """Generate JavaScript in Playwright async (page) => format.

    Will be auto-converted to camoufox format by adapt_js_for_backend().
    """
    company = person.company
    company_options = survey.company_options or []

    # Determine company selection strategy
    if company in company_options:
        company_click = f"await page.locator('[data-qa=\"option-{company}\"]').first().click();"
        company_fill = ""
    else:
        # Select "其他" and fill text input (input appears in subject-2 after clicking)
        company_click = "await page.locator('[data-qa=\"option-其他\"]').first().click();"
        company_fill = f"""
    await page.waitForTimeout(500);
    const otherInput = page.locator('[data-qa="subject-2"] input, [data-qa="subject-2"] textarea, [data-qa="subject-1"] input').first();
    if (await otherInput.count() > 0) {{
      await otherInput.fill('{_js_escape(company)}');
    }}"""

    # Build answer clicks for quiz
    answer_clicks = ""
    if answers:
        for subject_id, answer_text in answers.items():
            escaped = _js_escape(answer_text)
            answer_clicks += f"""
    await page.evaluate(() => {{
      const subj = document.querySelector('[data-qa="{subject_id}"]');
      if (!subj) return;
      const opts = subj.querySelectorAll('[data-qa^="option-"]');
      let clicked = false;
      for (const opt of opts) {{
        const qa = opt.getAttribute('data-qa');
        if (qa === 'option-{escaped}') {{
          opt.click();
          clicked = true;
          break;
        }}
      }}
      if (!clicked) {{
        const needle = '{escaped}'.replace(/\\s+/g, '');
        for (const opt of opts) {{
          const qa = (opt.getAttribute('data-qa')) || '';
          const optText = qa.replace('option-', '').replace(/\\s+/g, '');
          if (optText && (optText.includes(needle) || needle.includes(optText))) {{
            opt.click();
            clicked = true;
            break;
          }}
        }}
      }}
    }});
    await page.waitForTimeout(300);"""

    name_escaped = _js_escape(person.name)
    email_escaped = _js_escape(person.email)

    script = f"""async (page) => {{
    // 0. Wait for React render
    await page.waitForTimeout(3000);

    // 1. Select company
    {company_click}
    {company_fill}
    await page.waitForTimeout(200);

    // 2. Fill name (subject-3) + email (subject-4)
    const nameField = page.locator('[data-qa="subject-3"] input, [data-qa="subject-3"] textarea').first();
    if (await nameField.count() > 0) {{
      await nameField.fill('{name_escaped}');
    }}
    await page.waitForTimeout(100);

    const emailField = page.locator('[data-qa="subject-4"] input, [data-qa="subject-4"] textarea').first();
    if (await emailField.count() > 0) {{
      await emailField.fill('{email_escaped}');
    }}
    await page.waitForTimeout(100);

    // 3. Answer quiz questions (if any)
    {answer_clicks}

    // 4. Consent checkbox
    const consent = page.locator('[data-qa*="本人已詳閱"], [data-qa*="同意"]').first();
    if (await consent.count() > 0) {{
      await consent.click();
      await page.waitForTimeout(200);
    }}

    // 5. Random delay before submit (simulate human)
    const delay = Math.floor(Math.random() * 1500) + 500;
    await page.waitForTimeout(delay);

    // 6. Submit
    await page.locator('text=送出').first().click();
    await page.waitForTimeout(500);

    // 7. Handle confirmation dialog
    const preSubmitUrl = page.url();
    const confirmBtns = ['text=確定送出', 'text=確定', 'text=確認', 'text=OK'];
    for (const sel of confirmBtns) {{
      const btn = page.locator(sel).first();
      if (await btn.count() > 0 && await btn.isVisible()) {{
        await btn.click();
        break;
      }}
    }}

    // 8. Wait for redirect to result page (detect URL change)
    try {{
      await page.waitForFunction(
        (oldUrl) => window.location.href !== oldUrl,
        preSubmitUrl,
        {{ timeout: 30000 }}
      );
    }} catch (e) {{}}

    // 9. Wait for result page to fully load
    try {{
      await page.waitForLoadState('networkidle', {{ timeout: 15000 }});
    }} catch (e) {{}}
    await page.waitForTimeout(3000);

    // 10. Wait for score text to appear (quiz result pages)
    try {{
      await page.waitForFunction(
        () => /成績|分數|Score|感謝|你的/.test(document.body.innerText),
        null,
        {{ timeout: 15000 }}
      );
    }} catch (e) {{}}
    // Extra wait for score rendering after text appears
    await page.waitForTimeout(2000);

    // 11. Extract page text
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
    pw: BrowserSession,
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
    # Adapt JS for the backend
    adapted_js = adapt_js_for_backend(script, pw.backend)

    try:
        pw.open(survey.url)
        raw_output = pw.run_code(adapted_js, timeout=90)

        # Parse result text
        result_text = raw_output.strip()

        # Playwright wraps result in "### Result"
        if "### Result" in result_text:
            result_match = re.search(r"### Result\s*\n(.*?)(?=\n###|\Z)", result_text, re.DOTALL)
            if result_match:
                result_text = result_match.group(1).strip().strip('"')

        score = _extract_score(result_text) if survey.type == "quiz" else None

        # Detect if we're still on the form page (submission failed silently)
        form_still_visible = any(
            marker in result_text for marker in ("此題必填", "送出", "請選擇公司名稱")
        )

        # Debug: log result text for score extraction diagnosis
        if survey.type == "quiz":
            preview = result_text[:300].replace("\n", " | ")
            log.warning("[fill] %s result_text: %s", person.name, preview)
            if form_still_visible:
                log.warning("[fill] %s form still visible — submission likely failed", person.name)
            elif score is None:
                log.warning("[fill] %s score=None — regex matched nothing", person.name)

        submission = existing or Submission(
            survey_id=survey.id,
            person_id=person.id,
        )

        if form_still_visible and survey.type == "quiz":
            submission.status = "failed"
            submission.error_message = "Form submission failed — still on form page"
            submission.score = None
        else:
            submission.status = "success"
            submission.error_message = None
            submission.score = score
        submission.answers_snapshot = answers

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

        try:
            if not existing:
                db.add(submission)
            db.commit()
            db.refresh(submission)
        except Exception:
            log.critical(
                "Failed to persist error submission for survey=%s person=%s: %s",
                survey.id,
                person.id,
                e,
                exc_info=True,
            )
            db.rollback()
            return submission
        return submission

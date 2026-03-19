"""CLI entry point for auto-survey station."""

import csv
from datetime import date, datetime, timezone

import click

from .config import settings
from .db import engine, get_session, init_db
from .models import Base, DailyRun, Person, Submission, Survey
from .notify import send_bark


@click.group()
def main():
    """Auto Survey — automated SurveyCake form filler."""
    pass


@main.command()
@click.argument("url")
@click.option("--dry-run", is_flag=True, help="Recon + analyze only, don't fill")
def attend(url: str, dry_run: bool):
    """Fill attendance form for all active people."""
    _ensure_db()
    from .orchestrator import run_attendance

    run_attendance(url, dry_run=dry_run)


@main.command()
@click.argument("url")
@click.option("--dry-run", is_flag=True, help="Recon + analyze only, don't fill")
def quiz(url: str, dry_run: bool):
    """Fill quiz form for all active people."""
    _ensure_db()
    from .orchestrator import run_quiz

    run_quiz(url, dry_run=dry_run)


@main.command()
@click.option("--attend-url", "attend_url", default=None, help="Attendance form URL")
@click.option("--quiz-url", "quiz_url", default=None, help="Quiz form URL")
@click.option("--dry-run", is_flag=True, help="Recon + analyze only, don't fill")
def run(attend_url: str | None, quiz_url: str | None, dry_run: bool):
    """Run attendance + quiz in one shot, tracking daily state."""
    if not attend_url and not quiz_url:
        click.echo("Error: provide at least one of --attend-url or --quiz-url")
        raise SystemExit(1)

    _ensure_db()
    db = get_session()
    from .orchestrator import run_attendance, run_quiz

    try:
        # Track daily run state
        today = date.today()
        daily = db.query(DailyRun).filter(DailyRun.run_date == today).first()
        if not daily:
            daily = DailyRun(run_date=today)
            db.add(daily)

        daily.attend_url = attend_url
        daily.quiz_url = quiz_url
        daily.status = "running"
        daily.updated_at = datetime.now(timezone.utc)
        db.commit()

        results = []

        if attend_url:
            click.echo(f"[auto-survey] === Attendance: {attend_url} ===")
            try:
                run_attendance(attend_url, dry_run=dry_run)
                results.append("attendance: OK")
            except Exception as e:
                results.append(f"attendance: FAILED ({e})")

        if quiz_url:
            click.echo(f"[auto-survey] === Quiz: {quiz_url} ===")
            try:
                run_quiz(quiz_url, dry_run=dry_run)
                results.append("quiz: OK")
            except Exception as e:
                results.append(f"quiz: FAILED ({e})")

        summary = " | ".join(results)
        has_fail = any("FAILED" in r for r in results)
        daily.status = "failed" if has_fail else "completed"
        daily.result_summary = summary
        daily.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Bark notification
        status_text = "FAIL" if has_fail else "OK"
        send_bark("Auto Survey", f"{status_text} {summary}")
        click.echo(f"[auto-survey] Done: {summary}")

    finally:
        db.close()


@main.command("notify-check")
def notify_check():
    """Check if today needs a reminder. Send Bark if no URLs provided yet."""
    _ensure_db()
    db = get_session()
    try:
        today = date.today()
        daily = db.query(DailyRun).filter(DailyRun.run_date == today).first()

        if daily and daily.status in ("running", "completed", "scheduled"):
            click.echo(f"[auto-survey] Today already {daily.status}, skipping notification.")
            return

        # No run yet or still pending — send reminder
        send_bark(
            "Auto Survey Reminder",
            "今天有課程，請提供 SurveyCake URL",
        )
        click.echo("[auto-survey] Reminder sent via Bark.")

        # Create pending record if not exists
        if not daily:
            daily = DailyRun(run_date=today, status="pending")
            db.add(daily)
            db.commit()
    finally:
        db.close()


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", default=None, type=int, help="Bind port")
def serve(host: str, port: int | None):
    """Start web UI server."""
    _ensure_db()
    import uvicorn

    from .web import app

    actual_port = port or settings.web_port
    click.echo(f"[auto-survey] Starting web UI on {host}:{actual_port}")
    uvicorn.run(app, host=host, port=actual_port, log_level="info")


@main.group()
def people():
    """Manage people list."""
    pass


@people.command("import")
@click.argument("csv_path", type=click.Path(exists=True))
def import_people(csv_path: str):
    """Import people from CSV (columns: name, email, company)."""
    _ensure_db()
    db = get_session()
    count = 0
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip()
                email = row.get("email", "").strip()
                company = row.get("company", "").strip()
                if not name or not email or not company:
                    click.echo(f"Skipping incomplete row: {row}")
                    continue

                existing = db.query(Person).filter(Person.email == email).first()
                if existing:
                    existing.name = name
                    existing.company = company
                    existing.active = True
                    click.echo(f"  Updated: {name} <{email}>")
                else:
                    db.add(Person(name=name, email=email, company=company))
                    click.echo(f"  Added: {name} <{email}>")
                count += 1
        db.commit()
        click.echo(f"Imported {count} people.")
    finally:
        db.close()


@people.command("list")
def list_people():
    """List all people."""
    _ensure_db()
    db = get_session()
    try:
        people_list = db.query(Person).order_by(Person.name).all()
        if not people_list:
            click.echo("No people found. Import with: auto-survey people import <csv>")
            return
        click.echo(f"{'Name':<20} {'Email':<35} {'Company':<15} {'Active'}")
        click.echo("-" * 75)
        for p in people_list:
            active = "Y" if p.active else "N"
            click.echo(f"{p.name:<20} {p.email:<35} {p.company:<15} {active}")
    finally:
        db.close()


@people.command("deactivate")
@click.argument("email")
def deactivate_person(email: str):
    """Deactivate a person by email."""
    _ensure_db()
    db = get_session()
    try:
        person = db.query(Person).filter(Person.email == email).first()
        if not person:
            click.echo(f"Person not found: {email}")
            return
        person.active = False
        db.commit()
        click.echo(f"Deactivated: {person.name}")
    finally:
        db.close()


@main.command()
@click.option("--url", help="Filter by survey URL")
def history(url: str | None):
    """Show submission history."""
    _ensure_db()
    db = get_session()
    try:
        query = db.query(Submission).join(Survey).join(Person)
        if url:
            query = query.filter(Survey.url == url)
        subs = query.order_by(Submission.submitted_at.desc()).limit(50).all()

        if not subs:
            click.echo("No submissions found.")
            return

        click.echo(f"{'Date':<20} {'Name':<15} {'Survey':<30} {'Status':<10} {'Score'}")
        click.echo("-" * 85)
        for s in subs:
            dt = s.submitted_at.strftime("%Y-%m-%d %H:%M") if s.submitted_at else "?"
            name = s.person.name if s.person else "?"
            title = (s.survey.title or s.survey.url)[:28] if s.survey else "?"
            score = str(s.score) if s.score is not None else "-"
            click.echo(f"{dt:<20} {name:<15} {title:<30} {s.status:<10} {score}")
    finally:
        db.close()


@main.command("line-read")
@click.option("--group", default=None, help="LINE community name (default: from config)")
@click.option("--trigger/--no-trigger", default=False, help="Auto-trigger pipeline if URLs found")
@click.option("--dry-run", is_flag=True, help="Don't actually fill forms (only with --trigger)")
def line_read(group: str | None, trigger: bool, dry_run: bool):
    """Read LINE community chat and extract SurveyCake URLs."""
    from .line_reader import extract_survey_urls, read_line_community

    community = group or settings.line_community_name
    click.echo(f"[auto-survey] Reading LINE community: {community}")

    text = read_line_community(community)
    if not text:
        click.echo("[auto-survey] Failed to read LINE (not running or no content)")
        raise SystemExit(1)

    urls = extract_survey_urls(text)
    attend = urls.get("attend_url")
    quiz = urls.get("quiz_url")

    if not attend and not quiz:
        click.echo("[auto-survey] No SurveyCake URLs found in today's messages")
        raise SystemExit(1)

    if attend:
        click.echo(f"  簽到: {attend}")
    if quiz:
        click.echo(f"  測驗: {quiz}")

    if trigger:
        click.echo("[auto-survey] Triggering pipeline...")
        _ensure_db()
        ctx = click.get_current_context()
        ctx.invoke(run, attend_url=attend, quiz_url=quiz, dry_run=dry_run)
    else:
        click.echo("[auto-survey] Dry mode — use --trigger to auto-fill")


@main.command()
def init():
    """Initialize database schema."""
    _ensure_db()
    click.echo("Database initialized.")


def _ensure_db():
    """Create schema and tables if not exist."""
    init_db()
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    main()

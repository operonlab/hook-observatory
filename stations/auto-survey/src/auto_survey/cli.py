"""CLI entry point for auto-survey station."""

import csv

import click

from .db import get_session, init_db
from .models import Base, Person, Submission, Survey
from .db import engine


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
            date = s.submitted_at.strftime("%Y-%m-%d %H:%M") if s.submitted_at else "?"
            name = s.person.name if s.person else "?"
            title = (s.survey.title or s.survey.url)[:28] if s.survey else "?"
            score = str(s.score) if s.score is not None else "-"
            click.echo(f"{date:<20} {name:<15} {title:<30} {s.status:<10} {score}")
    finally:
        db.close()


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

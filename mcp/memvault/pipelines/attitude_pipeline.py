#!/usr/bin/env python3
"""attitude_pipeline.py — Memvault V2 Knowledge Graph: Attitude Evolution Pipeline

Reads user correction records (from corrections JSONL or stdin),
calls Core API /kg/attitudes/evolve for each correction,
and reports the attitude drift results.

Input format (one JSON object per line, or a JSON array):
  {"fact": "...", "category": "...", "session_id": "...", "timestamp": "..."}

Usage:
    # From corrections JSONL file
    python3 attitude_pipeline.py --input ~/Claude/memvault/corrections/2026-02/2026-02-26.jsonl

    # From stdin (pipe)
    cat corrections.jsonl | python3 attitude_pipeline.py

    # Process all corrections files in a directory
    python3 attitude_pipeline.py --input ~/Claude/memvault/corrections/ --all

    # Dry run — print what would be sent without calling Core API
    python3 attitude_pipeline.py --input corrections.jsonl --dry-run
"""

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
CORE_API = os.environ.get("CORE_API_URL", "http://localhost:8801")
EVOLVE_URL_TEMPLATE = "{base}/api/memvault/kg/attitudes/evolve"
DEFAULT_CORRECTIONS_DIR = Path.home() / "Claude" / "memvault" / "corrections"


# ── HTTP helper ────────────────────────────────────────────────────────────────
def http_post(url: str, body: dict, params: dict | None = None) -> tuple[int, dict]:
    """Returns (http_status_code, response_body)."""
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:300]
        try:
            error_body = json.loads(body_txt)
        except json.JSONDecodeError:
            error_body = {"detail": body_txt}
        return e.code, error_body
    except urllib.error.URLError as e:
        return 0, {"error": str(e)}


# ── Correction loaders ─────────────────────────────────────────────────────────
def load_from_jsonl(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, list):
                    records.extend(obj)
                elif isinstance(obj, dict):
                    records.append(obj)
            except json.JSONDecodeError as e:
                print(f"[warn] {path.name}:{lineno} invalid JSON — {e}", file=sys.stderr)
    return records


def load_from_stdin() -> list[dict]:
    raw = sys.stdin.read().strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass
    # Try line-by-line JSONL
    records = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"[warn] stdin:{lineno} invalid JSON — {e}", file=sys.stderr)
    return records


def collect_all_corrections(base_dir: Path) -> list[dict]:
    """Walk all JSONL files under corrections directory."""
    all_records = []
    jsonl_files = sorted(base_dir.rglob("**/*.jsonl"))
    if not jsonl_files:
        print(f"[warn] No JSONL files found under {base_dir}", file=sys.stderr)
        return all_records
    for fpath in jsonl_files:
        records = load_from_jsonl(fpath)
        all_records.extend(records)
        print(f"  Loaded {len(records)} records from {fpath.name}")
    return all_records


# ── Evolve one correction ──────────────────────────────────────────────────────
def evolve_correction(correction: dict, space_id: str, dry_run: bool) -> dict:
    """
    Call POST /api/memvault/kg/attitudes/evolve with one correction.

    Expected payload:
      {
        "fact": "...",
        "category": "...",
        "session_id": "...",
        "timestamp": "...",
        "space_id": "..."
      }

    Returns result dict with keys: success, status, response, correction.
    """
    url = EVOLVE_URL_TEMPLATE.format(base=CORE_API)
    body = {
        "fact": correction.get("fact", ""),
        "category": correction.get("category", ""),
        "session_id": correction.get("session_id", ""),
        "timestamp": correction.get("timestamp", datetime.now().isoformat(timespec="seconds")),
        "space_id": space_id,
    }

    if not body["fact"]:
        return {"success": False, "status": 0, "error": "empty fact", "correction": correction}

    if dry_run:
        return {
            "success": True, "status": 0, "dry_run": True,
            "correction": correction, "payload": body,
        }

    status, resp = http_post(url, body, params={"space_id": space_id})
    return {
        "success": status in (200, 201),
        "status": status,
        "response": resp,
        "correction": correction,
    }


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Memvault attitude pipeline — evolve attitudes from corrections"
    )
    parser.add_argument(
        "--input", "-i",
        help="Path to corrections JSONL file or directory. Reads from stdin if omitted.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="When --input is a directory, process all JSONL files recursively.",
    )
    parser.add_argument(
        "--space-id", default=os.environ.get("MEMVAULT_SPACE_ID", "default"),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be sent without calling Core API.",
    )
    parser.add_argument(
        "--stop-on-error", action="store_true",
        help="Stop processing if Core API returns an error.",
    )
    parser.add_argument(
        "--archive", action="store_true",
        help="Move processed JSONL files to corrections/processed/ directory.",
    )
    parser.add_argument(
        "--notify", action="store_true",
        help="Output JSON summary of high-drift corrections (drift_score > 0.3) to stdout.",
    )
    args = parser.parse_args()

    print("Memvault — attitude_pipeline.py")
    print(f"Core API : {CORE_API}")
    print(f"Space ID : {args.space_id}")
    if args.dry_run:
        print("Mode     : DRY RUN")
    print()

    # Load corrections
    corrections: list[dict] = []

    if not args.input:
        # Read from stdin
        print("[Load] Reading corrections from stdin ...")
        corrections = load_from_stdin()
    else:
        input_path = Path(args.input).expanduser()
        if input_path.is_dir():
            if args.all:
                print(f"[Load] Scanning all JSONL under {input_path} ...")
                corrections = collect_all_corrections(input_path)
            else:
                print(
                    f"[error] {input_path} is a directory. Use --all to process recursively.",
                    file=sys.stderr,
                )
                sys.exit(1)
        elif input_path.is_file():
            print(f"[Load] Loading {input_path} ...")
            corrections = load_from_jsonl(input_path)
        else:
            print(f"[error] Input path not found: {input_path}", file=sys.stderr)
            sys.exit(1)

    if not corrections:
        print("[skip] No corrections found.")
        sys.exit(0)

    print(f"[Process] {len(corrections)} correction(s) to evolve\n")

    # Process
    results = {"ok": 0, "fail": 0, "skip": 0}
    failed: list[dict] = []
    high_drift: list[dict] = []

    for i, correction in enumerate(corrections):
        fact_preview = correction.get("fact", "")[:60]
        category = correction.get("category", "?")

        print(f"  [{i+1}/{len(corrections)}] [{category}] {fact_preview}...", end=" ", flush=True)

        result = evolve_correction(correction, args.space_id, args.dry_run)

        if result.get("dry_run"):
            print(f"DRY_RUN → {json.dumps(result['payload'], ensure_ascii=False)[:80]}")
            results["ok"] += 1
        elif result["success"]:
            drift = ""
            drift_score = 0.0
            if isinstance(result.get("response"), dict):
                resp = result["response"]
                drift_val = resp.get("drift_score", resp.get("drift", ""))
                if drift_val:
                    drift = f" (drift={drift_val})"
                    try:
                        drift_score = float(drift_val)
                    except (TypeError, ValueError):
                        pass
            if drift_score > 0.3:
                high_drift.append({
                    "fact": correction.get("fact", ""),
                    "category": correction.get("category", ""),
                    "drift_score": drift_score,
                })
            print(f"OK{drift}")
            results["ok"] += 1
        else:
            err_detail = ""
            if isinstance(result.get("response"), dict):
                err_detail = result["response"].get("detail", str(result.get("response", "")))[:80]
            print(f"FAIL HTTP {result['status']}: {err_detail}")
            results["fail"] += 1
            failed.append(result)
            if args.stop_on_error:
                print("[stop] Stopping on first error (--stop-on-error).", file=sys.stderr)
                break

    # Summary
    print(f"\n{'='*60}")
    print("  Memvault — Attitude Pipeline Report")
    print(f"{'='*60}")
    print(f"  Total corrections : {len(corrections)}")
    print(f"  Evolved (OK)      : {results['ok']}")
    print(f"  Failed            : {results['fail']}")
    print(f"{'='*60}")

    if failed:
        print(f"\n[warn] {len(failed)} failed correction(s):")
        for r in failed[:5]:
            fact = r["correction"].get("fact", "")[:80]
            print(f"  HTTP {r['status']} — {fact}")
        if len(failed) > 5:
            print(f"  ... and {len(failed) - 5} more")

    # --archive: Move processed files to processed/ directory
    if args.archive and args.input:
        input_path = Path(args.input).expanduser()
        if input_path.is_dir() and args.all:
            processed_dir = input_path / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            jsonl_files = sorted(input_path.rglob("**/*.jsonl"))
            moved = 0
            for fpath in jsonl_files:
                if "processed" in fpath.parts:
                    continue
                dest = processed_dir / fpath.name
                shutil.move(str(fpath), str(dest))
                moved += 1
            print(f"\n[archive] Moved {moved} file(s) to {processed_dir}")
        elif input_path.is_file():
            processed_dir = input_path.parent / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            dest = processed_dir / input_path.name
            shutil.move(str(input_path), str(dest))
            print(f"\n[archive] Moved {input_path.name} to {processed_dir}")

    # --notify: Output high-drift summary as JSON
    if args.notify and not args.dry_run:
        notify_summary = {
            "total": len(corrections),
            "ok": results["ok"],
            "fail": results["fail"],
            "high_drift_count": len(high_drift),
            "high_drift": high_drift,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        notify_path = (
            Path(args.input).expanduser().parent / "notify_summary.json"
            if args.input
            else Path("/tmp/attitude_notify.json")
        )
        with open(notify_path, "w", encoding="utf-8") as f:
            json.dump(notify_summary, f, ensure_ascii=False, indent=2)
        print(f"\n[notify] Summary written to {notify_path}")

    if failed:
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()

"""Claude Code engine — uses `claude -p` CLI with image input for OCR.

Best for: handwritten text, complex layouts, tables, charts, mixed media.
Requires: claude CLI installed and authenticated.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from shutil import which

from . import register

_SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


@register("claude")
class ClaudeOCREngine:
    """Claude Code CLI for high-accuracy OCR on complex images."""

    name = "claude"

    def extract(self, file_path: str, languages: list[str] | None = None) -> dict:
        if not which("claude"):
            return {"error": "claude CLI not found in PATH", "engine": "claude"}

        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}", "engine": "claude"}

        ext = path.suffix.lower()

        if ext == ".pdf":
            return self._extract_pdf(path, languages)

        if ext not in _SUPPORTED_EXT:
            return {
                "error": f"Unsupported format: {ext}. Supported: {sorted(_SUPPORTED_EXT)}",
                "engine": "claude",
            }

        return self._run_claude(str(path), languages)

    def _extract_pdf(self, path: Path, languages: list[str] | None) -> dict:
        """Convert PDF to PNG via qlmanage, then OCR."""
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                subprocess.run(
                    ["qlmanage", "-t", "-s", "2000", "-o", tmpdir, str(path)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                png_files = list(Path(tmpdir).glob("*.png"))
                if not png_files:
                    return {
                        "error": "Failed to convert PDF to image",
                        "engine": "claude",
                    }

                result = self._run_claude(str(png_files[0]), languages)
                if "blocks" in result:
                    for b in result["blocks"]:
                        b["page"] = 1
                return result

        except Exception as e:
            return {"error": f"PDF processing failed: {e}", "engine": "claude"}

    def _run_claude(self, image_path: str, languages: list[str] | None) -> dict:
        """Call claude CLI to read and OCR an image."""
        import os

        lang_hint = ", ".join(languages) if languages else "auto-detect"
        prompt = (
            f"Read the image file at {image_path} using the Read tool, then extract ALL text. "
            f"Languages: {lang_hint}.\n"
            "Return ONLY a JSON object (no markdown fences, no explanation) with:\n"
            '- "text": the full extracted text\n'
            '- "blocks": array of {{"text": str, "type": "paragraph"|"heading"|"list"|"table"|"handwritten"}}\n'
            "Be thorough — include every piece of visible text. Preserve formatting."
        )

        # Unset CLAUDECODE to avoid nested execution protection
        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        try:
            result = subprocess.run(
                [
                    "claude",
                    "-p",
                    prompt,
                    "--model",
                    "claude-haiku-4-5-20251001",
                    "--output-format",
                    "text",
                    "--max-turns",
                    "2",
                    "--allowedTools",
                    "Read",
                    "--permission-mode",
                    "bypassPermissions",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except FileNotFoundError:
            return {"error": "claude CLI not found", "engine": "claude"}
        except subprocess.TimeoutExpired:
            return {"error": "claude CLI timed out (120s)", "engine": "claude"}

        if result.returncode != 0:
            stderr = result.stderr.strip()[:300]
            return {
                "error": f"claude CLI failed (rc={result.returncode}): {stderr}",
                "engine": "claude",
            }

        raw = result.stdout.strip()
        parsed = self._parse_response(raw)

        return {
            "text": parsed.get("text", raw),
            "blocks": parsed.get("blocks", []),
            "languages": languages or ["auto"],
            "engine": "claude",
            "model": "claude-haiku-4-5-20251001",
        }

    @staticmethod
    def _parse_response(text: str) -> dict:
        """Try to parse JSON from Claude's response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        if "```" in text:
            for block in text.split("```"):
                block = block.strip()
                if block.startswith("json"):
                    block = block[4:].strip()
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    continue

        return {"text": text, "blocks": []}

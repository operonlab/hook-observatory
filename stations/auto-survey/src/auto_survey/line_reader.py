"""LINE Desktop reader — AppleScript automation to extract SurveyCake URLs from community chat."""

import re
import subprocess

from .config import settings

SURVEYCAKE_RE = re.compile(r"https?://www\.surveycake\.com/s/\w+")

# AppleScript: navigate LINE → search community → copy messages
_APPLESCRIPT_TEMPLATE = """\
tell application "LINE" to activate
delay 1

tell application "System Events"
    tell process "LINE"
        -- Focus search field
        set searchField to text field 1 of splitter group 1 of window 1
        set focused of searchField to true
        delay 0.3

        -- Clear and type community name
        key code 0 using {{command down}}
        key code 51
        delay 0.2
        set value of searchField to "{community_name}"
        delay 1.0

        -- Click first search result (row 1 = header in some versions, try row 1 first)
        set chatList to list 1 of splitter group 1 of window 1
        click row 1 of chatList
        delay 0.8

        -- Select all messages and copy
        key code 0 using {{command down}}
        delay 0.2
        key code 8 using {{command down}}
        delay 0.3

        -- Press Escape to dismiss search
        key code 53
        delay 0.2
    end tell
end tell
"""


def read_line_community(community_name: str | None = None) -> str | None:
    """Open LINE Desktop, search for a community, and return clipboard text.

    Returns None if LINE is not running or any step fails.
    """
    name = community_name or settings.line_community_name

    # 1. Check LINE is running
    check = subprocess.run(["pgrep", "-x", "LINE"], capture_output=True)
    if check.returncode != 0:
        return None

    # 2. Run AppleScript
    script = _APPLESCRIPT_TEMPLATE.format(community_name=name)
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    # 3. Read clipboard
    try:
        clip = subprocess.check_output(["pbpaste"], text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None

    return clip if clip.strip() else None


def extract_survey_urls(text: str) -> dict[str, str | None]:
    """Extract SurveyCake URLs from LINE message text.

    Looks for a block containing '3355' with '簽到連結' and '測驗連結' labels.
    Returns {'attend_url': ..., 'quiz_url': ...}.
    """
    result: dict[str, str | None] = {"attend_url": None, "quiz_url": None}

    if "3355" not in text:
        return result

    urls = SURVEYCAKE_RE.findall(text)
    if not urls:
        return result

    # Strategy: match URLs by proximity to keywords
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "簽到連結" in line or "簽到" in line:
            found = SURVEYCAKE_RE.search(line)
            if found:
                result["attend_url"] = found.group()
            # Also check next line if URL not on same line
            elif i + 1 < len(lines):
                found = SURVEYCAKE_RE.search(lines[i + 1])
                if found:
                    result["attend_url"] = found.group()

        if "測驗連結" in line or "測驗" in line:
            found = SURVEYCAKE_RE.search(line)
            if found:
                result["quiz_url"] = found.group()
            elif i + 1 < len(lines):
                found = SURVEYCAKE_RE.search(lines[i + 1])
                if found:
                    result["quiz_url"] = found.group()

    # Fallback: if keywords didn't match but we have URLs in 3355 context,
    # assign first URL as attend, second as quiz
    if not result["attend_url"] and not result["quiz_url"] and urls:
        result["attend_url"] = urls[0]
        if len(urls) >= 2:
            result["quiz_url"] = urls[1]

    return result

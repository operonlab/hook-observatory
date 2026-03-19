"""LINE Desktop reader — AppleScript + cliclick automation to extract SurveyCake URLs.

Cannibalized from kaosensei/line-desktop-skill:
- AppleScript Accessibility navigation for search + enter chat
- cliclick for precise message area focusing
- Clipboard bridge for CJK text
"""

import re
import shutil
import subprocess
import time

from .config import settings

SURVEYCAKE_RE = re.compile(r"https?://www\.surveycake\.com/s/\w+")

# Step 1: Activate LINE, ensure window open, search community, click result
_SCRIPT_SEARCH = """\
tell application "LINE" to activate
delay 0.8

tell application "System Events"
    tell process "LINE"
        -- Ensure window is open
        if (count of windows) = 0 then
            click menu item "聊天" of menu "顯示" of menu bar 1
            delay 1.5
        end if

        -- Focus search field, clear, paste community name
        set searchField to text field 1 of splitter group 1 of window 1
        set focused of searchField to true
        delay 0.3
        key code 0 using {{command down}}
        key code 51
        delay 0.2
        set value of searchField to "{community_name}"
        delay 0.8

        -- Click first real result (row 2; row 1 is category header)
        set chatList to list 1 of splitter group 1 of window 1
        click row 2 of chatList
        delay 0.5
    end tell
end tell
"""

# Step 2: Get message area center coordinates for cliclick
_SCRIPT_GET_COORDS = """\
tell application "System Events"
    tell process "LINE"
        set msgList to list 1 of splitter group 1 of splitter group 1 of window 1
        set pos to position of msgList
        set sz to size of msgList
        set cx to (round ((item 1 of pos) + (item 1 of sz) / 2))
        set cy to (round ((item 2 of pos) + (item 2 of sz) / 2))
        return (cx as text) & "," & (cy as text)
    end tell
end tell
"""

# Step 3: Select all + copy (after cliclick focuses message area)
_SCRIPT_COPY = """\
tell application "System Events"
    tell process "LINE"
        key code 0 using {command down}
        delay 0.3
        key code 8 using {command down}
        delay 0.3
    end tell
end tell
"""

# Step 4: Escape back to chat list
_SCRIPT_ESCAPE = """\
tell application "System Events"
    tell process "LINE"
        key code 53
        delay 0.2
        key code 53
        delay 0.2
    end tell
end tell
"""


def _run_osascript(script: str, timeout: int = 10) -> str | None:
    """Run an AppleScript and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def read_line_community(community_name: str | None = None) -> str | None:
    """Open LINE Desktop, search for a community, and return chat text via clipboard.

    Flow (adapted from kaosensei/line-desktop-skill):
    1. Activate LINE → ensure window → search → click result
    2. Get message area coordinates → cliclick to focus
    3. Cmd+A → Cmd+C → read clipboard
    4. Escape to restore state

    Returns None if LINE is not running, cliclick missing, or any step fails.
    """
    name = community_name or settings.line_community_name

    # Pre-checks
    if subprocess.run(["pgrep", "-x", "LINE"], capture_output=True).returncode != 0:
        return None

    cliclick = shutil.which("cliclick")
    if not cliclick:
        return None

    # Step 1: Search and enter chat
    search_script = _SCRIPT_SEARCH.format(community_name=name)
    if _run_osascript(search_script, timeout=15) is None:
        return None

    time.sleep(0.5)

    # Step 2: Get message area center coordinates
    coords = _run_osascript(_SCRIPT_GET_COORDS)
    if not coords or "," not in coords:
        _run_osascript(_SCRIPT_ESCAPE)
        return None

    # Step 3: cliclick to focus message area
    try:
        subprocess.run([cliclick, f"c:{coords}"], timeout=5, check=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        _run_osascript(_SCRIPT_ESCAPE)
        return None

    time.sleep(0.3)

    # Step 4: Select all + copy
    _run_osascript(_SCRIPT_COPY)

    # Step 5: Read clipboard
    try:
        clip = subprocess.check_output(["pbpaste"], text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        clip = ""

    # Step 6: Escape to restore state
    _run_osascript(_SCRIPT_ESCAPE)

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

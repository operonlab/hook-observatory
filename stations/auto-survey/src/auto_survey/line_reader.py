"""LINE Desktop reader — Screenshot + macOS Vision OCR to extract SurveyCake URLs.

Strategy: LINE Desktop v26 社群 (Community) windows don't expose text via
Accessibility API. Instead we:
1. AppleScript: activate LINE, search community, click result
2. screencapture -l <CGWindowID>: capture LINE window (works even if behind other windows)
3. macOS Vision framework (VNRecognizeTextRequest): local OCR, no API cost
4. Regex: extract SurveyCake URLs from OCR text
"""

import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

# OCR may misread www as ww/vvw, http as htt, etc.
SURVEYCAKE_RE = re.compile(r"https?://w{2,3}\.surveycake\.com/s/\w+")

# ---------------------------------------------------------------------------
# AppleScript helpers
# ---------------------------------------------------------------------------

_SCRIPT_ACTIVATE = """\
tell application "LINE" to activate
delay 1.5

tell application "System Events"
    tell process "LINE"
        if (count of windows) = 0 then
            click menu item "聊天" of menu "顯示" of menu bar 1
            delay 1.5
        end if
    end tell
end tell
"""

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


def _run_osascript(script: str, timeout: int = 15) -> str | None:
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


# ---------------------------------------------------------------------------
# Scroll support
# ---------------------------------------------------------------------------

_SCRIPT_SCROLL_UP = """\
tell application "System Events"
    tell process "LINE"
        key code 116
        delay 0.5
    end tell
end tell
"""


def _scroll_up_and_capture(wid: int, pages: int = 1) -> str:
    """Scroll up in the message area and OCR each page, accumulating text."""
    all_text = ""
    for _ in range(pages):
        _run_osascript(_SCRIPT_SCROLL_UP, timeout=5)
        time.sleep(0.5)
        screenshot = _capture_line_window(wid)
        if screenshot:
            cropped = _crop_message_area(screenshot)
            text = _ocr_image(cropped or screenshot)
            all_text = text + "\n" + all_text  # prepend older messages
            screenshot.unlink(missing_ok=True)
            if cropped:
                cropped.unlink(missing_ok=True)
    return all_text


# ---------------------------------------------------------------------------
# Screenshot via CGWindowID
# ---------------------------------------------------------------------------


def _get_line_window_id() -> int | None:
    """Get LINE's CGWindowID using Quartz."""
    try:
        import Quartz

        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for w in windows:
            if w.get("kCGWindowOwnerName") == "LINE" and w.get("kCGWindowName"):
                return int(w["kCGWindowNumber"])
    except Exception:
        log.debug("Quartz unavailable, cannot get LINE window ID")
    return None


def _capture_line_window(wid: int) -> Path | None:
    """Capture LINE window by CGWindowID, return path to PNG."""
    tmp = Path(tempfile.mktemp(suffix=".png", prefix="line_cap_"))
    try:
        subprocess.run(
            ["screencapture", "-l", str(wid), "-o", str(tmp)],
            timeout=10,
            check=True,
        )
        if tmp.exists() and tmp.stat().st_size > 1000:
            return tmp
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError):
        pass
    tmp.unlink(missing_ok=True)
    return None


def _crop_message_area(src: Path) -> Path | None:
    """Crop right pane (message area) from LINE window screenshot using sips."""
    dst = src.with_name(src.stem + "_crop.png")
    try:
        # Get image dimensions
        result = subprocess.run(
            ["sips", "-g", "pixelHeight", "-g", "pixelWidth", str(src)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        height = width = 0
        for line in result.stdout.splitlines():
            if "pixelHeight" in line:
                height = int(line.split(":")[-1].strip())
            elif "pixelWidth" in line:
                width = int(line.split(":")[-1].strip())

        if width < 400 or height < 300:
            return None

        # Right pane: starts at ~55% width, skip top 95px header, bottom 45px input
        crop_x = int(width * 0.55)
        crop_y = 95
        crop_w = width - crop_x
        crop_h = height - 140  # 95 top + 45 bottom

        subprocess.run(
            [
                "sips",
                "--cropToHeightWidth",
                str(crop_h),
                str(crop_w),
                "--cropOffset",
                str(crop_y),
                str(crop_x),
                str(src),
                "--out",
                str(dst),
            ],
            capture_output=True,
            timeout=10,
            check=True,
        )
        if dst.exists() and dst.stat().st_size > 500:
            return dst
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, ValueError):
        pass
    dst.unlink(missing_ok=True)
    return None


# ---------------------------------------------------------------------------
# macOS Vision OCR
# ---------------------------------------------------------------------------


def _ocr_image(image_path: Path) -> str:
    """Run macOS Vision OCR on an image, return concatenated text."""
    try:
        import Vision
        import Quartz
        from Foundation import NSURL

        image_url = NSURL.fileURLWithPath_(str(image_path))
        image_source = Quartz.CGImageSourceCreateWithURL(image_url, None)
        if not image_source:
            return ""
        cg_image = Quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)
        if not cg_image:
            return ""

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["zh-Hant", "zh-Hans", "en"])
        request.setUsesLanguageCorrection_(True)

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
        success, error = handler.performRequests_error_([request], None)

        if not success:
            log.warning("Vision OCR failed: %s", error)
            return ""

        lines = []
        for obs in request.results():
            candidates = obs.topCandidates_(1)
            if candidates:
                lines.append(candidates[0].string())

        return "\n".join(lines)
    except ImportError:
        log.warning("pyobjc Vision framework not available")
        return ""
    except Exception as e:
        log.warning("Vision OCR error: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _click_community_tab(wid: int) -> bool:
    """Click the 社群 tab in LINE using cliclick.

    Uses a fixed x-offset (325px from window left) determined by calibration.
    """
    try:
        import Quartz

        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        )
        for w in windows:
            if int(w.get("kCGWindowNumber", 0)) == wid:
                bounds = w["kCGWindowBounds"]
                wx = int(bounds["X"])
                wy = int(bounds["Y"])
                # 社群 tab at x=325 from window left, y=30 from top
                subprocess.run(
                    ["cliclick", f"c:{wx + 325},{wy + 30}"],
                    timeout=5,
                    check=True,
                )
                return True
    except Exception as e:
        log.debug("Failed to click community tab: %s", e)
    return False


def _find_and_click_community(wid: int, community_name: str) -> bool:
    """OCR the chat list to find community, then double-click it."""
    screenshot = _capture_line_window(wid)
    if not screenshot:
        return False

    try:
        import Quartz
        from Foundation import NSURL
        import Vision

        # OCR left panel to find community position
        src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(screenshot)), None)
        img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
        w = Quartz.CGImageGetWidth(img)
        h = Quartz.CGImageGetHeight(img)

        # Crop left panel (x=60-280, y=70-500)
        left = Quartz.CGImageCreateWithImageInRect(img, Quartz.CGRectMake(60, 70, 220, 430))

        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setRecognitionLanguages_(["zh-Hant", "en"])

        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(left, None)
        handler.performRequests_error_([req], None)

        # Find community name and its y position
        for obs in req.results():
            text = obs.topCandidates_(1)[0].string()
            if community_name in text:
                box = obs.boundingBox()
                # Convert Vision coords (bottom-left origin) to window coords
                y_in_crop = int((1 - box.origin.y - box.size.height / 2) * 430) + 70
                log.debug("Found '%s' at y=%d in window", community_name, y_in_crop)

                # Get window position for absolute click
                windows = Quartz.CGWindowListCopyWindowInfo(
                    Quartz.kCGWindowListOptionOnScreenOnly
                    | Quartz.kCGWindowListExcludeDesktopElements,
                    Quartz.kCGNullWindowID,
                )
                for win in windows:
                    if int(win.get("kCGWindowNumber", 0)) == wid:
                        bounds = win["kCGWindowBounds"]
                        wx = int(bounds["X"])
                        wy = int(bounds["Y"])
                        subprocess.run(
                            ["cliclick", f"dc:{wx + 150},{wy + y_in_crop}"],
                            timeout=5,
                            check=True,
                        )
                        return True
    except Exception as e:
        log.debug("OCR community search failed: %s", e)
    finally:
        screenshot.unlink(missing_ok=True)
    return False


def read_line_community(community_name: str | None = None) -> str | None:
    """Read LINE Desktop community messages via screenshot + OCR.

    Flow:
    1. Check LINE is running, activate it
    2. Click 社群 tab → OCR chat list to find community → double-click
    3. Screenshot LINE window via CGWindowID
    4. Crop message area, run macOS Vision OCR
    5. Return concatenated text

    Returns None if LINE is not running or any step fails.
    """
    name = community_name or settings.line_community_name

    # Ensure LINE is running — launch if needed
    if subprocess.run(["pgrep", "-x", "LINE"], capture_output=True).returncode != 0:
        log.info("LINE not running, launching...")
        subprocess.run(["open", "-a", "LINE"], timeout=10)
        # Wait for LINE to fully start and render window
        for _ in range(10):
            time.sleep(2)
            if subprocess.run(["pgrep", "-x", "LINE"], capture_output=True).returncode == 0:
                log.info("LINE launched, waiting for window to render")
                time.sleep(5)
                break
        else:
            log.warning("LINE failed to start after 20s")
            return None

    # Step 1: Activate LINE
    _run_osascript(_SCRIPT_ACTIVATE, timeout=10)

    # Step 2: Get LINE window ID
    wid = _get_line_window_id()
    if not wid:
        log.warning("Cannot get LINE window ID")
        return None

    # Step 3: Click 社群 tab
    if not _click_community_tab(wid):
        log.warning("Cannot click 社群 tab")
        return None
    time.sleep(1.5)

    # Step 4: OCR chat list to find and double-click community
    if not _find_and_click_community(wid, name):
        log.warning("Cannot find '%s' in community list", name)
        _run_osascript(_SCRIPT_ESCAPE)
        return None
    time.sleep(2.0)

    # Step 5: Screenshot and OCR the message area
    wid = _get_line_window_id()  # refresh WID
    if not wid:
        return None

    screenshot = _capture_line_window(wid)
    if not screenshot:
        _run_osascript(_SCRIPT_ESCAPE)
        return None

    cropped = _crop_message_area(screenshot)
    text = _ocr_image(cropped or screenshot)

    # Cleanup
    screenshot.unlink(missing_ok=True)
    if cropped:
        cropped.unlink(missing_ok=True)

    # Step 6: If no SurveyCake URLs found, scroll up and try again
    urls = SURVEYCAKE_RE.findall(text or "")
    if not urls and settings.line_scroll_pages > 0:
        log.info("No URLs in current view, scrolling up %d pages", settings.line_scroll_pages)
        # Click message area to focus it for scrolling
        scroll_text = _scroll_up_and_capture(wid, settings.line_scroll_pages)
        if scroll_text:
            text = scroll_text + "\n" + (text or "")

    _run_osascript(_SCRIPT_ESCAPE)

    log.info("OCR extracted %d chars from LINE community '%s'", len(text), name)
    return text if text.strip() else None


def extract_survey_urls(text: str) -> dict[str, str | None]:
    """Extract SurveyCake URLs from LINE message text.

    OCR often splits URLs across lines, so we first reassemble them
    by joining lines that look like URL continuations.
    Returns {'attend_url': ..., 'quiz_url': ...}.
    """
    result: dict[str, str | None] = {"attend_url": None, "quiz_url": None}

    # Reassemble broken URLs: join lines starting with www./http/surveycake
    # to the previous line (OCR line-break artifacts)
    lines = text.splitlines()
    merged: list[str] = []
    for line in lines:
        stripped = line.strip()
        if merged and re.match(r"^(w{2,3}\.|https?://|surveycake|[A-Za-z0-9]{3,8}$)", stripped):
            merged[-1] += stripped
        else:
            merged.append(stripped)
    text = "\n".join(merged)

    urls = SURVEYCAKE_RE.findall(text)
    if not urls:
        return result

    # Strategy: match URLs by proximity to keywords
    merged_lines = text.splitlines()
    for i, line in enumerate(merged_lines):
        if "簽到" in line:
            found = SURVEYCAKE_RE.search(line)
            if found:
                result["attend_url"] = found.group()
            elif i + 1 < len(merged_lines):
                found = SURVEYCAKE_RE.search(merged_lines[i + 1])
                if found:
                    result["attend_url"] = found.group()

        if "測驗" in line:
            found = SURVEYCAKE_RE.search(line)
            if found:
                result["quiz_url"] = found.group()
            elif i + 1 < len(merged_lines):
                found = SURVEYCAKE_RE.search(merged_lines[i + 1])
                if found:
                    result["quiz_url"] = found.group()

    # Fallback: assign first URL as attend, second as quiz
    if not result["attend_url"] and not result["quiz_url"] and urls:
        result["attend_url"] = urls[0]
        if len(urls) >= 2:
            result["quiz_url"] = urls[1]

    # Normalize OCR artifacts: ww.surveycake.com → www.surveycake.com
    for key in ("attend_url", "quiz_url"):
        if result[key]:
            result[key] = re.sub(r"://ww\.surveycake", "://www.surveycake", result[key])

    return result

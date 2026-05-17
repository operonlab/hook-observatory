# DashScope OAuth Refresh Runbook

When `agent-metrics dashscope-quota-sync` starts failing with
`Error: dashscope-quota-sync: scrape or parse failed`, the camoufox
session cookies for Alibaba have expired. Follow this runbook to
re-authenticate via Google OAuth and refresh the cookie snapshot.

Last verified working: **2026-05-17** (with full password auto-fill).

## TL;DR

```bash
~/.local/bin/python3 ~/workshop/schedules/runners/ws_dashscope_oauth_refresh.py
```

A headed camoufox window opens. The script auto-clicks the OAuth
buttons **and** auto-fills the Google password (read from macOS
Keychain). If Google is satisfied with just the password (no 2FA, no
device challenge), the whole flow is **zero-touch**.

If Google throws a 2FA or "verify it's you" challenge, the script
falls back to manual wait — finish the challenge in the camoufox
window, the script keeps polling.

Interactive time:
- Best case (password only): **~0 seconds** of user attention
- Worst case (2FA prompt): seconds spent on the 2FA, then automatic

## One-time setup: store Google password in Keychain

```bash
security add-generic-password \
    -s "google-oauth-dashscope" \
    -a "<your-google-email>" \
    -w "<your-google-password>" \
    -U
```

The script reads via ``security find-generic-password -s
google-oauth-dashscope -w``. Override service/account names with
``--keychain-service`` and ``--keychain-account``. Use
``--no-auto-password`` to disable auto-fill and fall back to manual
flow (also the implicit behavior when Keychain entry is missing).

If Google reports "Wrong password" after auto-fill, the script logs
the same ``security add-generic-password -U`` command for you to
update the Keychain entry.

## Symptoms that trigger this runbook

Any one of these is enough:

1. `ws-account-sync` Cronicle slot turns **red** with `worst_rc=1`.
2. `~/workshop/outputs/scheduler/logs/ws-account-sync.log` contains a
   line like:
   ```
   FAILED rc=1 stderr=...scrape or parse failed
   ```
3. Manual run prints `您当前处于未登录状态，登录后可使用完整服务`:
   ```bash
   ~/.cargo/shared-target/release/agent-metrics dashscope-quota-sync
   ```

## Why this is needed

| Layer | Behavior |
|---|---|
| Alibaba session cookies (`login_aliyunid_ticket`, `JSESSIONID`, `login_aliyunid_*`) | Session-scoped — die when the browser closes. |
| camoufox-cli persistence | Only persists *non-HttpOnly* cookies in the master profile. HttpOnly cookies (including the Alibaba ones above) are lost on close. |
| `~/.camoufox-profiles/master-login-cookies.json` | The rust collector's workaround — a one-time exported snapshot it re-imports on every run. **This is what goes stale**, usually after a few days. |
| Google OAuth state | If the Google account is still "Signed in" inside the camoufox profile, only one passkey tap is needed. If not, a full password re-auth on Google is also required. |

## What the script does (step-by-step)

The script lives at `~/workshop/schedules/runners/ws_dashscope_oauth_refresh.py`.

1. Reads Google password from Keychain (skip on miss; logs only the
   length, never the value).
2. Opens DashScope free-quota dashboard in a **headed** camoufox window
   using the master profile.
3. If already logged in (Google session still warm), jumps straight to
   the cookie-export step.
4. Auto-clicks 「立即登录」 → 「使用Google帳號登入」 → your Google account
   in the chooser (selected by email-substring match, default `@gmail.com`).
5. Detects the Google page state. If on the **passkey** page:
   - Clicks "Try another way"
   - Picks "Enter your password" from the alternatives list
6. Fills the visible password input from Keychain and submits.
7. Watches the post-submit state for up to 15s and branches:
   - `logged_in` → proceed to cookie export
   - `wrong_pw` → log Keychain-update instructions, fall through to
     the manual wait below
   - `twofa` → fall through to manual wait (you complete the 2FA in
     the open window)
   - anything else → fall through to manual wait
8. If not yet logged in, polls every 5s for up to 3 minutes, logging
   the current page state on each tick.
9. Backs up the old cookies file and writes a fresh snapshot via
   `camoufox-cli cookies export`.
10. Runs `agent-metrics dashscope-quota-sync` to verify end-to-end.
    Looks for the `parsed total_models=N` line in the rust log.
11. Closes the camoufox session.

Exit codes:
- `0` — login + export + verify all succeeded.
- `2` — failed to open the headed window (camoufox broken).
- `3` — couldn't find the 立即登录 button (layout changed).
- `4` — couldn't find the Google login link (layout changed).
- `5` — timeout waiting for login (>3 minutes).

## Manual fallback (if the script breaks)

If the aria selectors stop matching (Alibaba redesigned the login page),
the script will exit 3 or 4. Manual recovery:

```bash
# 1. Open a headed camoufox session yourself
camoufox-cli --session ds-manual --headed --persistent ~/.camoufox-profiles/master \
    open "https://modelstudio.console.alibabacloud.com/ap-southeast-1/?tab=dashboard#/model-usage/free-quota"

# 2. In the window: click 立即登录 → 使用Google帳號登入 → your account →
#    complete passkey. Wait until you see the dashboard with "模型用量".

# 3. Export the cookies
cp ~/.camoufox-profiles/master-login-cookies.json \
   ~/.camoufox-profiles/master-login-cookies.json.bak-$(date +%Y%m%d)
camoufox-cli --session ds-manual cookies export \
    ~/.camoufox-profiles/master-login-cookies.json

# 4. Close the session
camoufox-cli --session ds-manual close

# 5. Verify
~/.cargo/shared-target/release/agent-metrics dashscope-quota-sync
echo "exit code: $?"
```

If step 5 prints `parsed total_models=N` and exits 0, you're done.

## Why this is NOT cron'd

Google passkey requires physical user authentication (Touch ID / Face ID /
system password). There's no headless path. The audit signal flows the
other direction: `ws-account-sync` runs daily at 18:15 and turns the
Cronicle slot red when the dashscope half fails. You then run this
script manually at the next convenient moment.

If you want a Bark notification on failure, add a hook to
`ws_account_sync.py` to push when `worst_rc != 0` — but the Cronicle
red-slot signal is usually enough.

## Related files

- Runner: `~/workshop/schedules/runners/ws_dashscope_oauth_refresh.py`
- Rust collector: `~/workshop/stations/agent-metrics/src/collectors/dashscope_quota.rs`
- Merged daily sync: `~/workshop/schedules/runners/ws_account_sync.py`
- Original Python (deprecated, kept for reference): `~/workshop/schedules/runners/ws_credits_sync.py` (`_dashscope_auto_login`)
- Cookies snapshot: `~/.camoufox-profiles/master-login-cookies.json`
- camoufox profile: `~/.camoufox-profiles/master/`

## Future hardening ideas (not implemented)

- **Pre-emptive weekly refresh** — schedule this script on Sundays at
  some quiet hour. Tradeoff: still needs user passkey each time, so
  it would just shift when you get interrupted.
- **Bark push on first failure** — small addition to `ws_account_sync.py`
  to fire `bark://...` URL when `worst_rc != 0`.
- **HttpOnly cookie injection via WebExtension** — bypass camoufox's
  non-persistence by writing a Firefox extension that touches the
  cookie store directly. Worth it only if this stops being a once-a-week
  thing.

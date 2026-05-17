# DashScope OAuth Refresh Runbook

When `agent-metrics dashscope-quota-sync` starts failing with
`Error: dashscope-quota-sync: scrape or parse failed`, the camoufox
session cookies for Alibaba have expired. Follow this runbook to
re-authenticate via Google OAuth and refresh the cookie snapshot.

Last verified working: **2026-05-17**.

## TL;DR

```bash
~/.local/bin/python3 ~/workshop/schedules/runners/ws_dashscope_oauth_refresh.py
```

A headed camoufox window opens. The script auto-clicks the first three
buttons; when the Google passkey screen appears, **touch the fingerprint
sensor (or enter the system password)** in that window. The script
polls for up to 3 minutes, then exports cookies and runs a verification.

Total interactive time: ~30 seconds (most of it is the script waiting
for redirects).

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

1. Opens DashScope free-quota dashboard in a **headed** camoufox window
   using the master profile.
2. If already logged in, jumps straight to step 5.
3. Auto-clicks 「立即登录」 → 「使用Google帳號登入」 → your Google account
   in the chooser (selected by email-substring match, default `@gmail.com`).
4. **Pauses here** — you must complete the Google passkey/password
   prompt in the camoufox window. The script polls every 5s for up to
   3 minutes.
5. Once login is detected (page contains `模型用量` or `默认业务空间`):
   - Backs up the old cookies file to
     `~/.camoufox-profiles/master-login-cookies.json.bak-<ts>`.
   - Runs `camoufox-cli cookies export …` to write a fresh snapshot.
6. Runs `agent-metrics dashscope-quota-sync` to verify the new cookies
   work end-to-end. Looks for the `parsed total_models=N` log line.
7. Closes the camoufox session.

Exit codes:
- `0` — login + export + verify all succeeded.
- `2` — failed to open the headed window (camoufox broken).
- `3` — couldn't find the 立即登录 button (layout changed).
- `4` — couldn't find the Google login link (layout changed).
- `5` — timeout waiting for user passkey (>3 minutes).

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

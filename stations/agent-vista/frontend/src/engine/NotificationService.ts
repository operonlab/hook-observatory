// Desktop notification service (C7)
// Sends browser notifications for critical agent events when tab is not focused

class NotificationService {
  private _enabled = false;
  private _permissionRequested = false;
  private _lastNotifyTime = 0;
  private _cooldownMs = 5000; // min 5s between notifications

  /** Request notification permission (call on first user interaction) */
  async requestPermission(): Promise<boolean> {
    if (!('Notification' in window)) return false;
    if (this._permissionRequested) return this._enabled;
    this._permissionRequested = true;

    if (Notification.permission === 'granted') {
      this._enabled = true;
      return true;
    }
    if (Notification.permission === 'denied') return false;

    const result = await Notification.requestPermission();
    this._enabled = result === 'granted';
    return this._enabled;
  }

  get enabled() { return this._enabled; }

  /** Send a notification (only when tab is not focused) */
  notify(title: string, body: string) {
    if (!this._enabled) return;
    if (document.hasFocus()) return;

    const now = Date.now();
    if (now - this._lastNotifyTime < this._cooldownMs) return;
    this._lastNotifyTime = now;

    try {
      new Notification(title, {
        body,
        tag: 'agent-vista',
        silent: false,
      });
    } catch {
      // Notification creation failed — ignore
    }
  }

  /** Notify: agent needs permission (tool_permission) */
  notifyPermissionNeeded(cliType: string, sessionId: string) {
    this.notify(
      `${cliType} 需要授權`,
      `工作階段 ${sessionId.slice(-4)} 正在等待授權許可`,
    );
  }

  /** Notify: new session started */
  notifySessionStart(cliType: string, sessionId: string) {
    this.notify(
      `${cliType} 上線`,
      `新的工作階段 ${sessionId.slice(-4)} 已啟動`,
    );
  }

  /** Notify: session ended */
  notifySessionEnd(cliType: string, sessionId: string) {
    this.notify(
      `${cliType} 離線`,
      `工作階段 ${sessionId.slice(-4)} 已結束`,
    );
  }

  /** Notify: error event */
  notifyError(cliType: string, sessionId: string) {
    this.notify(
      `${cliType} 發生錯誤`,
      `工作階段 ${sessionId.slice(-4)} 回報錯誤`,
    );
  }
}

/** Global singleton */
export const notificationService = new NotificationService();

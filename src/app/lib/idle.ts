/** How long a person can do nothing before they are logged out. Matches the lifetime of an access token. */
export const IDLE_LOGOUT_MS = 15 * 60 * 1000;
/** How often the page checks the clock. A hidden tab may run its timers late, so the check compares real times. */
export const IDLE_CHECK_MS = 15 * 1000;

export const IDLE_NOTICE = "You were logged out after 15 minutes of inactivity. Please log in again.";

/** Browser events that count as "the person is here". */
export const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart", "scroll"] as const;

export function isIdle(lastActivity: number, now: number, limitMs: number = IDLE_LOGOUT_MS): boolean {
  return now - lastActivity >= limitMs;
}

/** Remembers the latest activity time; activity seen in another tab can move it forward but never backward. */
export class ActivityClock {
  private last: number;

  constructor(now: number) {
    this.last = now;
  }

  touch(at: number): void {
    if (at > this.last) this.last = at;
  }

  get lastActivity(): number {
    return this.last;
  }

  idle(now: number, limitMs: number = IDLE_LOGOUT_MS): boolean {
    return isIdle(this.last, now, limitMs);
  }
}

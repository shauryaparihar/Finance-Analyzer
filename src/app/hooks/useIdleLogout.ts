import { useEffect } from "react";
import { ACTIVITY_EVENTS, ActivityClock, IDLE_CHECK_MS, IDLE_LOGOUT_MS } from "../lib/idle";

const CHANNEL = "finsight-activity";

/**
 * While `enabled`, call `onIdle` once the person has done nothing for `limitMs`. Activity in any open tab of the
 * site counts (shared through a BroadcastChannel, nothing is written to browser storage), so working in one tab
 * does not log you out of another.
 */
export function useIdleLogout(enabled: boolean, onIdle: () => void, limitMs: number = IDLE_LOGOUT_MS): void {
  useEffect(() => {
    if (!enabled) return;
    const clock = new ActivityClock(Date.now());
    const channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL);
    let lastShared = 0;

    const onActivity = () => {
      const now = Date.now();
      clock.touch(now);
      if (channel && now - lastShared > 5000) {
        lastShared = now; // tell the other tabs, at most every few seconds
        channel.postMessage(now);
      }
    };
    channel?.addEventListener("message", (event: MessageEvent<number>) => clock.touch(Number(event.data)));
    for (const name of ACTIVITY_EVENTS) window.addEventListener(name, onActivity, { passive: true });

    let fired = false;
    const check = () => {
      if (!fired && clock.idle(Date.now(), limitMs)) {
        fired = true;
        onIdle();
      }
    };
    const timer = window.setInterval(check, IDLE_CHECK_MS);
    document.addEventListener("visibilitychange", check); // back from a long sleep: decide straight away

    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", check);
      for (const name of ACTIVITY_EVENTS) window.removeEventListener(name, onActivity);
      channel?.close();
    };
  }, [enabled, onIdle, limitMs]);
}

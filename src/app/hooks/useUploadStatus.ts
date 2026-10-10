import { useCallback, useEffect, useState } from "react";
import { getUploadStatus } from "../api";
import { isActive } from "../lib/status";
import type { UploadStatusResponse } from "../types";

const POLL_MS = 3000;

/**
 * The status of one upload. While it is queued or processing this asks again every few seconds.
 * Polling is enough here: an analysis takes seconds, and it avoids the extra moving parts of WebSockets.
 */
export function useUploadStatus(uploadId: string | null) {
  const [status, setStatus] = useState<UploadStatusResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(uploadId !== null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!uploadId) {
      setStatus(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll(id: string) {
      try {
        const next = await getUploadStatus(id);
        if (cancelled) return;
        setStatus(next);
        setError(null);
        setLoading(false);
        if (isActive(next.status)) timer = setTimeout(() => void poll(id), POLL_MS);
      } catch (e) {
        if (cancelled) return;
        setError(e);
        setLoading(false);
      }
    }
    setLoading(true);
    void poll(uploadId);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [uploadId, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { status, error, loading, reload };
}

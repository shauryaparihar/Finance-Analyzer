import { useCallback, useEffect, useRef, useState } from "react";

interface ResourceState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
}

/** Load something from the API when the dependencies change. Ignores answers that arrive after the page moved on. */
export function useResource<T>(loader: () => Promise<T>, deps: readonly unknown[]) {
  const [state, setState] = useState<ResourceState<T>>({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let cancelled = false;
    setState((previous) => ({ ...previous, loading: true }));
    loaderRef
      .current()
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error: unknown) => !cancelled && setState({ data: null, error, loading: false }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((updater: (current: T) => T) => {
    setState((previous) => (previous.data === null ? previous : { ...previous, data: updater(previous.data) }));
  }, []);
  return { ...state, reload, setData };
}

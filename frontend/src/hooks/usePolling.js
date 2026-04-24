import { useEffect, useRef, useState } from "react";

export default function usePolling(fetcher, intervalMs = 15000, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    let timer;

    const run = async () => {
      try {
        const result = await fetcher();
        if (mounted.current) {
          setData(result);
          setError(null);
        }
      } catch (err) {
        if (mounted.current) setError(err);
      } finally {
        if (mounted.current) setLoading(false);
      }
    };

    run();
    if (intervalMs > 0) {
      timer = setInterval(run, intervalMs);
    }

    return () => {
      mounted.current = false;
      if (timer) clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading };
}

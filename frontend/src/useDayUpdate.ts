import { useEffect, useRef, useState } from "react";
import { ApiError, type BackendClient } from "./api";
import {
  forgetUpdate,
  savedUpdate,
  updateKey,
  type DayUpdate,
} from "./dayUpdate";
import type { Mode } from "./guide";

export function useDayUpdate(
  client: BackendClient | null,
  day: string,
  mode: Mode,
  cursor?: string,
) {
  const [job, setJob] = useState<DayUpdate | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const current = useRef({ day, mode });
  current.current = { day, mode };
  useEffect(() => {
    setError(null);
    const saved = client
      ? savedUpdate(window.localStorage, client.profileId)
      : null;
    setJob(saved?.date === day ? saved : null);
  }, [client, day, mode]);

  useEffect(() => {
    if (!client || !job || job.date !== day || mode !== "browse") return;
    let alive = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const jobId = job.job_id;
    async function poll() {
      try {
        const status = await client!.updateStatus(jobId, controller.signal);
        if (!alive) return;
        if (status.date !== day || status.job_id !== jobId)
          throw new Error("Update belongs to another date.");
        setJob(status);
        if (status.state === "finished" || status.state === "failed") {
          try {
            forgetUpdate(window.localStorage, client!.profileId, jobId);
          } catch {
            /* Status still works without storage. */
          }
          setVersion((n) => n + 1);
        } else timer = setTimeout(() => void poll(), 1500);
      } catch (cause) {
        if (!alive) return;
        setJob(null);
        if (cause instanceof ApiError && cause.status === 404) {
          try {
            forgetUpdate(window.localStorage, client!.profileId, jobId);
          } catch {
            /* No write is triggered on reload. */
          }
          setVersion((n) => n + 1);
          setError(
            "The server restarted or this update was replaced. Saved data is kept; fetch this date again.",
          );
        } else
          setError(
            "Cannot check the update. Click Fetch again to reconnect; an active job will be reused.",
          );
      }
    }
    void poll();
    return () => {
      alive = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [client, job?.job_id, day, mode]);

  async function start(fetchEvidence = true) {
    if (!client || !cursor || mode !== "browse" || starting) return;
    setStarting(true);
    setError(null);
    setJob(null);
    try {
      const incoming = await client.startDayUpdate(day, cursor, fetchEvidence);
      if (incoming.date !== day) throw new Error("Update date mismatch.");
      try {
        window.localStorage.setItem(
          updateKey(client.profileId),
          JSON.stringify({ job_id: incoming.job_id, date: incoming.date }),
        );
      } catch {
        /* Polling still works; reload recovery is unavailable in this browser. */
      }
      if (current.current.day === day && current.current.mode === "browse")
        setJob(incoming);
    } catch (cause) {
      if (current.current.day === day && current.current.mode === "browse")
        setError(
          cause instanceof ApiError && cause.status === 409
            ? "Another date update may be running, or your saved timeline changed. Wait for it to finish or reload saved state."
            : "Could not start the update. Check that the local backend and database are available, then retry.",
        );
    } finally {
      setStarting(false);
    }
  }
  return {
    job: job?.date === day ? job : null,
    starting,
    error,
    version,
    start,
    active:
      starting ||
      (job?.date === day && ["collecting", "publishing"].includes(job.state)),
  };
}

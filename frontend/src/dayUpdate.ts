/** Spoiler-opaque job status. No source rows, game counts or ratings are accepted. */
export type DayUpdate = {
  job_id: string;
  date: string;
  state: "collecting" | "publishing" | "finished" | "failed";
  error?: string;
};
const UUID = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
const errors = new Set([
  "update_interrupted",
  "update_time_limit",
  "morning_source_policy_not_ready",
  "sports_collection_already_running",
  "sources_unavailable",
  "update_partly_saved",
  "day_game_limit",
  "update_failed",
]);
export function parseDayUpdate(raw: unknown): DayUpdate {
  if (!raw || typeof raw !== "object" || Array.isArray(raw))
    throw new Error("Invalid update status.");
  const d = raw as Record<string, unknown>;
  if (
    Object.keys(d).some(
      (k) => !["job_id", "date", "state", "error"].includes(k),
    ) ||
    typeof d.job_id !== "string" ||
    !UUID.test(d.job_id) ||
    typeof d.date !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(d.date) ||
    !["collecting", "publishing", "finished", "failed"].includes(
      String(d.state),
    ) ||
    (d.error !== undefined &&
      (d.state !== "failed" || !errors.has(String(d.error))))
  )
    throw new Error("Invalid update status.");
  return d as DayUpdate;
}
export const updateKey = (profile: string) =>
  `nba-time-machine:day-update:v1:${profile}`;
export function savedUpdate(
  storage: Pick<Storage, "getItem">,
  profile: string,
): DayUpdate | null {
  try {
    const raw = JSON.parse(storage.getItem(updateKey(profile)) ?? "null");
    if (!raw || Object.keys(raw).some((k) => !["job_id", "date"].includes(k)))
      return null;
    return parseDayUpdate({ ...raw, state: "collecting" });
  } catch {
    return null;
  }
}
export function updateFailure(code?: string): string {
  if (code === "morning_source_policy_not_ready")
    return "The local data sources are not ready. Check their configured access and retention policy.";
  if (code === "sports_collection_already_running")
    return "Another collection is running. Try again when it finishes.";
  if (code === "sources_unavailable")
    return "The providers could not be reached. Saved data is kept; try again later.";
  if (code === "update_partly_saved")
    return "Some updates could not be saved. Other games were kept. You can retry this date.";
  if (code === "update_time_limit")
    return "The update reached its time limit. Saved data is kept; you can retry this date.";
  return "The update could not finish. Saved data is kept; you can retry this date.";
}

export function forgetUpdate(
  storage: Pick<Storage, "getItem" | "removeItem">,
  profile: string,
  jobId: string,
) {
  if (savedUpdate(storage, profile)?.job_id === jobId)
    storage.removeItem(updateKey(profile));
}

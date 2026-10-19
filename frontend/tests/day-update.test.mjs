import test from "node:test";
import assert from "node:assert/strict";
import {
  parseDayUpdate,
  savedUpdate,
  forgetUpdate,
  updateKey,
} from "../src/dayUpdate.ts";
const job = {
  job_id: "00000000-0000-0000-0000-000000000077",
  date: "2026-10-18",
  state: "collecting",
};
test("update status rejects incidental outcome fields and arbitrary error/source text", () => {
  assert.deepEqual(parseDayUpdate(job), job);
  for (const raw of [
    { ...job, rating: 8 },
    { ...job, completed: 2 },
    { ...job, games: [] },
    { ...job, state: "failed", error: "raw source body" },
    { ...job, job_id: "wrong" },
    { ...job, state: "bogus" },
  ])
    assert.throws(() => parseDayUpdate(raw));
});
test("saved opaque job recovers without storing outcomes and an old tab cannot remove a newer handle", () => {
  const map = new Map();
  const storage = {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => map.set(k, v),
    removeItem: (k) => map.delete(k),
  };
  storage.setItem(
    updateKey("profile"),
    JSON.stringify({ job_id: job.job_id, date: job.date }),
  );
  assert.deepEqual(savedUpdate(storage, "profile"), job);
  forgetUpdate(storage, "profile", "00000000-0000-0000-0000-000000000099");
  assert.ok(savedUpdate(storage, "profile"));
  forgetUpdate(storage, "profile", job.job_id);
  assert.equal(savedUpdate(storage, "profile"), null);
});

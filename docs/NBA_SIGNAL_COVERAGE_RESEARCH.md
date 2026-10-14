# $0 NBA signal research — issue #82

Research only; 2026-10-14. This supersedes PR #81's proposed paid-provider
and calibration next steps for this issue. All scoring/weights remain deferred.
PR #81 is the unchanged parent; this follow-up does not replace it.

Initial local backend probes: liveData PBP and box score HTTP 403; Stats V3
transport timeout. The complete timestamped five-game sample is in
`evidence/issue-82-signal-access.jsonl` (health metadata only). Full report and
family-specific decisions follow after sample validation. No real-game source
adapter is authorized by a failed request; synthetic contract validation is not
an NBA parser or proof of access. No database writes or activation.

Handoff: run the synthetic tests, finish the four-family matrix and review the
sample diagnostics. Record browser evidence separately from backend requests.

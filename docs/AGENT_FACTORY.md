# Agent factory

The project is designed for interchangeable coding agents. ChatGPT, Codex, Copilot, Antigravity or another engine may stop mid-task and another engine must be able to continue without the prior conversation.

## Trigger

When an agent is given only:

```text
Go
```

it executes the recovery/selection algorithm in `AGENTS.md`.

## Durable state

Only repository-visible state is authoritative for handoff:

- open pull requests;
- remote branches and commits;
- linked GitHub Issues;
- PR review threads/comments;
- CI/check results;
- repository documentation.

Chat transcripts, local working trees, private plans and model scratchpads are not durable factory state.

## Work-selection state machine

```text
Go
 |
 v
Open unfinished PR exists?
 | yes
 v
Review issue + diff + reviews + CI
 |
Can current PR be advanced?
 | yes ----------------------> continue same branch -> validate -> update checkpoint
 | no
 v
Record blocker/reason
 |
 v
Find next unblocked issue by implementation phase
 |
 v
Create branch -> implement -> push coherent checkpoint -> open/update PR
 |
 v
Self-review + tests + CI
 |
 +--> incomplete: leave explicit handoff checkpoint
 |
 +--> complete: PR ready for merge/review
```

## What counts as unfinished

An open PR is unfinished when any of these apply:

- draft status;
- failing or incomplete required checks;
- unresolved review findings;
- linked issue acceptance criteria are not satisfied;
- PR body/checkpoint lists remaining work;
- implementation is obviously partial after reviewing the diff.

An open PR that is fully implemented and merely awaiting human merge/review should not monopolize the factory. The next agent may pick the next independent issue instead.

## Recovery rule

Recovery is review-first. A new agent must inspect what exists and may correct or replace a flawed implementation inside the same PR scope. "Continue" does not mean preserve mistakes.

## Progress rule

Prefer completing work over maximizing the number of open PRs. Do not open parallel implementations for the same issue.

## Blocking rule

External blockers such as missing Neon credentials must not stop unrelated work. Document the blocker and advance another independent task from the roadmap.

## Checkpoint rule

For unfinished PRs, keep the PR template's handoff checkpoint current:

- completed;
- remaining;
- current failures/blockers;
- next concrete action.

A good checkpoint is precise enough that a new engine can execute the next action without asking what happened.

# Goal Compass Feedback and Reuse Runtime Status

Date: 2026-07-17

Version: `0.1.0+codex.20260717054301`

## Delivered

- Governance errors, policy blocks, false positives, false negatives, wrong statuses,
  workflow friction, and unhandled plugin exceptions are written atomically to a
  local outbox before any network attempt.
- Feedback stays in a local durable outbox by default. A configured endpoint or
  environment variable cannot transmit until the project grants explicit upload
  consent. Failed delivery stays queued and never blocks product execution.
- Feedback payloads contain rule, command, outcome, plugin/runtime metadata, a
  hashed project identity, and redacted context. Prompt text, source content,
  environment values, and credentials are excluded.
- On the project's first confirmed use, Goal Compass performs one project-scoped
  GitHub reuse probe. Read-only work skips the probe.
- Probe results are shared across conversations and tickets for five days. The
  next mutation after expiry refreshes against the North Star and remaining work,
  while reporting releases or repository updates for previously seen software.
- A strong reusable candidate requires an explicit adopt, extend, or
  evidence-backed rejection disposition. Reference-only candidates do not block.

## Runtime Verification

- Local HTTP receiver test: immediate POST succeeded; credential-like text was
  redacted before delivery.
- Unconfigured/unavailable receiver test: event remained in the durable outbox and
  the product command continued.
- Real GitHub negative probe: a Goal Compass-specific feedback delivery task
  returned `NO_CANDIDATES` without accepting zero-term matches.
- Real GitHub positive probe: an OpenTelemetry Collector task found the official
  Collector and related licensed repositories as direct-reuse candidates and
  required a disposition before custom implementation.
- Module suite: `264 tests`, `58.32s`, `OK`.
- Discovery suite: `264 tests`, `57.40s`, `OK`.
- Selftest: `0.54s`, `Goal Compass selftest OK`.
- Plugin validator: passed.
- Skill validator: passed.

## Server Connection State

No shared bearer token is embedded in the plugin. Enterprise, personal, and
non-interactive installs all default to local-only delivery. Remote delivery
becomes active only after project-scoped consent; the plugin then registers a
revocable device credential automatically and never asks the user to configure
or paste a Token:

```bash
python3 .agent/goal_compass.py feedback-config \
  --context enterprise \
  --allow-upload --confirm-upload --flush
```

The public receiver has no manual, browser, file, ZIP, or multipart upload
surface. It accepts only the bounded Goal Supervisor JSON event contract.

Until then, feedback is captured locally in
`.agent/runtime/feedback-outbox/`. A central maintainer may consume the event's
`maintainer_action` to open a reproduction-and-repair ticket, but installed project
copies never modify plugin source automatically from unverified telemetry.
`feedback-config --deny-upload` immediately revokes transmission while preserving
the local outbox.

## Net-Benefit Boundary

- Network failure is advisory and non-blocking.
- Reuse discovery runs once per project and at most once per five-day project
  window unless an operator explicitly forces a diagnostic refresh.
- A confirmed suitable tool is written into the ticket implementation and
  validation contract; research-only acknowledgment cannot satisfy the gate.
- No third-party repository is cloned, installed, or executed automatically.
- Search results are candidate evidence, not proof of compatibility.

## Project-Scoped Reuse Correction

Previous behavior cached probes by task fingerprint, so a new ticket or changed
bounded action could cause another search before the five-day project window
ended. The cache authority is now project-level:

- first confirmed project use performs one search;
- conversation continuation and new tickets reuse it without network or state writes;
- the first product mutation after five days refreshes once;
- refresh context includes the North Star, active phase, pending tickets,
  current must-do items, and backlog actions;
- previously seen repositories are checked even when no longer returned by the
  new-action query;
- confirmed adoption or extension is inserted into the ticket implementation
  and validation contract, and only successful close marks it `VERIFIED`.

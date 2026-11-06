# Outcome-First Agent Loop — Submission

**Name:** Rishav Singhania · **Date:** 2026-11-06 · **Hours actually spent (be honest):** About 6 · **Language / storage:** Python 3.11+ / SQLite

## 0. TL;DR

The controller learns from the simulator's HTTP event stream, tests welcome and voice changes under approval, and responds to caller-ID and prompt incidents.
On public_02 the conclusion rate rose 6.0% relative to baseline with no harmful changes. Public_01 ended at -0.2%, inside run-to-run noise. The prompt fix cost seven credits but took 1,530 simulated minutes, because the six-hour detector missed a 4.5% flag rate.
A crash at each of two remote write boundaries recovered on the same simulator. See the load and crash reports for the measurements.
Call-time optimisation, a feature store, customer-level trace retention and a supervisor UI are outside this implementation.

## 1. Assumptions

1. One controller owns the clock for one simulator world. A restart uses the same simulator URL and the same SQLite file. A fresh simulator gets a fresh SQLite path.
2. Approval state, version history and events are authoritative. The API exposes the approval ID and decision time but no approver name. The audit keeps the ID and the decision payload. The controller cannot supply a person's name.
3. Caller ID, voice and welcome options are randomised per dial within each configured cohort. Repeated calls to one lead are correlated. The implementation inflates variance for decisions, and the resulting intervals are approximate.
4. The default cohort is the catch-all from the simulator config. A default allocation change is in scope only if all explicit cohorts override that dimension. Prompt changes always cover the workflow.
5. Callers currently carrying traffic can serve as contemporaneous references. Unused caller IDs have no observed rate. An automated hallucination flag is a noisy signal, and a synthetic validation pass measures safety.
6. Timestamps from the simulator use IST and all public policies use a daytime opening and closing hour. The effective opening hour and request cap for Kestrel also honor the supervisor's stricter memo.
7. The affected-lead field is estimated reach through the cadence horizon plus the next upload. Some leads in that population will already have concluded or never receive the changed arm.
8. The controller preserves the supplied schedule, cadence and capacity. A prompt safety incident takes priority over starting a new experiment. A caller-ID incident may justify restoring pickup under a bounded engagement risk even where engagement is primary.

## 2. Scope decisions

| # | Capability | Status | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Event ingestion | Built | All decisions depend on durable event counts | Add retention, broker partitions and consumer offsets for a production feed |
| C2 | Feature joins and shared cohorts | Partial | The dial already carries the canonical config cohort ID | Persist lead features, cohort versions and denominators by feature slice |
| C3 | Bootstrap from history | Built | Past data sizes tests, supplies QA references and helps distinguish caller drift | Add source-health and backfill coverage checks |
| C4 | Call time | Cut | Hour and attempt are confounded without controlled dispatch | Build an experiment that preserves every eligible hour and capacity |
| C5 | Caller-ID health | Partial | Compare active IDs, shift within policy and retain a probe | Add first-use exploration, carrier data and recovery trials for retired IDs |
| C6 | Welcome and voice experiments | Built | One randomised contrast at a time on engagement-primary workflows | Add feature slices and a powered interaction test when volume supports it |
| C7 | Promotion and rollback | Built | An expected-loss readout promotes to 80/20, and the retained control supports a harm stop | Exercise decay on a dedicated fixture, since no public scenario has one |
| C8 | Hallucination response | Built | A safety incident needs a separate diagnosis and an approved, validated fix | Add manual QA sampling and alternative candidate review when engagement drops |
| C9 | Governance | Partial | Versioned approval, reconciliation, rate limits and policy-permitted caller auto-apply cover the write paths | Add multi-action batching, cancellation and named approvals to the API |
| C10 | Impact, reach and dry run | Partial | Give approvers the counts, method and uncertainty behind each request | Count active distinct eligible leads and calibrate impact against realised lift |
| C11 | Supervisor view | Cut | CLI audit is enough to reconstruct decisions for this run | Build a tenant-scoped read model with experiments and approvals in one place |
| C12 | Decision audit | Built | Local records link config changes, approvals, evidence and follow-up | Add authenticated reads and retention controls |
| C13 | Crash recovery | Built | Two real SIGKILLs exercise ambiguous remote writes | Run a wider fault matrix and test storage failure |
| C14 | Controller observability | Partial | Checkpoints, round timings, approval and credit logs expose the failure boundaries | Export metrics and route actionable alerts |
| C15 | Allocation of attention and credits | Partial | One proposal per workflow, cooldowns and a shared credit reserve | Add tenant budgets, fair queues and priority for urgent incidents |

I prioritised the paths where an incorrect decision would either harm customers or lose the evidence needed to explain it. The remaining time went to a narrow experiment loop using existing cohorts.

## 3. Stakeholders

### 01 Sales

Accepted a clear client-level outcome, using concluded leads divided by uploads. Pickup and engagement are shown separately alongside it. Same-day promotion depends on evidence and approval. In the public workflows, Kestrel cancellation permits a limited set of dimensions with a 0.20 total-variation cap. Northwind KYC has auto-apply disabled. A prompt that worked in another demo has no evidence on this workflow.

> Nikhil, the summit can show concluded leads out of uploads, alongside pickup and engagement. We can act the same day if a test has enough evidence and the approver is available. Kestrel's policy only allows specified changes within a shift limit. Northwind KYC requires approval. I'd show the incident timeline and the measured recovery so the audience can see what the agent changed.

### 02 Client compliance

Customer-facing changes go through approval, even where the API permits auto-apply. Prompt changes attach the validation ID. Northwind's two public workflows match the stated hours, but only renewal permits operational auto-apply. Workflow/version evidence is kept. The API supplies an approval ID without a person's name, and this build keeps aggregates instead of a customer-level trace.

> Meera, every voice, welcome or prompt change requires approval, and every prompt request carries a validation run ID. Renewal's signed policy permits bounded caller-ID changes. KYC requires approval. We can show what changed and why at workflow level today. For an individual customer inquiry, we'd need retained per-call variant records and a named approver identity from the platform.

### 03 Platform and SRE

SQLite is a local durable file with no added service to operate. The crash script kills the controller after a remote proposal write and after a remote apply. The platform clock point is correct for production. In this simulator the controller advances it, so simulated freshness and wall-clock processing are reported separately.

> Kabir, the kill test covers both sides of the approval flow where the server can commit before the controller saves the result. Both restart from the same SQLite file. The load report separates HTTP ingest time from full round time. For production I'd keep the same state model in Postgres and consume from the existing durable event feed.

### 04 Client operations supervisor

Kestrel gets at most two requests per rolling day, sent at 11:00 or later within API hours. Experiments are invalidated when a supervisor changes config. A new prompt request after a supervisor edit requires incident evidence, fresh validation and approval. Policy may permit in-flight caller changes without notice. The CLI provides a timeline. There is no consolidated screen or advance notification for auto-apply.

> Anita, if you change a live config during a trial, we stop reading that trial as if its conditions still hold. If a prompt you shipped triggers a safety incident, we bring you the measured flags and a validated candidate before changing it. Requests stay within your hours and two-per-day limit. The timeline shows caller rotations that policy allows us to apply directly. A single supervisor screen and advance notice still need product work.

### 05 Product

Accepted separate KPIs, one cohort ID from the call record, required proposal evidence, and learning only from variants that ran. Expired and rejected are separate API states. Both return to evaluation, with a cooldown after rejection and a fresh proposal ID. The impact value is a triage aid with units tied to the proposed action. Per-person call times and the supervisor view were cut.

> Tara, the proposal shows the eligible population estimate, observed counts and how we calculated the score. Every trial readout uses the same cohort ID the dialler recorded. An expired request is distinct from a rejection. We can revisit either with fresh evidence and policy checks. I'd ship the timeline and caller health first, then decide how much volume we can give to a call-time trial.

### 06 CTO

Accepted safety and evidence ahead of speculative lift. We spend credits on detected prompt incidents and keep a reserve. There is no assumption that a permission granted to one workflow carries over to another. Shared client infrastructure and live drift response have a clearer payoff than a model for per-person call time at this stage.

> Aryamann, I built the write boundary and the evidence needed to explain a change after restart. On public_02 the controller moved traffic off the failing caller ID and took a validated prompt fix through approval. The experiments were deliberately narrow, and the reports show what they cost. I'd fix that measurement problem before expanding to more cohorts or call-time optimisation.

## 4. Architecture

```text
 Simulator HTTP
   history + new chunks ──> stream/decode ──> SQLite chunk cursor + hourly counts
   policy + config versions ────────────────────────────────┐
                                                           v
                         incident checks and experiment readout
                                      │  write intent first
                                      v
 SQLite evidence + proposal journal <── governance ──> approvals/apply or caller PUT
          │                          ↖ poll approvals and config history
          └──> controller.audit, reports and on-call queries
```

Each chunk commits counts, uploads, administrative events and its cursor together. The counts are keyed by workflow, hour, version, cohort, prompt, caller ID, voice and welcome. SQLite also stores experiment state, validation receipts and the outbound proposal ID. On restart we fetch chunks beyond the committed cursor, look for writes that may already have happened and continue from the simulator's current clock. SQLite uses WAL with full synchronous writes, and an OS lock excludes a second process using the same database.

The controller uses Python's standard library and the starter's HTTPX dependency. Use a local disk for SQLite. The simulator, grading and crash driver are separate from the controller process.

## 5. The learning loop

- **Cohorts.** Decisions for allocations use the default cohort and an exact config version. Start an experiment only after 500 baseline connections and only when at least three simulated days remain. Prompt monitoring uses the workflow because a prompt applies everywhere. We skip default allocation changes when an explicit cohort would inherit the change.
- **Design.** On engagement-primary workflows, give an eligible challenger 45% and leave 55% on the incumbent. Test one dimension at a time. After an applied voice test, consider a welcome test before another voice. Candidate order is deterministic and each challenger is tried at most once per dimension in a workflow. This holds the other dimensions steady for a comparison and leaves voice-by-welcome interactions unestimated.
- **Winner.** The readout runs every round once each arm has 24 hours, 3,000 dials and 700 connections. It treats the lift as normal, using the 1.5 variance factor, and computes the expected loss of each choice: the primary-KPI points we expect to give up by picking that arm if it turns out to be the worse one. Promote when the lift is positive, the challenger's expected loss is at most 0.25 points, and the posterior chance of the guardrail dropping past its margin is under 10%. Restore control when the lift is negative and control's expected loss is at most 0.25 points. A trial still undecided at 96 hours restores control. The decision is stored when it is made, so a slow approval cannot reopen it. Only a harm stop can.
- **Why expected loss.** My first version took one fixed read and wanted a +1 point lower bound at z=2.807. With about 800 connections per arm that needs an observed gap near 9 points, while the grader reports effects of 1 to 2 points. It never promoted. Every public trial ended by restoring control, including two that the grader marked as better. A fixed test that can detect 2 points would need 10,000 to 15,000 connections per arm, which is about a month at this volume. [tools/readout_simulation.py](tools/readout_simulation.py) runs the real `readout` on synthetic trials at nw_renewal volume ([output](reports/readout_simulation.txt)):

  | true engagement lift | old rule promotes | new rule promotes | new rule restores |
  |---|---:|---:|---:|
  | -2 points | 0.0% | 4.0% | 96.0% |
  | -1 point | 0.0% | 13.1% | 86.9% |
  | 0 | 0.0% | 25.2% | 74.8% |
  | +1 point | 0.0% | 45.7% | 54.3% |
  | +2 points | 0.1% | 65.1% | 34.9% |
  | +2 points with pickup -3 | 0.0% | 0.6% | 99.4% |

  Expected loss bounds the cost of a wrong pick. It does not control a false-positive rate: with no true effect it promotes a quarter of the time, which costs nothing in expectation but uses an approval. A wrong promotion still leaves 20% on control, and the harm stop below watches it. Undecided trials are the price. A challenger with no effect runs a median 86 hours, which on an 8-day scenario leaves room for about two trials per workflow. A 72-hour deadline would save about 17 hours per null trial and drop power at +2 points from 66% to 50%, so I kept 96.
- **Decay.** An 80/20 promoted split keeps a live control. Look at up to 48 hours of promoted traffic, with at least 350 dials and 120 connections in each arm. An upper bound at z=4 that clears a 1.5-point engagement loss or breaks the guardrail triggers a rollback request. The same harm stop applies during exploration. Repeated safety looks are approximate and are not efficacy looks. Small effects and low-volume arms can take days to show up. The public runs promoted three variants and none decayed, so rollback has only run in unit tests.
- **Caller ID.** Compare active caller IDs within the current default cohort and version over eight hours. Require 180 dials on each compared arm and a pickup lower bound above 2.5 points. The previous week supplies a health reference, and a 4.5-point historical drop classifies an incident. Rotate toward a stronger observed ID, bound the move by policy, and leave about 5% to measure the weak ID. A weaker ID may see fewer than 180 calls after rotation, which delays a further step. Schedule and per-person call time are out of scope.
- **Guardrail.** Pickup uses dials as its denominator. Engagement uses connections. Promotion requires a separate noninferiority check at z=1.645. For caller rotation, check conditional engagement even when pickup is the declared guardrail. In an incident with too few pickups for arm-level noninferiority, use a smaller move and bound engagement risk for the affected fraction. Verify the post-change mix separately. Concluded leads per upload is a scenario outcome reported by the grader.

## 6. Governance

```text
 intent ──> pending ──> approved ──> applied
    │           │          ├──> stale / lapsed / withheld
    │           └──> rejected / expired
    └──> policy-permitted caller PUT ──> applied / stale / API rejection
```

The complete config is copied from the current version and only the intended field changes. Approval writes are paced by workflow hours, minimum response latency, TTL and the rolling 24-hour limit. Kestrel gets the stricter limit described above. The loop leaves two hours between requests and waits 12 hours after a human rejection. It prioritises one pending action at a time to keep unrelated changes out of the same request. While a request is open, the simulator advances in 15-minute increments. Before applying, re-read the base version, and withhold an experiment or promotion if new prompt-incident evidence is present. A conflict never sends a stale apply. Re-evaluation starts from the new live config and can produce a fresh ID. At scenario end, reconcile accepted results and do not issue new mutations.

Only caller ID is eligible for auto-apply, and only if each effective cohort distribution is within the live policy's total-variation limit. An approved config is applied via its approval ID. A supervisor edit invalidates the experiment and pauses elective experiments for 24 hours. No old config is restored over the supervisor's edit. A version change by the controller for caller or prompt work starts a fresh experiment measurement window if a trial is still live.

Reach includes campaign uploads within the cadence horizon and the next daily batch. For an allocation change with existing cohorts, scale it by the observed default dial share. This may overstate remaining reachable people and can count returning people again across campaigns. The caller dry run reweights measured caller rates. The experiment dry run shows historical support and leaves the challenger estimate unknown if it has never run. The prompt dry run shows separate validation and prior observed counts. Impact is expressed as a conservative fractional improvement or safety gap for the proposed action. It is zero for new experiments, and the scores across action types have not been calibrated against each other.

## 7. Incidents

The prompt detector looks for 180+ connections and at least 4.5% flags in six hours, or 500+ connections and at least 4.0% flags in 24 hours. The lower excess bound over a supported historical reference must be at least 0.5 or 0.7 points, respectively, at z=3.09. The per-look null tail before the excess and rate gates is about 0.1% under the assumed model. The rolling windows overlap, the reference is selected from history, and flags are imperfect. The true false-alarm rate needs live calibration. Review flag calibration and measure false alarms on shadow traffic before paging on the detector alone.

One LLM call costs three credits. A validation run tests 400 conversations and costs four credits. Candidate ordering favors a previously safe prompt and avoids strict catalog entries when a comparably supported option exists. Candidates with evidence of a guardrail drop are skipped. A candidate must meet the workflow's validation floor and receive approval. The credit reserve is 12% of initial credits, bounded between four and 16. The controller does not spend into the reserve. Live verification compares flags, pickup and engagement separately with the observed pre-change period. The before/after comparison is observational.

| Public_02 incident | Observed timeline (IST, simulated) |
|---|---|
| Kestrel caller ID flagged, D2 10:00 | First controller rotation at D2 14:00. Flagged-ID share was 30.6% on D2, 10.4% on D3, and 4.6% on D7. |
| Kestrel supervisor prompt edit, D3 11:30 | P2 ran at about 4.5% flags, just under the six-hour floor, so no six-hour window fired. The 24-hour window fired at D4 12:00 with 47 flags in 965 connections against 94 in 6,668 in the reference. P1 passed 98.5% of 400 validations. Approval `apr_00004` was decided at 12:45 and v6 applied at 13:00, 1,530 minutes after the edit. By 17:00 there were four flags in 300 post-change connections and no detected pickup guardrail regression. An earlier run of the same scenario saw 7% flags and fixed it in 315 minutes. |
| Northwind renewal supervisor edit, D5 15:00 | The controller preserved supervisor v4, dropped its promoted V2 split from tracking and paused elective experiments for 24 hours. The stale-approval test separately exercises an approval crossing a supervisor version change. |

## 8. Scale

See [public_03_load.md](reports/public_03_load.md) for the machine limits, ingest rate, simulated and wall-clock decision lag, peak RSS, and per-day timing. The simulator's history generation is outside controller startup timing. The history download and rollup are included as a separate line.

At 10×, JSON decoding and one serial HTTP chunk stream are likely to saturate before the indexed SQLite rollup lookups. An hourly partition per workflow avoids fetching raw calls for routine decisions. For production, partition the event feed by tenant and workflow and preserve order within each partition. Run one decision owner per workflow behind a lease. Keep policy, proposal idempotency and the budget ledger in Postgres, with tenant-level quotas and reserved incident capacity. Measure hot-workflow skew before picking partition counts.

## 9. Reliability

Run the checks from the repo root.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python tools/crash_recovery.py --run-dir runs/crash-demo
```

To regenerate a grade, choose a scenario and fresh run directories. Run the server in one terminal and the controller and grader in another.

```sh
.venv/bin/python -m sim baseline --scenario scenarios/public_02_incidents.yaml --run-dir runs/base02
.venv/bin/python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/mine02
```

```sh
CONTROLLER_DB=runs/controller02.sqlite3 ./run.sh http://127.0.0.1:8700
.venv/bin/python -m sim grade --run runs/mine02 --baseline runs/base02 --out reports/public_02.md
```

Use `public_01_dev.yaml` and a separate set of paths for public_01. The approver is simulated, so approval IDs and outcomes may vary between runs.

The [crash log](reports/crash_recovery.txt) records a kill immediately after the approval creation response, then another immediately after a successful apply response. The durable IDs reconciled with the original world. Committed counts and approval state survived, and the SQLite integrity check passed. A partial chunk is discarded and re-fetched. For an ambiguous paid call the intent is retained and that exact operation is not retried, because the credit endpoints have no idempotency key or receipt lookup. The response can be lost and a validation may need human follow-up.

GET failures other than 429 and 5xx fail visibly. Transport errors, 429 and 5xx trigger bounded backoff and reconciliation. For approval writes, look up the durable proposal ID before posting again. For approved or auto-applied writes, consult approval or version history before deciding whether another request is needed. A 409 stale base is recorded, a 410 at apply is a lapse, and a definitive 4xx response is recorded as a failed proposal. If the simulator itself restarts, start a new run and use a new database.

## 10. Audit & observability

```sh
.venv/bin/python -m controller.audit runs/controller02.sqlite3 ks_cancel \
  --since 2027-01-08T12:00 --limit 6
```

The [captured output](reports/audit_public_02.txt) gives the diagnosis, evidence and approval ID, the applied config version, and the live QA check. A compact reading of those rows follows.

```text
12:00  prompt_incident       P2, 47/965 flags over 24 h; historical reference 94/6668
12:00  proposal_intent       P2 -> P1, validation val_00001, pass rate 0.985
12:45  approval_decided      apr_00004 approved
13:00  proposal_applied      prompt_fix, version 6, approval apr_00004
13:00  config_changed        controller_approved, prompt_version
17:00  change_verification   P1, 4/300 flags; no detected pickup guardrail regression
```

The W2 trial on this workflow waited until 17:00 to start. A new trial bumps the config version, and that would have cut the prompt check short.

The audit uses the simulator's approval identifier because there is no approver-name field. For on-call, page on a growing ingest backlog during dialling, an unreconciled apply outcome, or a high-confidence active prompt incident blocked on credits or approval. Check the chunk cursor, the proposal ID and live approval state, or the recent flag counts and reserve, respectively. Ordinary declines, stale requests caused by supervisor edits, and underpowered experiments belong in a digest. Checkpoints record credits and ingestion progress. Query `audit` by timestamp and kind for decisions per hour and `rounds` for measured processing times. Alert delivery remains a production integration.

## 11. Results

### public_01_dev

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.342 | +0.2% | 0.246 | +0.6% | 0.490 | -0.4% | 4% | 69 (57) |
| nw_kyc | 0.367 | +0.0% | 0.243 | +0.6% | 0.594 | -0.6% | 0% | 16 (21) |
| nw_renewal | 0.413 | -0.7% | 0.261 | -1.1% | 0.544 | +0.5% | 0% | 49 (54) |
| ALL | 0.371 | -0.2% | 0.251 | -0.0% | 0.529 | -0.1% | 2% | 134 (132) |

Six changes applied: four neutral, two beneficial and none harmful by the grader. Both workflows started with a V2 voice trial that had no real effect. Kestrel's ended at D3 when control's expected loss fell under the tolerance. Northwind renewal's ran to the 96-hour deadline, and the approver rejected the first request to end it, so it did not close until D5. Kestrel then tested W2 and promoted it to 80% at D7. That promotion was beneficial but came too late to move the eight-day totals. My first version of the readout scored +0.8% here with two harmful changes, both restores of a welcome message the grader showed was better. The new readout traded that for slower null trials, and the outcome change is inside the noise described below.

### public_02_incidents

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.288 | +22.4% | 0.203 | +12.1% | 0.497 | +6.3% | 33% | 107 (348) |
| nw_kyc | 0.363 | -2.9% | 0.237 | +1.2% | 0.585 | -3.9% | 0% | 20 (29) |
| nw_renewal | 0.427 | -1.3% | 0.260 | -1.0% | 0.552 | -0.4% | 8% | 58 (54) |
| ALL | 0.351 | +6.0% | 0.229 | +4.4% | 0.536 | +0.7% | 17% | 185 (431) |

Ten changes applied: seven beneficial, three neutral and none harmful. The beneficial changes were three caller rotations, the prompt fix, the start of Northwind's V2 trial, and Kestrel's W2 trial and its promotion. Northwind promoted V2 at D3, graded neutral at +0.010, just under the grader's cut. The D5 supervisor edit then ended that tracking. The first version applied thirteen changes here with three harmful: two restores after inconclusive trials and a voice test after the supervisor edit. The grader's labels use hidden truth that the controller did not have at decision time.

Kestrel's conclusion rate rose 22.4%, most of it from the caller rotation and the prompt fix. Northwind KYC, which the controller never changes, came out at -0.6%, +2.3% and -2.9% across three runs of this scenario, because controller actions elsewhere shift the shared random draws. The overall figure moved from +6.8% to +6.0% between versions, and almost all of that is KYC. Differences of a few percent between controller versions are inside that spread.

The remaining limit is throughput. One dimension per trial leaves room for about two trials per workflow in eight days. The simulator samples voice and welcome independently on each dial, so running both contrasts in one trial would roughly double that, at little cost in power if the two do not interact strongly. The public reports do not show winner decay. The unit suite covers promotion, a failed pickup guardrail, rollback and the undecided-until-deadline path with constructed rollup counts.

## 12. Trade-offs & rejected alternatives

| Option | Why considered | Choice |
|---|---|---|
| Raw event warehouse | Customer-level queries and clustered uncertainty | Hourly aggregate plus administrative event audit keeps memory and storage bounded in the assignment |
| One multi-arm factorial trial | Could identify voice/welcome interactions | One dimension and one challenger per trial gives an interpretable contrast with less traffic |
| One fixed read with a +1 point lower bound | Simple false-positive story | It could not see 1 to 2 point effects inside the horizon and ended every trial by restoring control. Replaced with an expected-loss readout and a 96-hour deadline |
| Auto-apply customer-facing changes when allowed | Removes approval delays | Take the human path for welcome, voice and prompt changes |
| Per-lead hour preferences | Could improve pickup for returning callers | Cut until there is a controlled dispatch experiment and comparable attempt data |
| New infrastructure | Allows several controller replicas | SQLite keeps this single-host run operationally small. A production deployment can reuse Postgres |

## 13. Known weaknesses

The default cohort can hide meaningful feature slices, and a fixed variance multiplier is no replacement for clustering by person. The readout promotes about a quarter of challengers with no effect and 4% of those two points worse. The retained control and the harm stop are the backstop. A trial with no effect runs about 86 hours. The six-hour prompt detector misses flag rates near 4.5%, which cost a day on public_02. A change-point check on a prompt the supervisor just shipped would catch that sooner. When a supervisor edit invalidates a running trial, the split it left in the config stays live and untracked. On public_02 Kestrel kept V2 at 45% for the rest of the run. The caller comparison cannot rank unused IDs. The prompt fix verifier can identify a possible trade-off, but cannot estimate causality from a pre/post comparison. Hidden scenarios and promoted-winner decay were not observed in the public evidence. Per-workflow rate limits do not coordinate a shared approver across workflows. A long approval decision can delay responding to a newer incident on the same workflow. Reach is an estimate. SQLite does not provide cross-host failover.

## 14. If this went to production at Formi next month

1. Days 1–2. Run in shadow and compare rollups and event freshness with dialler dashboards. Verify tenant isolation and identify owners for workflow policy.
2. Days 3–5. Validate flag calibration and review real, consented samples with QA and Compliance. Add named approval identity, campaign-level visibility and the on-call runbook.
3. Days 6–8. Enable one low-risk workflow through the approval path. Exercise expiry, cancellation, rejected proposals and a crash during apply while operators follow the timeline.
4. Days 9–10. Review guardrails and shadow false alarms before raising traffic or enabling bounded caller auto-apply. Agree on a rollback owner and reserve budget per tenant.

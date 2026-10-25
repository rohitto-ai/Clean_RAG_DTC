# Phase 10.3 — FastAPI service, `why` blocks and an audit log

_2026-10-25 · branch `phase10-demo` · extends `app.py` · **production retrieval and gate unchanged** · the symptom path uses the production default only; lexicon v2 is NOT adopted_

## Objective

Give the demo a service surface: the telematics pipeline, the symptom path, a replay driver for
a live-looking demo, an explanation of every answer, and an audit trail of every request.

## Headline

| item | result |
|---|---|
| Startup (models + indexes loaded **once**) | **6.0 s**, reported by `/health` as `startup_seconds` |
| Endpoints | 13, plus static files at `/` |
| `src/test_api.py` | **56/56** |
| Latency p50 / p95 (excluding startup) | `/vehicle` 1.9 / 2.3 ms · `/symptom` 31.5 / 35.8 ms · `/fleet` 63.5 / 74.0 ms · `/health` 1.9 / 2.1 ms · `/verify-code` 1.4 / 2.0 ms · `/audit` 2.0 / 2.8 ms |
| Suite | **44 passed / 1 xfail / 0 failed** |
| Determinism `--defaults` | **`ffff9bc707d8754d`** |

Startup loads MiniLM, Chroma, the BM25 corpus, 311 records, the SPN/FMI dictionary and the
1,000-row demo log. The telematics `Pipeline` is constructed with the **same** `Retriever`
instance, so there is exactly one copy of the embedder and vector store in the process.

## Endpoints

| method | path | returns |
|---|---|---|
| GET | `/health` | status, versions (embedder, index, gate, git commit), determinism hash, record/vector/BM25/dictionary/log counts, `startup_seconds`, replay flag |
| GET | `/scenarios` | `data/demo/scenarios.json` — 14 website presets |
| GET | `/fleet?severity=&region=&outcome=` | `telematics.fleet_summary()` with filters |
| GET | `/vehicle/{vehicle_id_or_registration}` | `telematics.vehicle_report()`, **404** if unknown |
| POST | `/verify-code` | `{vehicle_id, reported_code}` → MATCH / MISMATCH (+ possible transposition), never auto-replaced |
| POST | `/symptom` | `{query, summary}` → Phase 9.1 `advise()` top-3 + illustrative cost/TAT; refusals returned as refusals |
| GET | `/audit?limit=50` | the latest audit entries |
| POST | `/replay/start` · `/replay/stop` · `/replay/reset` | drive the live store |
| GET | `/replay/status` | rows replayed, progress, last event date |
| POST | `/query` · `/diagnose` · `/advise` | the Phase 7 / 9.1 surfaces, unchanged |
| GET | `/` | static files from `web/` |

`StaticFiles` is mounted at `/` **after** every API route, so the API paths keep priority and
no CORS is needed — the UI and the API share one origin and one port.

## The `why` block

Every response carries `why` with a fixed shape:

| key | content |
|---|---|
| `route` | which path was taken (`vehicle_report`, `symptom`, `refused`, `fleet_summary`, …) |
| `ladder` | the telematics rungs that fired, per episode (R0 validate/de-dup, R1 exact, R1b ambiguous, R2 fallback, R3 unmapped) |
| `retrieval` | whether similarity search was used at all, and the per-result dense/BM25/RRF ranks when it was |
| `gate` | whether gate v2 was applied, its decision, reasons and signals |
| `citations` | `{code_full, manual_page, citation}` for every rendered fix block |
| `severity_reasons` | the exact reasons that produced each episode's severity |
| `steps` | every processing step, each labelled **RULE** or **AI** |

The RULE/AI labelling is the honest part: on the telematics path **every** step is RULE. Only
`/symptom` with `summary: true` adds a single AI step, labelled
*"one-sentence summary per code (Qwen2.5-0.5B) — phrasing only, never a repair step"*. A test
asserts that the telematics path contains no AI step and that `/symptom` without `summary`
contains none either.

Cost and TAT are always under their own key `illustrative_cost_tat`, labelled
**"Illustrative - owned by another team; not from the manual"**, never mixed into the manual
content. A test asserts the old `cost_tat` key is gone from API responses.

## Audit log

One JSON line per request to `data/demo/audit.jsonl` (**gitignored** — it is a runtime
artifact), rotated to `audit.jsonl.1` at 5 MB. Fields: `timestamp`, `endpoint`, `request`
(body or params), `route`, `codes`, `decision`, `latency_ms`, `git_commit`,
`determinism_hash`, `replay_active`, plus per-endpoint extras.

`decision` uses a closed vocabulary, asserted by test:
`answer` · `refuse` · `clarify` · `candidates` · `mismatch` · `match` · `not_found` ·
`no_code_detected`. A vehicle with several episodes records the comma-joined set.

Writing the audit line can never fail a request: the writer swallows `OSError` and returns.

## Replay driver

`POST /replay/start {rows_per_tick, tick_seconds}` sorts the demo log by `Event_Date` and feeds
rows into an in-memory live store on a daemon thread. **While a replay is active, `/fleet` and
`/vehicle` see only the rows replayed so far** — tested exactly: with the replay halted,
`/fleet`'s `rows_in_scope` equals `/replay/status`'s `rows_replayed`, and is below 1,000.
`/replay/stop` halts it and keeps what has arrived; `/replay/reset` restores the full log. A
second `start` while running returns **409**, as does `stop` with no replay.

## curl examples

```bash
# start the service (see "Exposing port 8000" below for the Codespace)
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000

BASE=http://127.0.0.1:8000

curl -s $BASE/health | jq '{status, startup_seconds, determinism_hash, counts}'
curl -s $BASE/scenarios | jq '.scenarios | keys'

# fleet, then filtered
curl -s $BASE/fleet | jq '{vehicles, episodes, by_outcome, by_worst_severity}'
curl -s "$BASE/fleet?severity=CRITICAL" | jq '.filters, (.per_vehicle | keys | length)'
curl -s "$BASE/fleet?region=North&outcome=AMBIGUOUS_MAPPING_CANDIDATES" | jq '.filters'

# one vehicle: episodes, why block, illustrative cost
curl -s $BASE/vehicle/DEMO-MAT-0001 | jq '{worst_severity, outcome_counts}'
curl -s $BASE/vehicle/DEMO-MAT-0001 | jq '.why.citations, .why.steps'
curl -s $BASE/vehicle/DEMO-MAT-0001 | jq '.episodes[0].illustrative_cost_tat'
curl -s $BASE/vehicle/DM34TN3620   | jq '.vehicle_id'          # by registration
curl -s -o /dev/null -w '%{http_code}\n' $BASE/vehicle/DEMO-MAT-9999   # 404

# the ambiguous key: candidates, never auto-advised
curl -s $BASE/vehicle/DEMO-MAT-0004 | jq '.episodes[0] | {outcome, candidates, fix_blocks}'

# a technician's code vs the telemetry
curl -s -X POST $BASE/verify-code -H 'content-type: application/json' \
  -d '{"vehicle_id":"DEMO-MAT-0011","reported_code":"P0100-00"}' \
  | jq '{status, possible_transposition, auto_replaced, message}'

# symptom search (production config), and a refusal
curl -s -X POST $BASE/symptom -H 'content-type: application/json' \
  -d '{"query":"rail pressure sensor short to ground"}' \
  | jq '{mode, config, codes: .why.codes}'
curl -s -X POST $BASE/symptom -H 'content-type: application/json' \
  -d '{"query":"what is the capital of France"}' | jq '{mode, why: .why.gate}'

# replay
curl -s -X POST $BASE/replay/start -H 'content-type: application/json' \
  -d '{"rows_per_tick":40,"tick_seconds":1}' | jq '{started, rows_total}'
curl -s $BASE/replay/status | jq '{rows_replayed, progress, last_event_date}'
curl -s $BASE/fleet | jq '{replay_active, rows_in_scope, vehicles}'
curl -s -X POST $BASE/replay/stop  | jq '{stopped, rows_replayed}'
curl -s -X POST $BASE/replay/reset | jq '{reset, rows_in_scope}'

# audit trail
curl -s "$BASE/audit?limit=5" | jq '.entries[] | {endpoint, decision, latency_ms, codes}'
```

## Exposing port 8000 in the Codespace

1. **Bind to all interfaces**, or the forwarded port will refuse the connection:
   `uvicorn app:app --host 0.0.0.0 --port 8000`.
2. VS Code auto-forwards 8000 and shows a toast. Otherwise open the **Ports** panel
   (`Ctrl+Shift+P` → *Ports: Focus on Ports View*), find 8000, and use *Open in Browser*.
3. **Visibility.** The port is **Private** by default — only you, signed in to GitHub, can
   reach it. To demo to someone else, right-click the port → *Port Visibility* → **Public**,
   which produces a URL anyone with the link can open. From the CLI:
   `gh codespace ports visibility 8000:public -c $CODESPACE_NAME`.
   **Set it back to Private after the demo:** a public port exposes the whole API, including
   `/audit`, to anyone with the link.
4. The URL is `https://$CODESPACE_NAME-8000.app.github.dev/`. It serves the placeholder UI at
   `/` and the API on the same origin, so a browser page needs no CORS configuration.
5. **Keep-alive.** A Codespace suspends after its idle timeout (30 min default) and *idle means
   no terminal or editor activity* — inbound HTTP alone may not count. For an unattended demo,
   raise the timeout in Settings → Codespaces → *Default idle timeout*, keep the terminal
   running uvicorn in the foreground, and re-open the Codespace window if it has suspended.
   After a rebuild, `data/demo/` is committed but `index/` and the model are not: re-run
   `./run.sh` once (it rebuilds the index and downloads the model) before starting the service.

## Tests

`src/test_api.py` — **61/61**, via `fastapi.testclient.TestClient` (56 at 10.3; the placeholder assertion was replaced in 10.4 by five stronger static checks):

- `/health` (versions, hash, counts, `startup_seconds`, lexicon-v2-not-adopted), `/scenarios`;
- `/fleet` plus each filter, and **422** for an unknown severity or outcome;
- `/vehicle` ADVISORY with citations and severity reasons, the ambiguous outcome, the refusal
  and clarification outcomes, lookup by registration, and **404** for an unknown vehicle *and*
  an unknown registration;
- `/verify-code` for both scripted transpositions (MISMATCH + possible transposition,
  `auto_replaced: false`), the MATCH case, and **400** on empty fields;
- `/symptom` top-3 with ranks and citations, the out-of-scope **refusal** with its reason, the
  base-code **clarification**, and **400** on an empty query;
- replay start → progress → 409 on double start → stop → no rows after stop → `/fleet` sees
  exactly the replayed rows → reset → 409 on stop with no replay;
- audit: coverage of every endpoint, the required fields, the closed decision vocabulary, the
  refusal and mismatch entries, the hash and commit on every line, **exactly one new line per
  request**, and that the file is gitignored;
- static: `/` serves the UI (four tabs, synthetic-data footer, no external requests), unknown static path **404**;
- a `why` block of the right shape on every response, with every step labelled RULE or AI.

Latency is measured in the same run, bucketed per endpoint (`/vehicle/{id}` is one bucket, not
one per vehicle), and written to `data/experiments/10_3/api_latency.json`.

`/fleet` is the slowest endpoint at ~64 ms because it re-runs the ladder for all 199 vehicles on
every call; nothing is cached between requests beyond per-process code resolution.

## Files

| file | change |
|---|---|
| `app.py` | extended: startup loads once, 10 new endpoints, `why` builders, audit, replay, static mount |
| `web/index.html` | placeholder at 10.3; **replaced by the real UI in Phase 10.4** |
| `src/test_api.py` | 56 tests + latency measurement (new) |
| `.gitignore` | `data/demo/audit.jsonl`, `.jsonl.1` |
| `data/experiments/10_3/api_latency.json` | measured latency |

## Limitations

1. **Single process, in-memory state.** Diagnosis sessions, the replay store and the live
   fleet view are per-process. Two workers would not share them, so run one.
2. **The replay thread is not transactional.** `/fleet` taken mid-tick sees whatever has been
   appended; the test stops the replay before asserting an exact count for that reason.
3. **`/fleet` has no caching** — ~64 ms per call for 199 vehicles. Fine for a demo, wrong for a
   real fleet; it would need an incremental aggregate.
4. **No authentication.** Anything that can reach the port can read every endpoint, including
   `/audit`. That is why the Codespace port must go back to Private after a demo.
5. **The audit log records request bodies verbatim.** On synthetic data that is harmless; with
   real telematics it would hold vehicle identifiers and need the same handling as the feed.
6. **Cost and TAT remain illustrative** and owned by another team.
7. **Lexicon v2 is deliberately unreachable** from this service: `/symptom` uses the adopted
   production configuration only, so the service cannot silently serve an unadopted config.

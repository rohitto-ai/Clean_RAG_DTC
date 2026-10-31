# Phase 13.1 — conversational pre-filter for non-diagnostic input

_Branch `phase10-demo`. Retrieval, the relevance gate, the indexes and the records are
**unchanged**; this phase only decides whether to call them._

## Objective

The demo takes free text, so people type things that are not fault reports: "hi", "thanks", and —
the one that matters — "no issues, the truck is running fine". Before this phase all three went
into the router and came back with a ranked list of fault codes and fix blocks. For a greeting that
is merely silly. For a vehicle someone has just declared **healthy** it is the worst failure mode
this project has: a confident, cited answer about a fault that nobody reported.

The gate cannot fix this. Gate v2 refuses on *lexical and dense distance* from the manual, and
"no issues, the truck is running fine" is full of ordinary vehicle vocabulary — it sits comfortably
inside the corpus. This is the same structural limit already recorded for the no-DTC-match rows
(0/19 declined): the gate cannot refuse an in-domain sentence. A separate, earlier decision is
needed.

## Method

`src/conversational.py` exposes `classify(query) -> GREETING | THANKS | NO_PROBLEM | None` and
`respond(query)`. It runs **before routing** on the two free-text paths, `/symptom` (the web UI's
Service query tab) and `/query` (the Phase 7 surface). `None` means "not conversational — run the
normal pipeline".

**GREETING / THANKS — whole-query rule.** Every token must be a greeting, a thanks/acknowledgement
or pure filler ("a", "lot", "please"). One content word and the filter stands down, which is what
makes `hi, engine knocking at full load` a normal symptom query. Fixed multi-word pleasantries
("good morning", "thank you") are folded to single tokens first.

**NO_PROBLEM — healthy phrase AND no problem signal.** The query must match an explicit healthy
phrase (`no issue(s)`, `no problem(s)`, `nothing wrong`, `all good`, `working fine/normally/
properly`, `running fine/smoothly/normally`, `healthy`, `starts fine`, `no complaint`, `no warning`,
…) and contain **no** problem signal of any kind:

| signal | examples |
|---|---|
| fault code / telemetry | `P`/`U`/`B`/`C` + 4 hex, `SPN`, `FMI` |
| contrast word | but, except, however, although, though, sometimes, occasionally, only when, apart from |
| negated action | not, won't, doesn't, didn't, can't, fails, unable, refuses, never |
| symptom or fault term | lamp, light, warning, smoke, noise, knock, rattle, whine, squeal, leak, smell, stall, cut out, misfire, vibration, overheat, hot, power loss, weak, slow, hard, error, fault, code, alarm, derate, limp |

**Healthy phrases are masked out before the problem scan.** This is the one non-obvious mechanic
and the rule turns on it: `no warning` is a healthy phrase that *contains* the symptom term
"warning", and `no complaint` contains a negation. Scanning the raw text would reject every healthy
statement; scanning the masked remainder rejects only statements that say something **else** as
well. So `no warning` passes, while `no warning light but loses power` is rejected twice over — by
the leftover "light" and by "but".

**Replies** are three fixed strings, the decision label is `conversational`, and the `why` block's
steps are all **RULE**:

```
conversational pre-filter: GREETING - whole-query rule, applied BEFORE routing   [RULE]
fixed reply returned; router, retriever, gate and manual are never consulted     [RULE]
```

Each reply is written to the audit log like any other decision, with the label and the reasons that
fired.

## Key decisions

- **Fail closed.** A false positive swallows a real fault report; a false negative merely sends
  "hi" through retrieval and earns a refusal. The two are not symmetric, so every rule returns
  `None` when unsure, and the test file has **31 must-not-fire** cases against **26 should-fire**.
- **No model, by construction.** Every decision is a regex or a set membership test and every reply
  is a fixed string, so the filter cannot invent a diagnosis. A test asserts that importing the
  module pulls in neither `llama_cpp` nor `sentence_transformers`.
- **In front of routing, not inside the gate.** Touching the gate would change production
  behaviour on real queries and break the determinism hash. The pre-filter is additive and leaves
  retrieval byte-identical.
- **Precedence between the two rules is pinned.** Bare "all ok" is matched by the pleasantry rule
  (which runs first) and so answers THANKS, while "all ok with the truck" carries a content word and
  reaches NO_PROBLEM. Both replies are non-diagnostic, so nothing unsafe turns on the order — it is
  fixed in a test so the behaviour is defined rather than incidental.
- **Out-of-scope questions are left alone.** "How do I change a tyre" is the *gate's* job, and it
  already refuses it correctly. The pre-filter deliberately does not compete.

## Results

### Tests — `src/test_conversational.py`, 67/67

26 should-fire (including `hi`, `thanks a lot`, `all good, running fine`, `no issue vehicle is
cranking and healthy`, and `no warning`) and 31 must-not-fire, of which the dangerous class is a
healthy phrase with a fault attached:

| query | classify() | why it must not fire |
|---|---|---|
| `starts fine but black smoke under load` | `None` | contrast + symptom term |
| `no issue except a squeal on cold start` | `None` | contrast + symptom term |
| `healthy at idle, weak when climbing` | `None` | symptom term |
| `no warning light but loses power` | `None` | leftover "light" + contrast |
| `no issues however it will not start when cold` | `None` | contrast + negation |
| `no issue with SPN 520210` | `None` | telemetry reference |
| `hi, engine knocking at full load` | `None` | not whole-query pleasantry |
| `thanks, but the lamp came back` | `None` | not whole-query pleasantry |
| `vehicle not cranking` | `None` | negation, and no healthy phrase at all |
| `P0192-00` | `None` | code pattern |

### Safety measurement — POST-HOC, counts only

`scripts/measure_13_1.py` runs `classify()` alone — no retriever, no index, no answer, no metric —
over every row of all four sets and counts what it *would* have intercepted:

| set | rows | intercepted | by mode |
|---|---|---|---|
| DEV (gold_v2) | 34 | **0** | symptom 0/12, near-dup 0/7, exact 0/6, group 0/3, out-of-scope 0/6 |
| TEST (gold_v2, spent) | 36 | **0** | symptom 0/13, near-dup 0/7, exact 0/6, group 0/4, out-of-scope 0/6 |
| independent (spent) | 60 | **0** | symptom 0/41, no_dtc 0/19 |
| R2 colleague (spent) | 20 | **0** | symptom 0/15, no_dtc 0/4, inconclusive 0/1 |

**0 of 150 rows intercepted**, as required, so no rule needed changing. Two of those columns are
worth naming: the **23 `no_dtc` rows** describe real complaints with no matching code (leaks,
noises), and the filter correctly leaves every one of them alone — it fires on "the vehicle is
healthy", never on "something is wrong but I cannot find a code". The **12 out-of-scope rows** are
likewise untouched and still reach the gate.

This measurement is **post-hoc and counts only**. It cannot show the filter is safe on language
nobody has written yet; it shows only that it intercepts nothing in the corpora this project holds.
R2 lives on the 11.x/12.x branch and was read read-only with `git show`, not copied onto this
branch.

### Demo

Three presets added to the Service query menu (`hi`, `thanks a lot`,
`no issue, the vehicle is running fine`), rendered as a RULE-tagged notice that says plainly that
nothing was retrieved. `./run.sh demo --check` extended from 43 to **49 checks** — the three
presets (each asserting `mode == "conversational"`, no results, no citations, `retrieval.used ==
false`, and every `why` step labelled RULE), two negative cases that must **not** be intercepted,
and one `/query` greeting — and reports **DEMO CHECK PASSED**. The audit assertion now requires a
`conversational` decision to appear alongside `refuse` and `mismatch`.

### Unchanged

Suite `src/smoke_index.py` **44 passed / 1 xfail / 0 failed**; determinism
`--defaults --index-dir index` **`ffff9bc707d8754d`**; DEV symptom MRR 0.7111, overall 0.8613, gate
6/6 and 28/28.

## Files

| file | role |
|---|---|
| `src/conversational.py` | the rules, the three fixed replies, `classify()` / `respond()` |
| `src/test_conversational.py` | 67 cases, 31 of them must-not-fire |
| `scripts/measure_13_1.py` | the post-hoc interception count over all four sets |
| `data/experiments/13_1/prefilter_safety.json` | its output, including per-mode counts |
| `app.py` | the pre-filter in front of `/symptom` and `/query`, `why_conversational()`, audit |
| `web/app.js` | the conversational branch in the Service query renderer + 3 presets |
| `scripts/demo_smoke.py` | 6 new checks (3 presets, 2 negatives, 1 `/query`) |

## Limitations

1. **Fixed vocabulary, English only.** "all sorted", "runs sweet", "chalu hai", a typo'd "thanx"
   or Hinglish phrasing all return `None` and fall through to retrieval. That is the safe
   direction, but it means the filter helps less than its hit-rate on this corpus suggests.
2. **No semantics.** `is the vehicle healthy when the lamp is on` is a question *about* a fault and
   is correctly not intercepted — but only because "lamp" is on the term list, not because the
   filter understood the sentence. A healthy-sounding sentence whose fault word is absent from the
   list would be intercepted.
3. **The term list is finite and hand-written.** It was written from the manual's own vocabulary
   plus common workshop words, not derived from data, and it is the single point of failure for
   NO_PROBLEM. A symptom word that is missing from it (say "judder" or "hunting") would let a fault
   report through as healthy if it were phrased alongside a healthy clause.
4. **0/150 is not a safety proof.** None of these sets contains a conversational row — they were
   written as diagnostic sets — so the measurement shows the absence of harm on fault data, not
   that the filter fires correctly on real pleasantries at scale.
5. **Not applied to `/advise` or `/diagnose`.** Both are reached with a query the caller has
   already chosen to diagnose, and `/diagnose` is a session flow; extending the filter there would
   need its own thought about session state.
6. **The healthy reply is advice-free by design.** It does not suggest checks or a service
   interval, because the manual contains no such content and the design law forbids inventing it.

# Phase 13.2 — optional redesigned web UI, served side by side

_Branch `ui-v2`, rebased onto `phase10-demo` after 13.3b. **Not merged.** The classic UI, the API,
retrieval, the gate, the indexes and the records are unchanged; `web_v2/` is additive._

## Objective

The Phase 10.4 UI was built for a projector: four tabs, 17 px type, high-contrast badges. It
demonstrates the system but it does not look like something a service workshop would keep open all
day. Phase 13.2 is a second, optional front end at **`/v2`** — a sidebar dashboard with one search
box, light/dark, severity chips, a horizontal fault stepper, an expandable repair timeline, a
printable job card and a slide-in "Why this answer?" panel.

Both UIs are served at once and both are reachable from each other, so the old one is never at risk:
`/` is untouched apart from a single "New UI" link.

## Design decisions

**No build step, nothing fetched.** Three files — `index.html`, `style.css`, `app.js` — plus an
inline SVG sprite for every icon and a system font stack. The smoke test asserts the bundle contains
no external URL at all; the only `http://` string in it is the SVG XML **namespace** in
`createElementNS`, which is an identifier and never a request, and the check excludes it explicitly
rather than quietly passing.

**Only the existing endpoints.** `/health`, `/fleet`, `/vehicle/{id}`, `/verify-code`, `/symptom`,
`/audit`, `/replay/*`, `/scenarios`. No endpoint was added, and where the API could not support a
design idea it was dropped and recorded below rather than worked around.

**Severity is never colour alone.** Every chip prints its name — `CRITICAL`, `HIGH`, `MEDIUM`,
`LOW` — and carries a dot plus a tinted background and border. A vehicle with no rated rows gets a
plain dash, not a grey `LOW`, which would read as a real rating. The four KPI tiles use a left
colour bar as a secondary cue, never the only one.

**Four distinct, friendly message styles**, none of them an error:

| class | style | used for |
|---|---|---|
| **conversational** (13.1) | green, `RULE` tag, label `conversational · GREETING/THANKS/NO_PROBLEM` | "hi", "thanks", "no issue, the vehicle is running fine" |
| **incomplete code** (13.3) | amber, `RULE` tag, candidate list with pages | `P-10`, `P019`, `P1` |
| **invalid code** (13.4) | the same amber style, labelled `invalid code` | `P1023473efa…`, `U0100zzzz` |
| **refusal** | blue, "Not covered in this manual" + the gate's reason | out-of-scope questions |
| **clarification** | amber, "Needs clarification" + did-you-mean | known base, unknown suffix |

Only a genuine transport or server failure uses the red error style.

**The repair procedure is a vertical timeline** with the step number in the node, the spec in
monospace, and each branch rendered as a pass or fail chip — read from the manual's own words
(`if no`, `if not`, `unavailable`, `still present`, `fail` → fail; otherwise pass). Pins and the
manual page sit in the footer of every fix block.

**The job card prints one page.** `@media print` hides the shell entirely and renders a separate
`#jobcard` node: fault, system, manual page, causes, checkpoints, the numbered procedure with specs
and branches, pins, the illustrative cost note and two signature lines. The illustrative cost/TAT
panel stays dashed and separately labelled on screen *and* on paper.

**Accessibility.** Skip link; `aria-current` on the active nav item; a visible 3 px focus ring on
everything focusable; fleet rows are real buttons (`tabindex`, Enter and Space); the drawers trap
nothing but close on Escape and restore focus; an `aria-live` region announces view changes and
replay state; `prefers-reduced-motion` disables the skeleton shimmer and the drawer slide. Contrast
was chosen for AA on both themes, and `color-scheme` is declared so native selects and scrollbars
follow the theme.

**Responsive to tablet.** At ≤1000 px the sidebar collapses to an icon rail; at ≤760 px the search
box takes its own row and the stepper wraps. The main column is `minmax(0, 1fr)` so the horizontally
scrollable stepper scrolls *inside* the card instead of stretching the page — a grid item defaults
to `min-width: auto`, which was a real bug caught by looking at the screenshots.

## What the API cannot do (listed, not added)

Per the task's rule, these would need a new endpoint or field and were **not** built:

1. **True replay pause/resume.** `POST /replay/stop` is terminal: the thread ends, and
   `POST /replay/start` constructs a fresh `_Replay`, which sets `STATE["live"] = []` and begins
   again from the first row. The UI therefore labels the control **"Resume (restarts the feed)"**
   with a tooltip saying so, rather than implying a resume that does not exist. A real
   `POST /replay/pause` + `/resume` holding the index would be a small addition.
2. **Region on the fleet table.** `/fleet`'s `per_vehicle` returns `registration`,
   `worst_severity`, `episodes` and `outcomes` — no region, although `/fleet` *accepts* `?region=`.
   The column and the filter were therefore removed: an always-empty column is worse than no column.
   `/vehicle/{id}` does return region, and the Vehicle view shows it. Adding `region` to
   `per_vehicle` would restore both.
3. **Server-side sort or pagination.** The fleet table sorts and filters in the browser over the
   whole `per_vehicle` map (199 rows here). That is fine at demo scale and would not be at fleet
   scale.
4. **A per-code "related codes" view** would need the existing `advise` related-codes data exposed
   on `/symptom`; it is not in the response, so it is not shown.

## Screenshots

`docs/report/img/ui_v2/`, 19 images captured from the running server with Playwright at 1280×800
(desktop) and 834×1112 (tablet), both UIs, plus a v2 dark-mode shot:

| view | v2 | classic |
|---|---|---|
| Fleet | `v2_desktop_fleet.png`, `v2_tablet_fleet.png`, `v2_desktop_fleet_dark.png` | `classic_desktop_fleet.png`, `classic_tablet_fleet.png` |
| Service query | `v2_desktop_symptom.png`, `v2_tablet_symptom.png` | `classic_desktop_symptom.png`, `classic_tablet_symptom.png` |
| Conversational (13.1) | `v2_desktop_conversational.png`, `v2_tablet_conversational.png` | `classic_desktop_conversational.png`, `classic_tablet_conversational.png` |
| Incomplete code (13.3) | `v2_desktop_incomplete_code.png`, `v2_tablet_incomplete_code.png` | `classic_desktop_incomplete_code.png`, `classic_tablet_incomplete_code.png` |
| Vehicle | `v2_desktop_vehicle.png`, `v2_tablet_vehicle.png` | — |

Playwright is **dev-only** and is not in `requirements.txt`, exactly as in Phase 10.4;
`scripts/capture_ui_v2.py` needs a running server and is never part of the demo path.

Three bugs were found by reading those screenshots rather than by testing: the stepper wrapped onto
two rows, an `ADVISORY` episode was styled "NEEDS CONFIRMATION" (its message is an explanatory note,
not an open question), and the cards overflowed the viewport. All three are fixed.

## Verification

`./run.sh demo --check` extended to **94 checks**, **DEMO CHECK PASSED**. The new block
asserts that `/v2/`, `/v2/index.html`, `/v2/style.css` and `/v2/app.js` are served; that the bundle
fetches nothing external; that both UIs link to each other; that v2 calls only existing endpoints;
that **every** classic preset — 3 symptom, 3 conversational, 3 incomplete-code, 2 invalid-code,
2 transposition — is present in the v2 bundle; and that the API returns the same decision for each preset when driven
from v2.

Suite `src/smoke_index.py` **44 passed / 1 xfail / 0 failed**; determinism
`--defaults --index-dir index` **`ffff9bc707d8754d`**.

## Files

| file | role |
|---|---|
| `web_v2/index.html` | shell: sidebar, top bar, drawers, inline SVG sprite |
| `web_v2/style.css` | tokens, light/dark, chips, stepper, timeline, skeletons, print job card |
| `web_v2/app.js` | all four views, search dispatch, why panel, job card, presets |
| `app.py` | three added lines mounting `web_v2/` at `/v2` **before** the `/` catch-all |
| `web/index.html` | one added line: the "New UI" link |
| `scripts/demo_smoke.py` | the `/v2` block (28 checks) and a `text()` accessor for static assets |
| `scripts/capture_ui_v2.py` | dev-only screenshot capture |

## How to switch the default

Two lines in `app.py`, at the bottom where the static mounts are:

```python
app.mount("/v2", _StaticV2(directory="web_v2", html=True), name="web_v2")   # new UI
app.mount("/",   StaticFiles(directory="web",    html=True), name="web")    # classic at /
```

Swap the directories to make v2 the default and keep the old one reachable:

```python
app.mount("/classic", _StaticV2(directory="web",    html=True), name="web_classic")
app.mount("/",        StaticFiles(directory="web_v2", html=True), name="web")
```

Then flip the two cross-links (`web/index.html` → `href="/"`, `web_v2/index.html` → `href="/classic"`)
and re-run `./run.sh demo --check`, which will need its `/v2` paths re-pointed.

## How to roll back

The branch is not merged, so `phase10-demo` is already the rollback. On this branch:

- **Disable without deleting:** rename or remove the `web_v2/` directory — `app.py` guards the mount
  with `if os.path.isdir("web_v2")`, so `/v2` simply stops existing and the classic UI is unaffected.
- **Remove entirely:** `git revert` the commit, or delete `web_v2/`, the three mount lines in
  `app.py`, the "New UI" link in `web/index.html` and the `/v2` block in `scripts/demo_smoke.py`.
- Nothing else depends on it: no API, test, index or record changed.

## Limitations

1. **Not evaluated with anyone.** No technician has used it. Every claim here is about structure and
   contrast, not about whether it is faster to work with than the classic UI.
2. **No automated accessibility audit.** Contrast ratios were chosen by hand and keyboard paths were
   checked by hand; no axe/Lighthouse run was performed, and no screen reader was used.
3. **Replay "Resume" restarts the feed**, because the API has no resume (see above). The label says
   so, but it is still a compromise.
4. **The fleet table renders every vehicle**; there is no virtualisation or pagination.
5. **Print tested in headless Chromium only.** The job card uses `@page { margin: 14mm }` and should
   be checked on a real printer before anyone relies on it.
6. **Two front ends now exist**, which is a maintenance cost: a change to a response shape must be
   made twice. If v2 is adopted, the classic UI should be retired rather than kept forever.
7. **The screenshots predate 13.4.** They were captured before `invalid_code` existed, so no image
   shows that reply; it uses the same style as the incomplete-code shot, which is included.
8. **13.2 was finished after 13.3**, so the branch carries 13.1 and 13.3 behaviour; it has not been
   re-based onto anything later, and `ui-v2` must be rebased again before it is merged.

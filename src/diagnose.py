"""
Phase 6 — Conversational diagnosis: a DETERMINISTIC state machine over steps[].

Design law: the LLM phrases; it never routes. Every transition here is computed
from the structured record. No model is loaded, imported or consulted.

Three source-data realities this must survive (all measured in Phases 1-3, not
rediscovered here):

  * 37 `on_true`/`goto` targets point OUTSIDE their step list. These are manual
    typos - the document prints "Step 9" twice, skips a label, and so on - and in
    20/20 affected records the final step is a terminal "Check DTC". Such a target
    is CLAMPED to the terminal step and the clamp is logged.
  * `on_false` is null for all but 5 steps in the entire manual. Null means FALL
    THROUGH to n+1, the document's own default - not "unknown", not a dead end.
  * 4 steps reference themselves ("go to step 9" printed on step 9). A visited-set
    plus a hard step cap guarantees termination.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_STEPS = 64          # hard cap; the longest real DTC has 15 steps


@dataclass
class Transition:
    frm: int
    to: int | None
    reason: str
    answer: str | None = None
    clamped: bool = False


@dataclass
class DiagnosisState:
    record: dict
    current: int | None
    visited: list = field(default_factory=list)
    transitions: list = field(default_factory=list)
    clamps: list = field(default_factory=list)
    inferences: list = field(default_factory=list)
    finished: bool = False
    outcome: str | None = None
    pending: list = field(default_factory=list)   # queued multi-target steps


class Diagnoser:
    """Walks one DTC's steps[]. Feed it yes/no; it returns the next step."""

    def __init__(self, record):
        self.rec = record
        self.steps = {s["n"]: s for s in record["steps"]}
        self.order = [s["n"] for s in record["steps"]]
        self.terminal = self._find_terminal()

    # ---------------- structure helpers --------------------------------
    def _find_terminal(self):
        for s in reversed(self.rec["steps"]):
            if s["kind"] == "terminal":
                return s["n"]
        return self.order[-1] if self.order else None

    def _resolve(self, target, state, frm):
        """Clamp an out-of-range target to the terminal step, and log it."""
        if target is None:
            return None, False
        if target in self.steps:
            return target, False
        state.clamps.append({
            "from_step": frm, "requested": target, "clamped_to": self.terminal,
            "reason": "target outside step list (source-document defect)",
        })
        return self.terminal, True

    def _fallthrough(self, n):
        i = self.order.index(n) if n in self.order else -1
        return self.order[i + 1] if 0 <= i < len(self.order) - 1 else None

    # ---------------- public -------------------------------------------
    def start(self):
        st = DiagnosisState(record=self.rec,
                            current=self.order[0] if self.order else None)
        if st.current is None:
            st.finished, st.outcome = True, "no steps in this record"
        return st

    def current_step(self, state):
        return self.steps.get(state.current) if state.current else None

    def needs_answer(self, state):
        """
        True only when the transition genuinely depends on an outcome.

        A step with a target but NO condition is an unconditional instruction
        ("Fix the back-out cables ... & go to Step 13") - asking yes/no there
        would invent a decision the manual never poses.
        """
        s = self.current_step(state)
        if not s or s["kind"] == "terminal":
            return False
        return s["condition"] is not None

    def advance(self, state, answer=None):
        """
        `answer` is "yes"/"no" (condition held or not), or None for a step that
        needs no decision. Returns the mutated state.
        """
        s = self.current_step(state)
        if s is None or state.finished:
            state.finished = True
            return state

        state.visited.append(s["n"])

        # --- terminal -------------------------------------------------
        if s["kind"] == "terminal":
            state.finished = True
            state.outcome = ("Fault cleared." if answer == "yes" else
                             "Fault still present — escalate / re-run diagnosis."
                             if answer == "no" else
                             "Reached the final check. Did the fault clear?")
            state.transitions.append(Transition(s["n"], None, "terminal step"))
            return state

        # --- multi-target: "go to Step 9 & 11" means DO BOTH ----------
        if len(s["goto"]) > 1 and s["on_true"] is None:
            seq = []
            for t in s["goto"]:
                r, cl = self._resolve(t, state, s["n"])
                if r is not None:
                    seq.append(r)
            state.pending = seq[1:]
            nxt = seq[0] if seq else self._fallthrough(s["n"])
            state.transitions.append(Transition(
                s["n"], nxt, f"multi-target: perform steps {s['goto']} in sequence"))
            return self._goto(state, nxt)

        # --- normal routing -------------------------------------------
        unconditional = s["condition"] is None and s["on_true"] is not None
        if unconditional or answer == "yes":
            tgt, clamped = self._resolve(s["on_true"], state, s["n"])
            if tgt is None:
                tgt, reason = self._fallthrough(s["n"]), "condition held; no target stated, fall through"
            else:
                reason = (f"unconditional jump -> {s['on_true']}" if unconditional
                          else f"condition held -> on_true={s['on_true']}") + (
                    " (CLAMPED to terminal)" if clamped else "")
        else:
            tgt, clamped = self._resolve(s["on_false"], state, s["n"])
            if tgt is None:
                tgt = self._fallthrough(s["n"])
                reason = ("condition did not hold; on_false is null -> "
                          "fall through to next step")
                # If the TRUE branch already goes to n+1, plain fall-through
                # would send both answers to the same place, making the manual's
                # own condition a no-op - and in P0192-00 it renders steps 9-12
                # unreachable. 256 conditional steps (24%) are shaped this way.
                # The false branch therefore skips the step the true branch
                # occupies. This is an INFERENCE, not stated text, so it is
                # logged like a clamp.
                if (s["condition"] is not None and s["on_true"] is not None
                        and s["on_true"] == tgt):
                    skipped, tgt = tgt, self._fallthrough(tgt)
                    if tgt is None:
                        tgt = self.terminal
                    state.inferences.append({
                        "step": s["n"], "rule": "skip_true_branch",
                        "detail": (f"on_true=={skipped} is the next step; false "
                                   f"branch skips it to {tgt} so the stated "
                                   f"condition is not a no-op"),
                    })
                    reason = (f"condition did not hold; true branch occupies "
                              f"step {skipped}, so skipped to {tgt} [inferred]")
            else:
                reason = f"condition did not hold -> on_false={s['on_false']}" + (
                    " (CLAMPED to terminal)" if clamped else "")

        state.transitions.append(
            Transition(s["n"], tgt, reason, answer=answer, clamped=clamped))
        return self._goto(state, tgt)

    def _goto(self, state, nxt):
        # loop guard: a self-reference or cycle must terminate
        if nxt is not None and nxt in state.visited:
            state.transitions.append(Transition(
                nxt, None, f"loop guard: step {nxt} already visited — treating as terminal"))
            state.current = self.terminal if self.terminal not in state.visited else None
            state.finished = True
            state.outcome = (f"Loop detected (step {nxt} revisited). "
                             f"Ending at the final check.")
            return state
        if len(state.visited) >= MAX_STEPS:
            state.finished = True
            state.outcome = f"Step cap ({MAX_STEPS}) reached — aborting."
            return state
        if nxt is None:
            if state.pending:
                nxt = state.pending.pop(0)
            else:
                state.finished = True
                state.outcome = "End of procedure."
                state.current = None
                return state
        state.current = nxt
        return state

    # ---------------- trace --------------------------------------------
    def path_trace(self, state):
        return {
            "code_full": self.rec["code_full"],
            "page": self.rec["page"],
            "visited": state.visited,
            "finished": state.finished,
            "outcome": state.outcome,
            "clamps": state.clamps,
            "inferences": state.inferences,
            "transitions": [
                {"from": t.frm, "to": t.to, "answer": t.answer,
                 "reason": t.reason, "clamped": t.clamped}
                for t in state.transitions],
        }


def walk(record, answers):
    """Non-interactive walk driven by a list of yes/no answers. For tests."""
    d = Diagnoser(record)
    st = d.start()
    it = iter(answers)
    while not st.finished:
        ans = next(it, "no") if d.needs_answer(st) else None
        st = d.advance(st, ans)
    return d.path_trace(st)

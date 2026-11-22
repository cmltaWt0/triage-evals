"""Scores. A sample is `ok` when the verdict is the expected one (reviewer), or when every cell of the answer key has an
acceptable word and the runner found no problem (agent; e2e also needs the review to pass). The named objections and
the `checked` patterns are regular expressions, a heuristic: they are reported apart and never change `ok`."""
import re
from collections import Counter


def found(patterns: list[str], text: str) -> bool:
    """Whether every pattern matches somewhere in the text."""
    return all(re.search(p, text) for p in patterns)


def reviewer(res: dict, spec: dict) -> dict:
    text = res.get("text", "")
    must = [{"means": o["means"], "found": found(o["patterns"], text)} for o in spec.get("must", [])]
    must_not = [{"means": o["means"], "found": found(o["patterns"], text)} for o in spec.get("must_not", [])]
    objections = (all(m["found"] for m in must) and not any(m["found"] for m in must_not)) if must or must_not else None
    return {**res, "expected": spec["verdict"], "ok": res["verdict"] == spec["verdict"], "must": must,
            "must_not": must_not, "objections_ok": objections}


def agent(result: dict, outcome: str, spec: dict, session: dict) -> dict:
    """The runner's result of one run against the answer key: the verdicts it kept, after its own checks."""
    got = {f"{v['advisory']}/{v['repo']}": v["verdict"] for v in result.get("verdicts") or []}
    words = {cell: got.get(cell, "none") for cell in spec["key"]}
    misses = [cell for cell, w in words.items() if w not in spec["key"][cell]]
    notes = {str(c["advisory"]): c["note"] for c in result.get("checked") or []}
    checked = [{"advisory": c["advisory"], "found": found(c["patterns"], notes.get(c["advisory"], ""))}
               for c in spec.get("checked", [])]
    problems = result.get("problems") or []
    return {"ok": not misses and not problems, "words": words, "misses": misses, "problems": problems,
            "checked": checked, "notes": notes, "summary": result.get("summary"), "outcome": outcome,
            "verdicts": result.get("verdicts") or [], **session}


def e2e(result: dict, outcome: str, spec: dict, sessions: list[dict], rounds: list[dict]) -> dict:
    s = agent(result, outcome, spec, {"seconds": sum(x["seconds"] for x in sessions),
                                      "model": " ".join(sorted({x["model"] for x in sessions})), "sessions": sessions})
    passed = next((n for n, r in enumerate(rounds, 1) if r["verdict"] == "PASS"), None)
    return {**s, "verdicts_ok": s["ok"], "ok": s["ok"] and passed is not None, "passed_round": passed,
            "rounds": rounds}


def flips(samples: list[dict]) -> dict[str, dict[str, int]]:
    """The cells whose word was not the same in every sample, with how often each word came."""
    by = {cell: Counter(s["words"][cell] for s in samples) for cell in samples[0]["words"]} if samples else {}
    return {cell: dict(c) for cell, c in by.items() if len(c) > 1}

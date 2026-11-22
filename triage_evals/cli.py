"""./evals run reviewer|agent|e2e [options], ./evals report FILE, ./evals compare OLD NEW. See README.md."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from triage_evals import cases, engine, results, runner, score

ROOT = cases.ROOT


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="evals", description="Evals of Arceus's advisory triage.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run an eval and write its result file")
    r.add_argument("eval", choices=("reviewer", "agent", "e2e"))
    r.add_argument("--cases", default="*", help="a glob over case names (default: all of the eval's cases)")
    r.add_argument("--samples", type=int, default=3, help="runs per case (default 3)")
    r.add_argument("--arceus", default=os.environ.get("ARCEUS_DIR"), help="the Arceus checkout (or ARCEUS_DIR)")
    r.add_argument("--engine", help="the engine's source (default: the commit the checkout pins, fetched)")
    r.add_argument("--out", help="the result file (default: results/<eval>-<time>-<arceus commit>.json)")
    r.add_argument("--review-model", help="passed to codex as -m")
    r.add_argument("--review-effort", help="passed to codex as model_reasoning_effort")
    r.add_argument("--agent-model", default="opus", help="passed to claude as --model (default opus)")
    r.add_argument("--reviewer-answer", metavar="FILE", help="a stand-in reviewer: FILE is every review's answer")
    r.add_argument("--agent-answer", metavar="FILE", help="a stand-in agent: FILE is every session's verdicts.json")
    sub.add_parser("report", help="print a result file as a table").add_argument("file")
    c = sub.add_parser("compare", help="what changed between two result files; exits 1 when a pass rate fell")
    c.add_argument("old")
    c.add_argument("new")
    a = p.parse_args(argv)
    if a.cmd == "report":
        print(results.report(results.load(a.file)))
        return 0
    if a.cmd == "compare":
        text, fell = results.compare(results.load(a.old), results.load(a.new))
        print(text)
        return 1 if fell else 0
    if not a.arceus:
        p.error("the Arceus checkout to evaluate: --arceus DIR or ARCEUS_DIR")
    if a.samples < 1:
        p.error("--samples is at least 1")
    arceus = Path(a.arceus).resolve()
    venv = arceus / "runner" / ".venv"
    if Path(sys.prefix).resolve() != venv.resolve():  # the runner and its test stand-ins need the checkout's Python
        if not (venv / "bin" / "python").exists():
            raise SystemExit(f"no virtualenv at {venv}: set up the checkout's runner first")
        os.execv(venv / "bin" / "python", [str(venv / "bin" / "python"), str(ROOT / "evals"), *argv])
    return run(a, arceus)


def run(a, arceus: Path) -> int:
    work = Path(os.environ.get("EVALS_WORK") or ROOT / ".work").resolve()
    (work / "tmp").mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(work / "tmp")  # never the system's /tmp, for this process and all it starts
    tempfile.tempdir = None
    chosen = cases.select(cases.load(), "reviewer" if a.eval == "reviewer" else "agent", a.cases)
    if not chosen:
        raise SystemExit(f"no {a.eval} case is named like {a.cases!r}")
    runner.use(arceus)
    eng = engine.source(arceus, a.engine, work)
    src = (eng / engine.GATE).read_text()
    engine.templates(src)  # a changed engine stops the eval here, before any model is asked
    now = datetime.now(UTC)
    scratch = work / "runs" / f"{a.eval}-{now:%Y%m%d-%H%M%S}"
    ctx = {"arceus": arceus, "engine": eng, "src": src, "scratch": scratch, "samples": a.samples,
           "e2e": a.eval == "e2e",
           "ask": engine.canned(a.reviewer_answer) if a.reviewer_answer else
           engine.codex(a.review_model, a.review_effort),
           "session": runner.canned(a.agent_answer) if a.agent_answer else runner.claude(a.agent_model)}
    out = {"eval": a.eval, "date": now.isoformat(timespec="seconds"), "target": target(a, arceus, eng),
           "options": {"cases": a.cases, "samples": a.samples},
           "cases_hash": hashlib.sha256(" ".join(f"{c.id}:{c.hash}" for c in chosen).encode()).hexdigest()[:12],
           "cases": []}
    origins = {}  # a project's repositories, made once for all its cases
    for case in chosen:
        if case.folder not in origins:
            origins[case.folder] = cases.materialize(case, scratch / "origin" / case.folder.name)
        samples = []
        for s in EVALS[a.eval](case, origins[case.folder], ctx):
            samples.append(s)
            print(f"{case.id} {len(samples)}/{a.samples}: {'as expected' if s['ok'] else 'NOT as expected'}, "
                  f"{s['seconds']} s", file=sys.stderr, flush=True)
        out["cases"].append({"id": case.id, "hash": case.hash, "expected": case.spec, "samples": samples,
                             "passed": sum(s["ok"] for s in samples), "of": len(samples),
                             **({"flips": score.flips(samples)} if a.eval != "reviewer" else {})})
    every = [s for c in out["cases"] for s in c["samples"]]
    reviews = every if a.eval == "reviewer" else [r for s in every for r in s.get("rounds", [])]
    sessions = [] if a.eval == "reviewer" else [x for s in every for x in s.get("sessions", [s])]
    out["reported"] = {"reviewer": sorted({x["model"] for x in reviews}),
                       "agent": sorted({x["model"] for x in sessions})}
    path = Path(a.out or ROOT / "results" / f"{a.eval}-{now:%Y%m%d-%H%M%S}-{out['target']['arceus'][:7]}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    shutil.rmtree(scratch)
    print(results.report(out))
    print(f"\nwritten to {path}")
    return 0


def target(a, arceus: Path, eng: Path) -> dict:
    """What the eval ran on, as far as this machine can tell before it starts."""
    def git(d: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True).stdout.strip()

    def version(cli: str, used: bool, standin: str | None) -> str | None:
        return None if not used else f"stand-in {standin}" if standin else "not installed" if not shutil.which(cli) \
            else subprocess.run([cli, "--version"], capture_output=True, text=True).stdout.strip()

    return {"arceus": git(arceus, "rev-parse", "HEAD"), "arceus_dirty": bool(git(arceus, "status", "--porcelain")),
            "engine": git(eng, "rev-parse", "HEAD") or "unknown",
            "engine_pinned": engine.pinned(arceus).get("BULAVA_REF"),
            "codex": version("codex", a.eval != "agent", a.reviewer_answer),
            "claude": version("claude", a.eval != "reviewer", a.agent_answer),
            "review_model": a.review_model, "review_effort": a.review_effort,
            "agent_model": a.agent_model if a.eval != "reviewer" else None}


def reviewer_eval(case, origin, ctx):
    """The case's report through round 1 of the review, `samples` times, on one prepared run."""
    state = ctx["scratch"] / case.id
    t = runner.Triage(ctx["arceus"], case, origin, state)
    try:
        if case.spec.get("earlier"):  # a two-run case: the first run's verdicts are the second run's `earlier`
            first = t.start()
            shutil.copyfile(case.folder / case.spec["earlier"], first["report"])
            t.finish(first["id"])
        r = t.start()
        shutil.copyfile(case.folder / case.spec["report"], r["report"])
        for i in range(ctx["samples"]):
            yield score.reviewer(engine.review(ctx["engine"], ctx["src"], r, 1, state / f"ledger-{i}", ctx["ask"]),
                                 case.spec)
    finally:
        t.close()


def triage_eval(case, origin, ctx):
    """The agent triages the case's project, a new run each sample, and the runner reads what it wrote. For e2e, the
    review rounds the runner asked for come between: a failed report goes to a new agent session with the reviewer's
    objections, as the engine's stop hook gives them, and at the limit it is accepted with the reviewer's notes."""
    for i in range(ctx["samples"]):
        state = ctx["scratch"] / case.id / str(i)
        t = runner.Triage(ctx["arceus"], case, origin, state)
        try:
            r = t.start()
            sessions = [ctx["session"](r["brief"] + runner.AGENT_NOTE, r["workspace"], r["report"])]
            rounds, receipt = [], None
            for rnd in range(1, r["rounds"] + 1) if ctx["e2e"] else ():
                res = engine.review(ctx["engine"], ctx["src"], r, rnd, state / "ledger", ctx["ask"])
                rounds.append(res)
                if res["verdict"] == "PASS":
                    receipt = {"result": "succeeded_research", "review": "passed", "commits": []}
                    break
                if res["verdict"] != "FAIL":
                    break  # no readable verdict: the engine would park the run and wait for its reviewer
                if rnd >= r["rounds"] or res["stall"] >= 2:  # --report-at-limit accept, as the runner asks
                    receipt = {"result": "succeeded_research", "review": "passed", "accepted_with_notes": True,
                               "commits": [], "review_why": res["text"]}
                    break
                back = engine.send_back(ctx["src"], rnd, r["rounds"], res["text"])
                sessions.append(ctx["session"](r["brief"] + runner.AGENT_NOTE + "\n\n" + back + runner.FIX_NOTE,
                                               r["workspace"], r["report"]))
            result, outcome = t.finish(r["id"], receipt)
        finally:
            t.close()
        yield score.e2e(result, outcome, case.spec, sessions, rounds) if ctx["e2e"] else \
            score.agent(result, outcome, case.spec, sessions[0])


EVALS = {"reviewer": reviewer_eval, "agent": triage_eval, "e2e": triage_eval}

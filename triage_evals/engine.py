"""The engine's report review (hooks/review-gate.sh, stage gate.reportReview) done outside the engine: the prompt and
the text that sends a report back are cut out of the gate script, never retyped, and a piece not found exactly once
stops the eval; the clips, the Codex call and the engine's own find-report, report-text and review-ledger tools."""
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

GATE = "hooks/review-gate.sh"
TIMEOUT = 480  # seconds, as review_call gives Codex


class EngineError(Exception):
    """The engine's part cannot be reproduced: its gate script changed, or one of its tools failed."""


def pinned(arceus: Path) -> dict[str, str]:
    """BULAVA_SOURCE and BULAVA_REF as the Arceus checkout's setup/setup.conf.example pins them."""
    text = (arceus / "setup" / "setup.conf.example").read_text()
    return dict(re.findall(r"^(BULAVA_SOURCE|BULAVA_REF)=(\S+)", text, re.M))


def source(arceus: Path, given: str | None, work: Path) -> Path:
    """The engine folder (the one with hooks/ and bin/): the source given, else the commit the checkout pins, fetched
    once into the work folder."""
    if given:
        root = Path(given).resolve()
    else:
        pin = pinned(arceus)
        root = work / f"engine-{pin['BULAVA_REF'][:12]}"
        if not root.exists():
            part = root.with_name(root.name + ".part")
            shutil.rmtree(part, ignore_errors=True)
            for args in (["init", "-q", str(part)],
                         ["-C", str(part), "fetch", "-q", "--depth", "1", pin["BULAVA_SOURCE"], pin["BULAVA_REF"]],
                         ["-C", str(part), "checkout", "-q", "FETCH_HEAD"]):
                subprocess.run(["git", *args], check=True)
            part.rename(root)
    return root / "engine" if (root / "engine" / GATE).exists() else root


def clip(text: str, n: int) -> str:
    """clip_utf8 (bin/supervisor-lib.sh): at most n bytes, never half a character."""
    return text.encode()[:n].decode("utf-8", errors="ignore")


def _one(text: str, piece: str) -> None:
    if text.count(piece) != 1:
        raise EngineError(f"{GATE} has {text.count(piece)} of {piece[:70]!r} where this harness needs exactly one: "
                          "the engine changed, and its report review is not reproduced until the harness follows it")


def _once(text: str, old: str, new: str) -> str:
    _one(text, old)
    return text.replace(old, new)


def _piece(src: str, head: str, first: str, last: str, closer: str = '"\n') -> str:
    """A shell string of the gate script: from `first` (right after `head`, the two found together exactly once) to
    `last`, the first one followed by `closer`."""
    _one(src, head + first)
    a = src.index(head + first) + len(head)
    b = src.find(last + closer, a)
    if b < 0:
        raise EngineError(f"{GATE} has no {last[:60]!r} closing the string that starts {first[:40]!r}")
    return src[a:b + len(last)]


def templates(src: str) -> dict[str, str]:
    """The prompt, its FIX CHECK block, the duplicates paragraph and the send-back text, every shell expansion
    replaced by a marker; one this harness does not know stops it."""
    t = {"prompt": _piece(src, '  rprompt="', "You are reviewing a RESEARCH REPORT, not code.",
                          "most important first."),
         "fix": _piece(src, '    _rfix_block="', "\nFIX CHECK — this is not a first reading.",
                       "the full reading is done.\n"),
         "group": _piece(src, '&& _rgroup="', "Some ids above may be one defect described twice.",
                         "names an open id above, no item closes.\n"),
         "back": _piece(src, 'jq -n --arg reason "', "🌙 Рецензент звіту не прийняв його (коло ",
                        "і заяви результат ще раз.", '" \\\n')}
    for old, new in (("""$((rounds + 1))$(rounds_unlimited "$_rmax" || printf ' of at most %s' "$_rmax")""",
                      "\0ROUND\0"), ("$_task\n", "\0TASK\0\n"),
                     ("$_crit\n${_piece_block:+\n$_piece_block\n}\n", "\0CRIT\0\n\n"), ("($_report)", "(\0REPORT\0)"),
                     ("${_text:-(the report is empty)}", "\0TEXT\0"), ("${_rfix_block}", "\0FIX\0")):
        t["prompt"] = _once(t["prompt"], old, new)
    t["fix"] = _once(t["fix"], '$(python3 "$BIN_DIR/lib/review-ledger.py" open "$LEDGER_F" 2>/dev/null)', "\0OPEN\0")
    t["fix"] = _once(t["fix"], "${_rgroup}", "\0GROUP\0")
    t["back"] = _once(t["back"], """$_next$(rounds_unlimited "$_rmax" || printf ' з %s' "$_rmax")""", "\0ROUND\0")
    t["back"] = _once(t["back"], "$review", "\0REVIEW\0")
    for name, piece in t.items():
        if "$" in piece:
            raise EngineError(f"the {name} text of {GATE} has a shell expansion this harness does not know")
    return t


def _fill(text: str, **values: str) -> str:
    for k, v in values.items():
        text = text.replace(f"\0{k}\0", v)
    return text


def build(src: str, task: str, crit: str, report: str, text: str, rnd: int, rmax: int,
          fix: tuple[str, bool] | None = None) -> str:
    """The review prompt as the gate composes it. `fix`: the ledger's open items and whether it is grouped, for a
    round after the first. Each part is taken by command substitution, which drops the newlines at its end."""
    t = templates(src)
    block = "" if fix is None else _fill(t["fix"], OPEN=fix[0], GROUP="" if fix[1] else t["group"])
    return _fill(t["prompt"], ROUND=f"{rnd} of at most {rmax}", TASK=clip(task, 6000).rstrip("\n"),
                 CRIT=clip(crit, 8000).rstrip("\n"), REPORT=report,
                 TEXT=text.rstrip("\n") or "(the report is empty)", FIX=block)


def send_back(src: str, rnd: int, rmax: int, review: str) -> str:
    """What the engine's stop hook tells the worker when the review failed its report."""
    return _fill(templates(src)["back"], ROUND=f"{rnd} з {rmax}", REVIEW=review)


def parse(answer: str) -> tuple[str, bool]:
    """The verdict and STATE: COMPLETE, from whole header lines in the first eight; PASS without COMPLETE is none."""
    head = "\n".join(answer.splitlines()[:8])
    m = re.search(r"^[ \t*]*VERDICT:[ \t]*(PASS|FAIL)[ \t*]*$", head, re.M)
    complete = bool(re.search(r"^[ \t*]*STATE:[ \t]*COMPLETE[ \t*]*$", head, re.M))
    verdict = m.group(1) if m else ""
    return ("" if verdict == "PASS" and not complete else verdict), complete


def codex(model: str | None, effort: str | None):
    """The reviewer as review_call starts it: read-only, web search on (the report review asks for it)."""
    def ask(prompt: str, cwd: Path) -> dict:
        cmd = ["codex", "exec", *(["-c", f"model_reasoning_effort={effort}"] if effort else []),
               *(["-m", model] if model else []), "--sandbox", "read-only", "--skip-git-repo-check",
               "-c", "tools.web_search=true", "--", "-"]
        t0 = time.monotonic()
        try:
            r = subprocess.run(cmd, cwd=cwd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT)
            out, rc, err = r.stdout, r.returncode, r.stderr
        except subprocess.TimeoutExpired:
            out, rc, err = "", 142, f"timed out after {TIMEOUT} s"
        said = [m.group(1).strip() if m else "?" for m in
                (re.search(rf"^{k}: (.+)$", err, re.M) for k in ("model", "reasoning effort"))]
        return {"answer": out, "rc": rc, "seconds": round(time.monotonic() - t0),
                "model": f"{said[0]}, effort {said[1]}", **({"error": err.strip()[-300:]} if rc else {})}
    return ask


def canned(path: str):
    """A stand-in reviewer: the file's content is its answer, every time."""
    answer = Path(path).read_text()
    return lambda prompt, cwd: {"answer": answer, "rc": 0, "seconds": 0, "model": "stand-in"}


def review(engine: Path, src: str, run: dict, rnd: int, ledger: Path, ask) -> dict:
    """One round of the report review of `run` (runner.Triage.start), with the report's ledger as the gate keeps it."""
    def call(script: str, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(engine / "bin" / script), *map(str, args)], capture_output=True,
                              text=True)

    def book(*args) -> str:
        r = call("lib/review-ledger.py", *args)
        if r.returncode:
            raise EngineError(f"review-ledger.py {args[0]} exited {r.returncode}: {r.stderr.strip()}")
        return r.stdout.strip()

    report = call("pipeline-tool.py", "find-report", "--cwd", run["workspace"],
                  "--summary", f"artifacts/{run['id']}/verdicts.txt the report").stdout.strip()
    if not report:
        raise EngineError("the engine's find-report found no report in artifacts/")
    text = call("pipeline-tool.py", "report-text", report, "--max", "60000").stdout
    fix = (book("open", ledger), book("grouped", ledger) == "1") if ledger.exists() else None
    got = ask(build(src, run["brief"], run["criteria"], report, text, rnd, run["rounds"], fix), run["workspace"])
    answer = got.pop("answer")
    answer = answer if got["rc"] == 0 else ""  # the gate drops what a failed call printed
    verdict, complete = parse(answer)
    opened = stall = 0
    if complete and verdict:
        tmp = ledger.with_name(ledger.name + ".answer")
        tmp.write_text(answer + "\n")
        if fix is not None:
            res = json.loads(book("apply", ledger, tmp, "[]"))
            opened, stall = len(res["open"]), int(res.get("stall") or 0)
            if opened:
                verdict = "FAIL"
                answer += ("\n\nSTILL OPEN FROM THE REVIEW (not confirmed fixed; ids are stable):\n"
                           + book("open", ledger))
        elif verdict == "FAIL":
            opened = int(book("init", ledger, tmp, "[]", "one") or 0)
        tmp.unlink()
    if verdict == "PASS":
        ledger.unlink(missing_ok=True)
    return {"verdict": verdict, "complete": complete, "text": answer, "open": opened, "stall": stall, **got}

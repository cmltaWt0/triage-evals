"""The whole `run` path on the Arceus checkout's runner, with a stand-in reviewer and a stand-in agent."""
import json
import re
import shutil
import subprocess

from conftest import ARCEUS, ENGINE
from triage_evals import cases, cli

PASS, FAIL = "STATE: COMPLETE\nVERDICT: PASS\n", "STATE: COMPLETE\nVERDICT: FAIL\n\n1. The APT note is vague.\n"
REPORTS = cases.ROOT / "cases" / "shop" / "reports"


def head(d: str) -> str:
    return subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def test_the_reviewer_eval_reviews_the_cases_report_after_its_earlier_run(evals, monkeypatch, capsys):
    seen = []

    def ask(prompt, cwd):  # what the reviewer is given: the prompt, and the run's folder in the workspace
        folder = sorted((cwd / ".arceus" / "secops").iterdir())[-1]
        seen.append((folder.name, json.loads((folder / "advisories.json").read_text()), prompt))
        return {"answer": PASS, "rc": 0, "seconds": 0, "model": "stand-in"}
    monkeypatch.setattr(cli.engine, "canned", lambda path: ask)
    res = evals("reviewer", "--cases", "shop/[ce]*", "--reviewer-answer", "-")
    assert [(c["id"], c["passed"], c["of"]) for c in res["cases"]] == [
        ("shop/clean-follows-notes", 1, 1), ("shop/earlier-verdict-turned-by-notes", 1, 1)]
    assert [s[0] for s in seen] == ["secops-1", "secops-2"]  # the earlier case's second run is the one reviewed
    earlier = {e["repo"]: e["verdict"] for a in seen[1][1] if a["id"] == "x_SHOP-2026-0012" for e in a["earlier"]}
    assert earlier == {"shop-deploy": "needs_review", "shop-api": "needs_review", "shop-web": "needs_review"}
    assert '"verdict": "not_affected"' not in seen[0][2] and '"verdict": "not_affected"' in seen[1][2]
    t = res["target"]
    assert (t["arceus"], t["engine"], t["codex"], t["claude"]) == (head(ARCEUS), head(ENGINE), "stand-in -", None)
    assert res["reported"] == {"reviewer": ["stand-in"], "agent": []} and len(res["cases_hash"]) == 12
    assert "| shop/earlier-verdict-turned-by-notes | 1/1 | PASS (expected PASS) · 0 s a sample |" \
        in capsys.readouterr().out


def test_the_agent_eval_scores_what_the_runner_kept(evals, tmp_path, capsys):
    res = evals("agent", "--cases", "shop*", "--agent-answer", str(REPORTS / "clean-follows-notes.json"))
    assert [(c["id"], c["passed"]) for c in res["cases"]] == [("shop", 1), ("shop-setting", 0), ("shop-variant", 0)]
    assert "| **total** | **1/3** | 1 of 3 cases in every sample |" in capsys.readouterr().out
    assert res["cases"][1]["samples"][0]["misses"] == ["x_SHOP-2026-0014/shop-api", "x_SHOP-2026-0015/shop-api"]
    assert res["cases"][2]["samples"][0]["misses"] == ["x_SHOP-2026-0014/shop-api"]
    broken = json.loads((REPORTS / "clean-follows-notes.json").read_text())
    broken["verdicts"][0]["where"] = [{"repo": "shop-api", "file": "app/missing.py", "line": 1}]
    (tmp_path / "broken.json").write_text(json.dumps(broken))
    s = evals("agent", "--cases", "shop", "--agent-answer", str(tmp_path / "broken.json"))["cases"][0]["samples"][0]
    assert not s["ok"] and s["problems"] and s["misses"] == ["x_SHOP-2026-0011/shop-api"]


def test_the_e2e_eval_sends_a_failed_report_back_until_its_limit(evals, tmp_path, monkeypatch):
    prompts = []

    def session(prompt, cwd, report):
        prompts.append(prompt)
        report.write_bytes((REPORTS / "clean-follows-notes.json").read_bytes())
        return {"seconds": 1, "model": "stand-in"}
    monkeypatch.setattr(cli.runner, "canned", lambda path: session)
    (tmp_path / "fail.txt").write_text(FAIL)
    s = evals("e2e", "--cases", "shop", "--agent-answer", "-", "--reviewer-answer", str(tmp_path / "fail.txt"))
    s = s["cases"][0]["samples"][0]
    assert [(r["verdict"], r["stall"]) for r in s["rounds"]] == [("FAIL", 0), ("FAIL", 1), ("FAIL", 2)]
    assert s["passed_round"] is None and s["verdicts_ok"] and not s["ok"] and s["seconds"] == 3
    assert "(коло 1 з 3):\n\nSTATE: COMPLETE\nVERDICT: FAIL\n\n1. The APT note is vague." in prompts[1]
    assert "STILL OPEN FROM THE REVIEW" in prompts[2] and prompts[2].endswith("correct that file and stop.)")
    (tmp_path / "pass.txt").write_text(PASS)
    s = evals("e2e", "--cases", "shop", "--agent-answer", "-", "--reviewer-answer", str(tmp_path / "pass.txt"))
    assert s["cases"][0]["samples"][0]["passed_round"] == 1 and s["cases"][0]["passed"] == 1


def test_the_reviewer_is_codex_started_as_the_gate_starts_it(evals, tmp_path):
    (tmp_path / "bin" / "codex").write_text(  # in place of the fixture's guard
        f'#!/bin/sh\n[ "$1" = --version ] && echo "codex-cli 9.9" && exit 0\nprintf "%s\\n" "$@" > {tmp_path}/argv\n'
        f'cat > {tmp_path}/prompt\nprintf "workdir: /w\\nmodel: m1\\nreasoning effort: high\\n" >&2\necho "{PASS}"\n')
    res = evals("reviewer", "--cases", "shop/clean*", "--review-model", "m1", "--review-effort", "high")
    assert (tmp_path / "argv").read_text().split() == ("exec -c model_reasoning_effort=high -m m1 --sandbox read-only "
                                                       "--skip-git-repo-check -c tools.web_search=true -- -").split()
    assert (tmp_path / "prompt").read_text().startswith("You are reviewing a RESEARCH REPORT, not code.")
    assert res["target"]["codex"] == "codex-cli 9.9" and res["reported"]["reviewer"] == ["m1, effort high"]
    assert res["cases"][0]["passed"] == 1


def test_the_agent_is_a_headless_claude_session_given_the_runners_brief(evals, tmp_path):
    (tmp_path / "bin" / "claude").write_text(  # in place of the fixture's guard; it writes the clean report
        f'#!/bin/sh\n[ "$1" = --version ] && echo "9.9 (Claude Code)" && exit 0\n'
        f'printf "%s\\n" "$@" > {tmp_path}/argv\n'
        f'cat > {tmp_path}/prompt\ncp {REPORTS}/clean-follows-notes.json .arceus/secops/secops-1/verdicts.json\n'
        'echo \'{"modelUsage": {"m-agent": {}}, "num_turns": 3}\'\n')
    res = evals("agent", "--cases", "shop", "--agent-model", "m2")
    assert (tmp_path / "argv").read_text().split() == (
        "-p --output-format json --model m2 --strict-mcp-config --setting-sources project --disable-slash-commands "
        "--no-session-persistence --tools Read,Grep,Glob,Write --permission-mode acceptEdits").split()
    prompt = (tmp_path / "prompt").read_text()
    assert prompt.startswith("Triage run 1:") and prompt.endswith("as told above, then stop.)")
    assert re.findall(r"^- `(shop-[a-z]+)` \(main\)", prompt, re.M) == ["shop-api", "shop-web", "shop-deploy"]
    assert res["target"]["claude"] == "9.9 (Claude Code)" and res["reported"]["agent"] == ["m-agent"]
    assert res["cases"][0]["passed"] == 1


def test_a_case_from_a_real_run_gets_the_advisories_that_run_was_given(evals, monkeypatch, tmp_path):
    """advisories.json instead of OSV records: ids, facts and texts reach the agent and the reviewer unchanged, and a
    repository may sit under a group path, as on a real code host."""
    shop, case = cases.ROOT / "cases" / "shop", tmp_path / "cases" / "replayed"
    shutil.copytree(shop / "repos" / "shop-api", case / "repos" / "sub" / "shop-api")
    for name in ("shop-web", "shop-deploy"):
        shutil.copytree(shop / "repos" / name, case / "repos" / name)
    shutil.copyfile(shop / "notes.md", case / "notes.md")
    given = [{"id": 41, "ref": "SEC-41", "title": "pixloom: heap overflow", "text": "pixloom before 2.4.1 overflows.",
              "facts": {"identifiers": ["EXAMPLE-41"], "kev": True, "fixed": ["2.4.1"]}}]
    (case / "advisories.json").write_text(json.dumps(given))
    verdict = {"advisory": 41, "repo": "sub/shop-api", "verdict": "affected", "evidence": "e",
               "where": [{"repo": "sub/shop-api", "file": "requirements.txt", "line": 2}]}
    checked = [{"advisory": 41, "note": "n"}]
    (case / "report.json").write_text(json.dumps({"summary": "One advisory.", "checked": checked,
                                                  "verdicts": [verdict]}))
    (case / "case.toml").write_text('repos = ["sub/shop-api", "shop-web", "shop-deploy"]\n[[reviewer]]\nname = "r"\n'
                                    'report = "report.json"\nverdict = "PASS"\nwhy = "w"\n')
    seen = []

    def ask(prompt, cwd):
        folder = sorted((cwd / ".arceus" / "secops").iterdir())[-1]
        seen.append((json.loads((folder / "advisories.json").read_text()), prompt,
                     (cwd / "sub" / "shop-api" / "requirements.txt").is_file()))
        return {"answer": PASS, "rc": 0, "seconds": 0, "model": "stand-in"}
    monkeypatch.setattr(cli.engine, "canned", lambda path: ask)
    real = cases.load
    monkeypatch.setattr(cli.cases, "load", lambda: real(tmp_path))
    res = evals("reviewer", "--cases", "replayed/*", "--reviewer-answer", "-")
    assert [(c["id"], c["passed"]) for c in res["cases"]] == [("replayed/r", 1)]
    (advisories, prompt, cloned), = seen
    assert advisories == [{**given[0], "earlier": []}] and cloned
    assert "- `sub/shop-api` (main): checked out at" in prompt

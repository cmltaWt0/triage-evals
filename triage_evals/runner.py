"""A triage run on an Arceus checkout's own runner code, as local-run.py made it. Real: the runner (it prepares the
run, writes the brief, advisories.json and notes.md, reads verdicts.json, checks every reference, decides the
outcome). Stand-ins from the checkout's own tests: the engine's command line, the tracker, the code host, the security
screen (it allows every advisory). The agent is a headless `claude -p` session with Read, Grep, Glob and Write."""
import json
import os
import shutil
import subprocess
import sys
import time
import types
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

GROUP = "acme/shop"  # the code host group the case's repositories are listed under
AGENT_TIMEOUT = 2700
AGENT_NOTE = ("\n\n(This is a local test run without the engine: there is nothing to report to and no command to "
              "finish with. You have the Read, Grep, Glob and Write tools only. Write verdicts.json as told above, "
              "then stop.)")
FIX_NOTE = "\n\n(Local test: your report from the last round is in verdicts.json; correct that file and stop.)"


class RunError(Exception):
    pass


def use(arceus: Path) -> None:
    """The checkout's runner and its tests' stand-ins first on the path; what the runner checks of this machine
    (systemd units, the engine's tools, free disk, who owns the engine's folder) is not under test."""
    for p in (arceus / "runner", arceus / "runner" / "src"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from arceus_runner import bulava, health
    bulava._writable_by_us = lambda root: []
    health.shutil = types.SimpleNamespace(which=lambda name: f"/usr/bin/{name}", disk_usage=shutil.disk_usage)
    health.autostart = lambda: []


class Triage:
    """A case's project under the runner, in a state folder of its own. Runs go one at a time: start, then finish."""

    def __init__(self, arceus: Path, case, origin: dict[str, Path], state: Path):
        from arceus_runner import loop
        from arceus_runner.config import Config, Secrets
        from arceus_runner.db import ReviewStore
        from arceus_runner.engine import Engine
        from arceus_runner.events import EventLog
        from arceus_runner.gitops import Git, GitAuth
        from arceus_runner.integrations import build_register
        from tests.conftest import GL_TOKEN, YT_TOKEN, FakeClock, example_raw, providers
        from tests.fakes import FakeGitLab, FakeScreen, FakeYouTrack, json_response

        class OneGroup(FakeGitLab):
            def __call__(self, request):
                path = request.url.raw_path.decode().split("?")[0]
                if path == f"/api/v4/groups/{urllib.parse.quote(GROUP, safe='')}":
                    return json_response({"id": 42, "full_path": GROUP})
                if request.url.path == "/api/v4/groups/42/projects":
                    first = int(request.url.params.get("page", 1)) == 1
                    return json_response([{"id": n + 1, "path": name, "path_with_namespace": f"{GROUP}/{name}",
                                           "default_branch": "main", "archived": False, "description": None,
                                           "http_url_to_repo": str(origin[name])}
                                          for n, name in enumerate(case.repos)] if first else [],
                                         headers={"x-next-page": ""})
                return super().__call__(request)

        (state / "engine" / "bin").mkdir(parents=True)
        for script, cmd in (("dispatch.sh", "dispatch"), ("worker-send.sh", "worker-send"),
                            ("night-shift.sh", "night-shift"), ("claude-usage.sh", "claude-usage"),
                            ("codex-usage.sh", "codex-usage")):
            f = state / "engine" / "bin" / script
            f.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{arceus}/runner/tests/fake_engine.py" {cmd} "$@"\n')
            f.chmod(0o755)
        (state / "bulava.env").write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-not-used\n")
        (state / "bulava.env").chmod(0o600)
        if case.notes():
            shutil.copyfile(case.notes(), state / "instructions.md")
        raw = example_raw()
        raw.pop("slack")
        raw.update(project="local-test", mode="live")
        raw["code_host"].update(group=GROUP, exclude_repos=[])
        raw["paths"] = {"workspace": str(state / "workspace"), "bulava": str(state / "engine"),
                        "bulava_state": str(state / "engine-state"), "bulava_env": str(state / "bulava.env"),
                        "secrets": str(state / "secrets.env"), "db": str(state / "runner.db"),
                        "events": str(state / "events.jsonl")}
        raw["bulava"]["mcp_config"] = None
        raw["health"].pop("devstack_check", None)
        raw["health"].update(disk_fail_percent=1, disk_warn_percent=2)
        replay = case.folder / "advisories.json"  # a case from a real run: its advisories as the run was given them
        register = {"type": "triage_evals.replay", "advisories": str(replay)} if replay.is_file() else \
            {"type": "files", "advisories": str(case.folder / "advisories")}
        raw["secops"] = {"enabled": True, "register": register,
                         "reports": str(state / "secops-reports"), "instructions": str(state / "instructions.md"),
                         "post": False, "slack": False}
        self.cfg = cfg = Config.model_validate(raw)
        secrets = Secrets(tracker=YT_TOKEN, code_host=GL_TOKEN, slack=None, register=None)
        self.clock = FakeClock()
        tracker, host = providers(cfg, secrets, FakeYouTrack(), OneGroup(), self.clock)
        self.store = ReviewStore(cfg.paths.db)
        self.events = EventLog(cfg.paths.events, cfg.project, redact=secrets.values())
        self.runner = loop.Runner(cfg, self.store, self.events, tracker, host, now=lambda: datetime.now(UTC),
                                  mono=self.clock, engine=Engine(cfg, extra_env={}),
                                  git=Git(GitAuth(cfg.code_host.url, "bot", GL_TOKEN), "Local Test",
                                          "local@example.com"),
                                  classify=FakeScreen(), register=build_register(cfg, secrets))

    def _tick(self) -> None:
        self.runner.tick()
        self.clock.advance(600)

    def _engine(self, state: dict | None = None) -> dict:
        f = self.cfg.paths.bulava_state / "fake-engine.json"
        if state is not None:
            f.write_text(json.dumps(state))
        return json.loads(f.read_text()) if f.exists() else {"tasks": {}, "calls": []}

    def start(self) -> dict:
        """Queue a run and let the runner prepare it: what it handed the engine, and where the agent writes."""
        rid = self.store.add_run("secops", "command", "evals").id
        self._tick()
        calls = [c["argv"] for c in self._engine()["calls"] if c["cmd"] == "dispatch" and rid in c["argv"]]
        if not calls:
            run = self.store.run(rid)
            raise RunError(f"the runner started no agent for {rid}: {run.outcome}; {run.reason}")
        argv = calls[-1]
        crit = Path(argv[argv.index("--report-criteria") + 1]).read_bytes().decode("utf-8", errors="replace")
        ws = self.cfg.paths.workspace
        return {"id": rid, "brief": argv[-1], "criteria": crit, "workspace": ws,
                "rounds": int(argv[argv.index("--report-max-rounds") + 1]),
                "report": ws / ".arceus" / "secops" / rid / "verdicts.json"}

    def finish(self, rid: str, receipt: dict | None = None) -> tuple[dict, str]:
        """The engine's task ends (with the review's receipt, if any); the runner reads the report. Its result and
        outcome."""
        state = self._engine()
        state["tasks"][rid].update(state="done", attempt_live=False, **({"receipt": receipt} if receipt else {}))
        self._engine(state)
        for _ in range(8):
            self._tick()
            run = self.store.run(rid)
            if run.state == "done":
                return json.loads(run.result or "{}"), run.outcome
        raise RunError(f"the runner did not finish {rid}: it is {run.state}")

    def close(self) -> None:
        self.events.close()
        self.store.close()


def claude(model: str):
    """The agent: a new headless session for each call, in the workspace, with the brief on stdin."""
    def session(prompt: str, cwd: Path, report: Path) -> dict:
        from arceus_runner.screening import classifier_env
        cmd = ["claude", "-p", "--output-format", "json", "--model", model, "--strict-mcp-config",
               "--setting-sources", "project", "--disable-slash-commands", "--no-session-persistence",
               "--tools", "Read,Grep,Glob,Write", "--permission-mode", "acceptEdits"]
        t0 = time.monotonic()
        try:
            r = subprocess.run(cmd, input=prompt, cwd=cwd, env=classifier_env({"TMPDIR": os.environ["TMPDIR"]}),
                               capture_output=True, text=True, timeout=AGENT_TIMEOUT)
            said = json.loads(r.stdout)
        except (subprocess.TimeoutExpired, ValueError):
            said = {}
        return {"seconds": round(time.monotonic() - t0), "model": " ".join(sorted(said.get("modelUsage") or {})) or "?",
                "turns": said.get("num_turns"), "cost_usd": said.get("total_cost_usd")}
    return session


def canned(path: str):
    """A stand-in agent: the file is its verdicts.json, every session."""
    def session(prompt: str, cwd: Path, report: Path) -> dict:
        shutil.copyfile(path, report)
        return {"seconds": 0, "model": "stand-in"}
    return session

import json
import os
from pathlib import Path

import pytest

from triage_evals import cli, engine, runner

ARCEUS, ENGINE = os.environ.get("ARCEUS_DIR"), os.environ.get("ENGINE_DIR")
if not (ARCEUS and ENGINE):
    raise pytest.UsageError("set ARCEUS_DIR (an Arceus checkout with its runner's virtualenv) and ENGINE_DIR (the "
                            "engine's source) and run pytest with that checkout's Python: see README.md")
RECORDED = json.loads((Path(__file__).parent / "data" / "recorded-reviews.json").read_text())
(Path(__file__).resolve().parents[1] / ".work").mkdir(exist_ok=True)  # pytest.ini puts pytest's --basetemp in it


@pytest.fixture
def gate() -> str:
    return (engine.source(Path(ARCEUS), ENGINE, Path()) / engine.GATE).read_text()


@pytest.fixture
def evals(tmp_path, monkeypatch):
    """`./evals run ...` in this process, its work folder under tmp_path: the result file it wrote, as JSON. A real
    `codex` or `claude` is never reached: tmp_path/bin comes first on the PATH, the agent's too, and its two fail
    (a test may put a fake of its own there)."""
    monkeypatch.setenv("EVALS_WORK", str(tmp_path / "work"))
    monkeypatch.setenv("TMPDIR", str(tmp_path / "work" / "tmp"))
    (tmp_path / "bin").mkdir()
    for name in ("codex", "claude"):
        (tmp_path / "bin" / name).write_text(f"#!/bin/sh\necho 'a test reached the real {name}' >&2\nexit 99\n")
        (tmp_path / "bin" / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    runner.use(Path(ARCEUS))
    from arceus_runner import screening
    real = screening.classifier_env
    monkeypatch.setattr(screening, "classifier_env",
                        lambda base: {**real(base), "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"})

    def run(*args: str) -> dict:
        out = tmp_path / f"result-{len(list(tmp_path.glob('result-*')))}.json"
        assert cli.main(["run", *args, "--samples", "1", "--arceus", ARCEUS, "--engine", ENGINE,
                         "--out", str(out)]) == 0
        assert not any((tmp_path / "work" / "runs").iterdir()), "the run's scratch folder is left behind"
        return json.loads(out.read_text())
    return run

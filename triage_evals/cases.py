"""Cases as data. A folder per project under cases/ (or cases-private/, which git ignores) holds the repositories as
plain file trees (repos/<name>/), the advisories as OSV records (advisories/) or, for a case taken from a real run, as
the run was given them (advisories.json, replay.py), the team's notes (notes.md), prepared
reports, and case.toml: its reviewer cases and its answer key for the agent and e2e evals, each entry with its `why`."""
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("cases", "cases-private")
WORDS = ("affected", "fixed", "not_affected", "needs_review", "none")  # "none": no verdict
DATE = "2026-11-01T00:00:00+00:00"  # the author and date of every case commit: the same commits every time


class CaseError(Exception):
    pass


@dataclass
class Case:
    id: str          # <folder>/<name> for a reviewer case, <folder> for the answer key
    kind: str        # "reviewer", or "agent" for the agent and e2e evals
    folder: Path
    repos: list[str]
    spec: dict       # the [[reviewer]] entry, or the [agent] table with `key`: {"<advisory>/<repo>": [words]}
    hash: str

    def notes(self) -> Path | None:
        path = self.folder / self.spec.get("notes", "notes.md")
        return path if path.is_file() else None


def load(root: Path = ROOT, folders: tuple[str, ...] = FOLDERS) -> list[Case]:
    out = [c for top in folders for toml in sorted((root / top).glob("*/case.toml")) for c in _read(toml)]
    ids = [c.id for c in out]
    if len(set(ids)) != len(ids):
        raise CaseError(f"two cases have the same name: {sorted({i for i in ids if ids.count(i) > 1})}")
    return out


def select(cases: list[Case], kind: str, glob: str) -> list[Case]:
    return [c for c in cases if c.kind == kind and fnmatch.fnmatchcase(c.id, glob)]


def _need(path: Path, entry: dict, *keys: str) -> None:
    missing = [k for k in keys if k not in entry]
    if missing:
        raise CaseError(f"{path}: an entry has no {', '.join(missing)}: {entry}")


def _read(path: Path) -> list[Case]:
    folder = path.parent
    try:
        d = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as err:
        raise CaseError(f"{path}: {err}") from None
    repos = d.get("repos") or sorted(p.name for p in (folder / "repos").iterdir() if p.is_dir())
    h = digest(folder)
    out = []
    for r in d.get("reviewer", []):
        _need(path, r, "name", "report", "verdict", "why")
        if r["verdict"] not in ("PASS", "FAIL"):
            raise CaseError(f"{path}: {r['name']} expects {r['verdict']!r}, not PASS or FAIL")
        for o in r.get("must", []) + r.get("must_not", []):
            _need(path, o, "patterns", "means")
        out.append(Case(f"{folder.name}/{r['name']}", "reviewer", folder, repos, r, h))
    if "agent" in d:
        replay = folder / "advisories.json"
        ids = [a["id"] for a in json.loads(replay.read_text())] if replay.is_file() else \
            [json.loads(p.read_text())["id"] for p in sorted((folder / "advisories").glob("*.json"))]
        key = {f"{a}/{r}": ["none"] for a in ids for r in repos}  # a cell not listed expects no verdict
        for c in d["agent"].get("cell", []):
            _need(path, c, "advisory", "verdict", "why")
            words = [c["verdict"]] if isinstance(c["verdict"], str) else c["verdict"]
            for repo in [c["repo"]] if "repo" in c else repos:  # no `repo`: every repository
                cell = f"{c['advisory']}/{repo}"
                if cell not in key or set(words) - set(WORDS):
                    raise CaseError(f"{path}: {cell} {words} is not a cell of this case with one of {WORDS}")
                key[cell] = words
        for c in d["agent"].get("checked", []):
            _need(path, c, "advisory", "patterns", "why")
        out.append(Case(folder.name, "agent", folder, repos, {**d["agent"], "key": key}, h))
    return out


def digest(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(folder).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:12]


def materialize(case: Case, dest: Path) -> dict[str, Path]:
    """Each repository of the case as a git repository under dest: one commit, by a fixed author on a fixed date,
    with no user or system git configuration, so its id is the same on every run and machine."""
    env = {**os.environ, "GIT_AUTHOR_DATE": DATE, "GIT_COMMITTER_DATE": DATE,
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    out = {}
    for name in case.repos:
        d = dest / name
        shutil.copytree(case.folder / "repos" / name, d, symlinks=True)  # a real tree may hold dangling links
        # -f: a file the project tracks although its .gitignore matches it is part of the tree too
        for args in (["init", "-q", "-b", "main"], ["add", "-A", "-f"], ["commit", "-q", "-m", "The project as it is"]):
            subprocess.run(["git", "-c", "user.name=Case", "-c", "user.email=case@example.com", *args], cwd=d,
                           env=env, check=True, capture_output=True)
        out[name] = d
    return out

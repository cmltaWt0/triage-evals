# triage-evals

Evals for the advisory triage of Arceus: its SecOps agent reads a project's code against open security advisories and
writes a verdict per advisory and repository, and before the run ends the engine has a second model review that
report. Arceus's own tests check the runner with a stand-in engine and a hand-written report; no model is called.
Whether the **agent** judges a project rightly, and whether the **reviewer** accepts or rejects a report as intended,
can only be measured by running the models, several times, against cases with known answers. That is what this does.

**Everything under `cases/` is invented.** The projects and their repositories do not exist, and no advisory there
describes a real vulnerability, also where it names real software (APT) with version numbers. The other package names
(`pixloom`, `queuemaster`, `gitpebble`, `tokenbrine`) were in no public registry when they were chosen. Do not install what the
invented repositories list, and do not feed the advisory records to a scanner or an advisory database.

**Not deterministic.** The same case can pass twice and fail once: each case runs three times by default; read the
rates, never a single run. Every sample costs subscription usage: a full reviewer run is 42 Codex calls of 15 to 30
seconds, an agent sample about a minute of Claude, an end-to-end sample that and two or three Codex calls. A plan's
usage limit can end a run early: a sample then has no verdict and an `error` that says so, and its rate means nothing.
Count the calls before a batch and run one eval at a time.

**Reproduced from the engine.** The report review's prompt is cut out of the engine's gate script
(`hooks/review-gate.sh`, stage `gate.reportReview`), never retyped; a piece of it not found exactly once stops the eval
with an error that names it. Its clips (6,000 bytes of the brief, 8,000 of the criteria), its `find-report`,
`report-text` and `review-ledger.py` tools, its Codex call (`codex exec --sandbox read-only`, web search on, 480 s), how
it reads a verdict (whole header lines in the first eight; PASS needs `STATE: COMPLETE`), the ledger of open objections
across rounds, the text that sends a failed report back, and acceptance with notes at the round limit. The runner is
the checkout's own code: it prepares the run, writes the brief, `advisories.json` and `notes.md`, reads
`verdicts.json`, checks every reference against the commit read, and decides the outcome.

**Not reproduced.** No dispatch, no tmux session, no stop hook: a failed report goes to a new agent session with the
engine's words, not back to the same one. The pipeline's stages before the agent are not run. The agent is a headless
`claude -p` session in the workspace with the Read, Grep, Glob and Write tools only. Not the engine's Claude stand-in
reviewer, nor its parking of an unreachable reviewer (here a review with no verdict ends the sample), nor its repair of
a prompt that is not valid UTF-8. The tracker, the code host, the security screen (it lets every advisory through) and
the engine's command line are the stand-ins from Arceus's own tests.

## What it needs

- An Arceus checkout with its runner's virtualenv (`runner/.venv`): `--arceus DIR` or `ARCEUS_DIR`. `./evals run`
  restarts itself with that Python.
- `codex` and `claude` on the PATH, signed in.
- The engine's source: `--engine DIR`, or else the commit the checkout pins in `setup/setup.conf.example`
  (`BULAVA_SOURCE`, `BULAVA_REF`) is fetched once into the work folder.
- The work folder is `.work/` here (or `EVALS_WORK`); every temporary file goes there, never to `/tmp`.

## The three evals

```sh
./evals run reviewer [--cases 'shop/*'] [--samples 3] [--review-model M] [--review-effort E]
./evals run agent    [--cases shop] [--agent-model opus]
./evals run e2e      [--cases 'shop*']
```

- **reviewer**: a reviewer case's prepared report goes through round 1 of the review, `--samples` times. Scored: the
  verdict against the expected one; the case's named objections are reported apart.
- **agent**: the agent triages the case's project through the runner's own brief, a new run each sample. Scored: every
  cell (advisory, repository) of the answer key against the verdicts the runner kept, and no problem found by the
  runner (a reference that does not exist, a verdict left out). The `checked` patterns, and the cells whose word changed
  between samples, are reported apart.
- **e2e**: the agent, then the review rounds the runner asks for; a failed report goes to a new agent session until it
  passes or the limit accepts it with notes. Scored: whether it passed (and in which round) and the final verdicts.

`--cases` is a glob over case names: `shop/clean-follows-notes` is a reviewer case, `shop` a project's answer key.
`--reviewer-answer FILE` and `--agent-answer FILE` put a file's content in place of Codex's answer or the agent's
`verdicts.json`, to try the harness without spending anything.

## Results

A run writes one JSON file, `results/<eval>-<time>-<commit>.json` or `--out`: what it ran on (the Arceus commit and
whether it had local changes, the engine's commit and the pinned one, the Codex and Claude versions, the models and
efforts asked for and as the CLIs reported them, the date, the cases' content hash), and every sample of every case:
the verdict or the verdicts, the review's text, the seconds, what was expected and the score. Then it prints the report.

```sh
./evals report results/reviewer-20261124-101037-0f12cdb.json
./evals compare results/baselines/reviewer-0f12cdb.json results/reviewer-20261125-090000-d1e2f3a.json
```

`report` prints a Markdown table, as readable in a terminal: per case the pass rate (`3/3`) and what happened (the
verdicts in order, the wrong cells, the rounds), then the eval's total. `compare` shows both rates per case, marks a
rate that fell or rose and a case whose content changed, lists what changed in the target, and exits 1 when any case's
rate fell. **A baseline** is a result file in `results/baselines/`, the only part of `results/` git keeps: run the eval
on the version to keep, copy its file there under a name that says what it is, and commit it.

## Cases

A folder per project under `cases/`. `cases-private/` is searched the same way and git ignores it: a real project's
cases go there and never leave the machine. To add one, make the folder with:

- `repos/<name>/`: each repository as a plain file tree. The harness makes a git repository of each, one commit with a
  fixed author and date, so its commits are the same every time.
- `advisories/`: one OSV record per `.json` file (the runner's `files` register reads them).
- `notes.md`: the team's notes, if any; a reviewer case may name another file with `notes`.
- the prepared reports its reviewer cases name, as `verdicts.json` files.
- `case.toml`: `repos` (in the order the code host lists them), then the cases, each entry with a one-line `why`:

```toml
[[agent.cell]]                    # the answer key; a cell not listed expects no verdict
advisory = "x_SHOP-2026-0011"
repo = "shop-api"                 # left out: every repository
verdict = "affected"              # or a list of acceptable words; "none" is no verdict
why = "requirements.txt pins an affected pixloom and app/main.py uses it"

[[agent.checked]]                 # every pattern must match the advisory's `checked` note
advisory = "x_SHOP-2026-0012"
patterns = ['shop-api', '(?i)build[- ]only']
why = "the notes ask the note to name what their rule left out"

[[reviewer]]                      # the case shop/follows-notes
name = "follows-notes"
report = "reports/follows-notes.json"
earlier = "reports/earlier.json"  # optional: a first run's report, whose verdicts the reviewed run gets as `earlier`
verdict = "FAIL"
why = "the hosts' APT gets no needs_review"

[[reviewer.must_not]]             # or [[reviewer.must]]: a named objection, there when every pattern matches
patterns = ['(?i)no such rule']
means = "objects to the build and CI exclusion"
```

Then `./evals run agent --cases <folder> --agent-answer <a report>` tries it without a model. The named objections and
the `checked` patterns are regular expressions over free text: a heuristic, kept out of the score; check a new one
against real review texts first. The three invented projects here (`shop`; `shop-variant`, where a tool installed in
the final image is invoked by the application; `shop-setting`, where that tool clones only a URL fixed in the code and
a library is affected only with a setting that is decided at run time) keep their quirks: a final image stage that
copies a manifest without installing it is part of the case, not a bug to fix.

An invented advisory must not be taken for a real one. Give it no alias in the form of a CVE or GHSA id, name a
package that is in no public registry (look it up in the ecosystem the record names and in PyPI, npm and crates.io
before choosing), and say in `database_specific.note` that it is invented: the runner does not pass that field on, so
no model reads it. A test holds the cases here to the alias and the note.

## Tests

No model and no network; the run path uses the stand-ins:

```sh
ARCEUS_DIR=~/src/arceus ENGINE_DIR=~/src/engine $ARCEUS_DIR/runner/.venv/bin/python -m pytest
```

## Licence

**FSL-1.1-ALv2**: the Functional Source License with an Apache 2.0 future grant, the licence Arceus and its engine
use. See [LICENSE](LICENSE). In short: run it, read it, change it and pass it on for anything but a commercial product
or service that competes with it; two years after a version is published, that version is available under Apache 2.0
as well.

The licence covers what is in this repository: the harness, the cases and the recorded results. Arceus and the engine
are not in it: the evals run the checkouts they are given, and each comes under its own licence, FSL-1.1-ALv2 too.
One exception: `triage_evals/engine.py`, `tests/test_engine.py` and `tests/test_run.py` quote short phrases of the
engine's `hooks/review-gate.sh`, to find its prompt in that file and to test that. Those phrases are from
[Bulava](https://github.com/Stepanokdev/bulava), Copyright 2026 Ivan Stepanok, under its
[licence](https://github.com/Stepanokdev/bulava/blob/main/LICENSE).

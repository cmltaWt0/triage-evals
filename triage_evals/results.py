"""A result file read by a person: `report` prints it as a Markdown table, which reads as well in a terminal;
`compare` shows what changed between two, case by case, and says whether a case's pass rate fell."""
import json
from pathlib import Path


def load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _rate(c: dict | None) -> str:
    return f"{c['passed']}/{c['of']}" if c else "—"


def _detail(kind: str, c: dict) -> str:
    s = c["samples"]
    secs = f"{round(sum(x['seconds'] for x in s) / len(s))} s a sample"
    if kind == "reviewer":
        parts = [" ".join(x["verdict"] or "none" for x in s) + f" (expected {c['expected']['verdict']})"]
        if s[0]["objections_ok"] is not None:
            parts.append(f"objections as named {sum(bool(x['objections_ok']) for x in s)}/{len(s)}")
        return " · ".join([*parts, secs])
    misses = sorted({f"{m} got {x['words'][m]}" for x in s for m in x["misses"]})
    parts = [f"problems {sum(len(x['problems']) for x in s)}",
             *([f"notes as named {sum(all(n['found'] for n in x['checked']) for x in s)}/{len(s)}"]
               if s[0]["checked"] else []),
             *([f"changed between samples: {', '.join(c['flips'])}"] if c["flips"] else []),
             *([f"wrong: {'; '.join(misses)}"] if misses else [])]
    if kind == "e2e":
        parts[:0] = ["review passed in round " + ", ".join(str(x["passed_round"] or "–") for x in s),
                     f"verdicts right {sum(x['verdicts_ok'] for x in s)}/{len(s)}"]
    return " · ".join([*parts, secs])


def report(res: dict) -> str:
    t, o = res["target"], res["options"]
    lines = [f"## {res['eval']} eval, {res['date']}", "",
             f"Arceus `{t['arceus'][:12]}`{' (with local changes)' if t['arceus_dirty'] else ''} · engine "
             f"`{t['engine'][:12]}` (pinned `{(t['engine_pinned'] or '?')[:12]}`) · codex {t['codex'] or '—'} · "
             f"claude {t['claude'] or '—'} · reviewer {', '.join(res['reported']['reviewer']) or '—'} · agent "
             f"{', '.join(res['reported']['agent']) or '—'} · {o['samples']} sample(s) a case · cases "
             f"`{res['cases_hash']}`", "", "| case | passed | detail |", "|---|---|---|"]
    lines += [f"| {c['id']} | {_rate(c)} | {_detail(res['eval'], c)} |" for c in res["cases"]]
    total = {"passed": sum(c["passed"] for c in res["cases"]), "of": sum(c["of"] for c in res["cases"])}
    lines.append(f"| **total** | **{_rate(total)}** | {sum(c['passed'] == c['of'] for c in res['cases'])} of "
                 f"{len(res['cases'])} cases in every sample |")
    return "\n".join(lines)


def compare(old: dict, new: dict) -> tuple[str, bool]:
    """The table of both pass rates, and whether any case's rate fell."""
    if old["eval"] != new["eval"]:
        raise SystemExit(f"these are results of two evals ({old['eval']}, {new['eval']}), not comparable")
    changed = [f"{k}: {old['target'].get(k)} → {v}" for k, v in new["target"].items() if old["target"].get(k) != v]
    if old["reported"] != new["reported"]:
        changed.append(f"models: {old['reported']} → {new['reported']}")
    lines = [f"## {new['eval']} eval: {old['date']} → {new['date']}", "", *(f"- {x}" for x in changed), "",
             "| case | old | new | |", "|---|---|---|---|"]
    a, b = {c["id"]: c for c in old["cases"]}, {c["id"]: c for c in new["cases"]}
    fell = False
    for cid in sorted(a.keys() | b.keys()):
        x, y, note = a.get(cid), b.get(cid), ""
        if x and y:
            d = y["passed"] * x["of"] - x["passed"] * y["of"]
            fell |= d < 0
            note = ("**fell**" if d < 0 else "rose" if d > 0 else "") + (" (the case changed)"
                                                                        if x["hash"] != y["hash"] else "")
        lines.append(f"| {cid} | {_rate(x)} | {_rate(y)} | {note.strip()} |")
    return "\n".join(lines), fell

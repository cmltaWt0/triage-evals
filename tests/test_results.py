import json

from triage_evals import cli, results


def result(date: str, rates: dict[str, tuple[int, int, str]], arceus: str = "a" * 40) -> dict:
    return {"eval": "reviewer", "date": date, "target": {"arceus": arceus}, "reported": {"reviewer": ["m"]},
            "cases": [{"id": cid, "passed": p, "of": n, "hash": h} for cid, (p, n, h) in rates.items()]}


def test_compare_names_each_change_and_fails_when_a_rate_fell(tmp_path):
    old = result("d1", {"x/kept": (3, 3, "h"), "x/fell": (3, 3, "h"), "x/rose": (1, 3, "h"), "x/gone": (2, 3, "h")})
    new = result("d2", {"x/kept": (3, 3, "h"), "x/fell": (4, 5, "h"), "x/rose": (2, 3, "h2"), "x/new": (0, 3, "h")},
                 arceus="b" * 40)
    text, fell = results.compare(old, new)
    assert fell
    assert "| x/fell | 3/3 | 4/5 | **fell** |" in text and "| x/kept | 3/3 | 3/3 |  |" in text
    assert "| x/rose | 1/3 | 2/3 | rose (the case changed) |" in text
    assert "| x/gone | 2/3 | — |  |" in text and "| x/new | — | 0/3 |  |" in text
    assert f"- arceus: {'a' * 40} → {'b' * 40}" in text
    for name, res in (("old", old), ("new", new), ("same", result("d3", {"x/fell": (2, 2, "h")}))):
        (tmp_path / f"{name}.json").write_text(json.dumps(res))
    assert cli.main(["compare", str(tmp_path / "old.json"), str(tmp_path / "new.json")]) == 1
    assert cli.main(["compare", str(tmp_path / "old.json"), str(tmp_path / "same.json")]) == 0

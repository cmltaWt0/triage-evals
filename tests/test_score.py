import json

from conftest import RECORDED
from triage_evals import cases, engine, score

CASES = {c.id: c for c in cases.load(folders=("cases",))}


def scored(cid: str, texts: list[str]) -> list[dict]:
    return [score.reviewer({"verdict": engine.parse(t)[0], "text": t}, CASES[cid].spec) for t in texts]


def test_recorded_reviews_score_as_they_were_measured():
    """The reviews Codex wrote on Arceus c6b9bb3 (and on fcc7554 for follows-notes) meet every expectation; on the
    base c28c8fb, which gave the reviewer no notes, the two PASS cases failed."""
    for commit in ("c6b9bb3", "fcc7554"):
        for cid, texts in RECORDED[commit].items():
            assert [(s["ok"], s["objections_ok"] in (True, None)) for s in scored(cid, texts)] == [(True, True)] * 3
    for cid, texts in RECORDED["c28c8fb"].items():
        assert [(s["verdict"], s["ok"]) for s in scored(cid, texts)] == [("FAIL", False)] * 3


def test_a_review_that_objects_to_the_build_exclusion_is_named():
    objecting = [t for texts in RECORDED["c28c8fb"].values() for t in texts]  # no notes: the exclusion disputed
    res = scored("shop/follows-notes", objecting)
    assert all(s["ok"] and s["must_not"][0]["found"] and s["objections_ok"] is False for s in res)
    kept = scored("shop/follows-notes", RECORDED["fcc7554"]["shop/follows-notes"])
    assert not any(s["must_not"][0]["found"] for s in kept)
    missing = scored("shop/vague-note", RECORDED["c6b9bb3"]["shop/rule-not-in-notes"])
    assert [s["must"][0]["found"] for s in missing] == [False] * 3


def agent_on(report: str, problems=()) -> dict:
    found = json.loads((CASES["shop"].folder / "reports" / report).read_text())
    return score.agent({**found, "problems": list(problems)}, "attention", CASES["shop"].spec, {"seconds": 1})


def test_the_answer_key_takes_every_cell():
    assert agent_on("clean-follows-notes.json")["ok"]
    res = agent_on("follows-notes.json")
    assert not res["ok"] and res["misses"] == ["x_SHOP-2026-0011/shop-deploy", "x_SHOP-2026-0012/shop-deploy"]
    assert res["words"]["x_SHOP-2026-0013/shop-web"] == "none" and res["checked"] == [
        {"advisory": "x_SHOP-2026-0012", "found": True}]
    assert agent_on("left-out-unsaid.json")["checked"][0]["found"] is False
    assert not agent_on("clean-follows-notes.json", ["`app/main.py:99` does not exist"])["ok"]
    two = [agent_on("clean-follows-notes.json"), agent_on("follows-notes.json")]
    assert score.flips(two) == {"x_SHOP-2026-0011/shop-deploy": {"needs_review": 1, "none": 1},
                                "x_SHOP-2026-0012/shop-deploy": {"needs_review": 1, "none": 1}}

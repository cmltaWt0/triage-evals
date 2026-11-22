import json
import re
import shutil
import subprocess

import pytest

from triage_evals import cases


def test_the_cases_load_with_their_answer_key():
    by = {c.id: c for c in cases.load()}
    assert sorted(by) == ["shop", "shop-setting", "shop-setting/affected-on-a-runtime-setting",
                          "shop-setting/follows-the-code", "shop-variant",
                          "shop-variant/affected-after-needs-review", "shop-variant/affected-after-needs-review-said",
                          "shop-variant/affected-by-what-ships", "shop-variant/misapplied-rule",
                          "shop-variant/needs-review-for-what-ships", "shop-variant/not-affected-on-a-claim",
                          "shop/clean-follows-notes",
                          "shop/earlier-verdict-turned-by-notes", "shop/follows-notes", "shop/image-left-out",
                          "shop/left-out-unsaid",
                          "shop/rule-not-in-notes", "shop/two-left-out", "shop/vague-note"]
    key = by["shop"].spec["key"]
    assert len(key) == 9 and key["x_SHOP-2026-0011/shop-api"] == ["affected"]
    assert key["x_SHOP-2026-0011/shop-web"] == ["none"]  # not listed: no verdict
    assert by["shop-variant"].spec["key"]["x_SHOP-2026-0014/shop-deploy"] == ["needs_review", "none"]
    assert by["shop/earlier-verdict-turned-by-notes"].notes().name == "notes-earlier.md"
    assert [c.id for c in cases.select(list(by.values()), "agent", "shop*")] == ["shop", "shop-setting", "shop-variant"]


@pytest.mark.parametrize("entry, says", [
    ('[[reviewer]]\nname = "x"\nreport = "r.json"\nverdict = "FAIL"\n', "no why"),
    ('[[agent.cell]]\nadvisory = "x_SHOP-2026-0011"\nrepo = "shop-app"\nverdict = "affected"\nwhy = "w"\n',
     "not a cell of this case"),
])
def test_a_case_that_says_less_than_it_must_is_refused(tmp_path, entry, says):
    shutil.copytree(cases.ROOT / "cases" / "shop", tmp_path / "cases" / "broken")
    (tmp_path / "cases" / "broken" / "case.toml").write_text(entry)
    with pytest.raises(cases.CaseError, match=says):
        cases.load(tmp_path)


def test_a_case_makes_the_same_commits_every_time(tmp_path):
    case = next(c for c in cases.load() if c.id == "shop")
    heads = {name: subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True,
                                  text=True).stdout.strip() for name, d in cases.materialize(case, tmp_path).items()}
    assert heads == {"shop-api": "8294042137b67dd07fed4a6a1e9ec39ed789170c",
                     "shop-web": "69ab21f03df2f7d8b5c26cc4c62cd2a7b286c72c",
                     "shop-deploy": "17adfad43a40a60066dfc4515bab48c6a2bbfe40"}


def test_the_content_hash_follows_every_file(tmp_path):
    shutil.copytree(cases.ROOT / "cases" / "shop", tmp_path / "shop")
    assert cases.digest(tmp_path / "shop") == cases.digest(cases.ROOT / "cases" / "shop")
    with open(tmp_path / "shop" / "repos" / "shop-web" / "package.json", "a") as f:
        f.write(" ")
    assert cases.digest(tmp_path / "shop") != cases.digest(cases.ROOT / "cases" / "shop")


def test_an_invented_advisory_cannot_be_taken_for_a_real_one():
    """What the README asks of the cases here: no alias in the form of a real identifier, and a note, which the
    runner's reading of the record drops, so no model sees it."""
    from arceus_runner.advisory_files import read_record
    paths = sorted((cases.ROOT / "cases").glob("*/advisories/*.json"))
    assert len(paths) == 12
    for path in paths:
        rec = json.loads(path.read_text())
        assert "invented" in rec["database_specific"]["note"].lower(), path
        assert not [a for a in rec["aliases"] if re.match(r"(?i)(CVE|GHSA)-", a)], path
        assert "nvented" not in repr(read_record(path)), path

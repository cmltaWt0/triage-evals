"""An advisory register that gives the advisories a real triage run was given, as that run's advisories.json held them
(`id`, `ref`, `title`, `facts`, `text`; `earlier` is the runner's to make), so a case taken from a real run puts the
same advisories before the agent and the reviewer, ids and facts unchanged. The runner names it by its module:
`secops.register: {type: triage_evals.replay, advisories: <the case's advisories.json>}`. It takes no verdicts."""
import json

from arceus_runner.config import AdvisoryRegisterConfig, ExpandedPath
from arceus_runner.integrations import Advisory, RegisterType


class ReplayConfig(AdvisoryRegisterConfig):
    advisories: ExpandedPath


class Replay:
    receives = False
    max_evidence = 4000  # what the real registers take

    def __init__(self, cfg: ReplayConfig):
        self.cfg = cfg

    def open(self) -> list[Advisory]:
        return [Advisory(id=a["id"], ref=a["ref"], title=a["title"], text=a["text"], facts=a.get("facts") or {},
                         changed="replayed") for a in json.loads(self.cfg.advisories.read_bytes())]

    def send(self, advisory, repo, verdict, evidence) -> None:
        raise AssertionError("a replayed register takes no verdicts")

    def latest(self, advisory, repo):
        return None

    def check(self, scope: str, post: bool) -> list:
        return []

    def close(self) -> None:
        pass


REGISTER = RegisterType(config=ReplayConfig, build=lambda section, token, http, transport=None: Replay(section))

import os

from tokenbrine import Verifier

verifier = Verifier(legacy=os.environ.get("TOKENBRINE_LEGACY") == "1")


def user_of(token: str) -> str:
    return verifier.verify(token)["sub"]

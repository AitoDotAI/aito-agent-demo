"""Read-only repro: an unseen word must not erase the matching probe evidence."""

import json
from contextlib import closing

from scripts.v2_relate_check import v2_config
from src.aito_client import AitoClient


def check(client: AitoClient) -> dict:
    cases = []
    errors = []
    for text in ("water", "water zzzmigrationunseen", "dropped water"):
        response = client._request("POST", client._path("_similarity"), {
            "from": "resolutions", "similarity": {"text": text},
            "select": ["text", "kb_article", "$score"], "limit": 2,
        })
        hits = response.get("hits", [])
        cases.append({"text": text, "hits": hits})
        if not any(h.get("kb_article") == "water_damage" for h in hits):
            errors.append(f"{text!r}: no water_damage neighbour in top 2")
    return {"cases": cases, "errors": errors}


def main() -> int:
    try:
        with closing(AitoClient(v2_config())) as client:
            result = check(client)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return int(bool(result["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())

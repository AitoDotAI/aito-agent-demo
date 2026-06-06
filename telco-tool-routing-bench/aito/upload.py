"""Create the `tickets` table and batch-upload the TRAIN split only.

Never uploads VAL or TEST. Asserts the row count after upload equals the TRAIN
size — if Aito silently dropped rows, we want to know.

    python -m aito.upload          # create + upload
    python -m aito.upload --recreate  # drop existing table first

Uses the write key (config.aito_write_key(), falls back to AITO_API_KEY).
"""

from __future__ import annotations

import json
import sys

import httpx

from bench import config
from aito.schema import TABLE_NAME, TICKETS_SCHEMA, row_for_upload


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=config.aito_url(),
        headers={"x-api-key": config.aito_write_key(), "content-type": "application/json"},
        timeout=60.0,
    )


def _table_exists(http: httpx.Client) -> bool:
    r = http.get("/api/v1/schema")
    assert r.status_code < 400, f"schema GET failed {r.status_code}: {r.text[:200]}"
    return TABLE_NAME in r.json().get("schema", {})


def _row_count(http: httpx.Client) -> int:
    # _query with no filter returns total; use aggregate count for robustness
    r = http.post("/api/v1/_query", json={"from": TABLE_NAME, "limit": 0})
    assert r.status_code < 400, f"_query failed {r.status_code}: {r.text[:200]}"
    data = r.json()
    assert "total" in data, f"unexpected _query shape: {str(data)[:200]}"
    return int(data["total"])


def create_table(http: httpx.Client, recreate: bool) -> None:
    if _table_exists(http):
        if not recreate:
            print(f"table '{TABLE_NAME}' exists; use --recreate to drop it first")
            return
        r = http.delete(f"/api/v1/schema/{TABLE_NAME}")
        assert r.status_code < 400, f"drop failed {r.status_code}: {r.text[:200]}"
        print(f"dropped existing table '{TABLE_NAME}'")
    r = http.put(f"/api/v1/schema/{TABLE_NAME}", json=TICKETS_SCHEMA)
    assert r.status_code < 400, f"create table failed {r.status_code}: {r.text[:300]}"
    print(f"created table '{TABLE_NAME}'")


def upload_rows(http: httpx.Client, tickets: list[dict]) -> int:
    """Batch-upload an arbitrary list of dataset tickets (used by upload_train and
    by the learning-curve experiment, which uploads TRAIN subsets)."""
    rows = [row_for_upload(t) for t in tickets]
    r = http.post(f"/api/v1/data/{TABLE_NAME}/batch", json=rows)
    assert r.status_code < 400, f"batch upload failed {r.status_code}: {r.text[:300]}"
    return len(rows)


def upload_train(http: httpx.Client) -> int:
    train = json.loads((config.DATA_DIR / "train.json").read_text())
    return upload_rows(http, train)


def main() -> None:
    recreate = "--recreate" in sys.argv
    with _client() as http:
        create_table(http, recreate=recreate)
        expected = upload_train(http)
        actual = _row_count(http)
        assert actual == expected, (
            f"row count after upload = {actual}, expected TRAIN size {expected}. "
            f"Aito dropped or duplicated rows — stop and investigate."
        )
        print(f"uploaded TRAIN: {actual} rows (matches expected {expected})")


if __name__ == "__main__":
    main()

"""Deterministic JSON encoding for persisted identities and exact comparisons."""

import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

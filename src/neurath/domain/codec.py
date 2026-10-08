"""Explicit JSON codecs shared by persistence and transport adapters."""

from typing import Any

from .errors import ValidationError
from .models import ENTITY_TYPES, Criterion, Entity, Phase


def entity_from_dict(kind: str, payload: dict[str, Any]) -> Entity:
    if kind not in ENTITY_TYPES:
        raise ValidationError(f"Unknown entity kind: {kind}")
    values = dict(payload)
    if kind == "task":
        values["criteria"] = [Criterion(**item) for item in values["criteria"]]
        values["phases"] = [Phase(**item) for item in values.get("phases", [])]
    return ENTITY_TYPES[kind](**values)

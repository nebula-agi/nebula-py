from __future__ import annotations

from typing import Any, Union, get_args, get_origin

from pydantic import TypeAdapter, ValidationError


def validate_response(annotation: Any, raw: Any) -> Any:
    """Validate a raw wire payload against a response annotation.

    For ``Union`` annotations, score each candidate variant by how well the
    payload's keys line up with the variant's fields (weighting required-field
    matches) so an optional-only variant can't greedily swallow an unrelated
    dict shape. Plain annotations validate directly via ``TypeAdapter``.
    """
    if get_origin(annotation) is Union:
        candidates: list[tuple[int, Any]] = []
        raw_keys = set(raw) if isinstance(raw, dict) else set()
        for variant in get_args(annotation):
            try:
                value = TypeAdapter(variant).validate_python(raw)
            except ValidationError:
                continue
            fields = getattr(variant, "model_fields", None)
            if isinstance(fields, dict) and raw_keys:
                known = raw_keys & set(fields)
                if not known:
                    continue
                required_known = sum(
                    1 for name in known if fields[name].is_required()
                )
                candidates.append((len(known) * 2 + required_known, value))
            else:
                candidates.append((1, value))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        raise ValueError("response did not match any union variant")
    return TypeAdapter(annotation).validate_python(raw)

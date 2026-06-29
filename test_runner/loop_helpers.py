"""Loop iteration variable bindings shared by runtime and dry_run."""

from __future__ import annotations

from typing import Any


def loop_index_bindings(
    index: int,
    index_var: str | None,
    *,
    count_mode: bool,
) -> dict[str, Any]:
    """Return loop index variables injected for one iteration.

    When ``index_as`` is omitted:
    - ``count`` loops: ``i`` and ``qi`` (batch-index convention in docs)
    - ``over`` loops: ``i`` only
    """
    if index_var:
        return {str(index_var): index}

    bindings: dict[str, Any] = {"i": index}
    if count_mode:
        bindings["qi"] = index
    return bindings


def loop_temp_index_keys(index_var: str | None, *, count_mode: bool) -> set[str]:
    """Keys that loop injects and should not leak as persisted body vars."""
    if index_var:
        return {str(index_var)}
    keys = {"i"}
    if count_mode:
        keys.add("qi")
    return keys

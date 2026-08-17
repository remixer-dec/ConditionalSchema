"""Condition value objects, sentinels, and helpers."""

from typing import Any, Dict, FrozenSet, Literal, Optional, Tuple

CSYesNo = Literal["yes", "no"]


class AnyOf:
    """Match a value against any option, including unhashable JSON-like values."""

    __slots__ = ("_values", "_frozen_values")

    def __init__(self, *values: Any):
        self._values = tuple(values)
        try:
            self._frozen_values: Optional[FrozenSet[Any]] = frozenset(values)
        except TypeError:
            self._frozen_values = None

    def evaluate(self, actual: Any) -> bool:
        if self._frozen_values is not None:
            try:
                return actual in self._frozen_values
            except TypeError:
                pass
        return actual in self._values

    def get_values(self) -> Tuple[Any, ...]:
        return self._values

    def __repr__(self) -> str:
        return f"AnyOf({', '.join(repr(v) for v in self._values)})"


class NoneOf:
    """Match a value only when it differs from every option."""

    __slots__ = ("_values", "_frozen_values")

    def __init__(self, *values: Any):
        self._values = tuple(values)
        try:
            self._frozen_values: Optional[FrozenSet[Any]] = frozenset(values)
        except TypeError:
            self._frozen_values = None

    def evaluate(self, actual: Any) -> bool:
        if self._frozen_values is not None:
            try:
                return actual not in self._frozen_values
            except TypeError:
                pass
        return actual not in self._values

    def get_values(self) -> Tuple[Any, ...]:
        return self._values

    def __repr__(self) -> str:
        return f"NoneOf({', '.join(repr(v) for v in self._values)})"


def any_of(*values: Any) -> AnyOf:
    """Create an :class:`AnyOf` condition."""
    return AnyOf(*values)


def none_of(*values: Any) -> NoneOf:
    """Create a :class:`NoneOf` condition."""
    return NoneOf(*values)


def truthy(value: Any) -> bool:
    """Check if a value is truthy."""
    return bool(value)


class _TruthyCheck:
    __slots__ = ()

    def __call__(self, value: Any) -> bool:
        return bool(value)

    def __repr__(self) -> str:
        return "TRUTHY"


class _FalsyCheck:
    __slots__ = ()

    def __call__(self, value: Any) -> bool:
        return not bool(value)

    def __repr__(self) -> str:
        return "FALSY"


class _UnboundCheck:
    __slots__ = ()

    def check(self, ctx: Dict[str, Any], key: str) -> bool:
        return ctx.get(key, _MISSING) is _MISSING

    def __repr__(self) -> str:
        return "UNBOUND"


TRUTHY = _TruthyCheck()
FALSY = _FalsyCheck()
UNBOUND = _UnboundCheck()
_MISSING = object()

__all__ = [
    "CSYesNo",
    "AnyOf",
    "NoneOf",
    "any_of",
    "none_of",
    "truthy",
    "TRUTHY",
    "FALSY",
    "UNBOUND",
]

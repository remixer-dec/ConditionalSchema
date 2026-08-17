"""Template and state-dependent Literal helpers."""

import string
from typing import Any, Callable, Dict, List, Literal, Optional, Union, overload


def _has_implicit_literal_template(value: str) -> bool:
    """Return whether a literal contains a documented simple placeholder."""
    try:
        for _, field_name, _, _ in string.Formatter().parse(value):
            if field_name is not None and field_name.isidentifier():
                return True
    except ValueError:
        return False
    return False


def _resolve_implicit_literal_template(value: str, ctx: Dict[str, Any]) -> str:
    """Resolve simple placeholders used by the documented Literal API."""
    if _has_implicit_literal_template(value):
        return value.format(**ctx)
    return value


class Template:
    """Represent a string or callable value resolved from bind context.

    The string form uses ``str.format(**ctx)``; callable exceptions and
    missing formatting keys propagate to the caller.
    """

    __slots__ = ("value",)

    def __init__(self, value: Union[str, Callable[[Dict], Any]]):
        self.value = value

    def resolve(self, ctx: Dict[str, Any]) -> Any:
        """Resolve the value, formatting strings with ``ctx``.

        ``KeyError`` and other exceptions from ``str.format`` or a callable are
        propagated to the caller.
        """
        if callable(self.value):
            return self.value(ctx)
        if isinstance(self.value, str):
            return self.value.format(**ctx)
        return self.value

    def __repr__(self) -> str:
        return f"Template({self.value!r})"


def CStemplate(value: Union[str, Callable[[Dict], Any]]) -> Template:
    """Create an explicit bind-time template from a string or callable."""
    return Template(value)


class LiteralTemplate:
    """Represent a Literal whose options depend on one context value.

    ``mapping_or_condition`` is either a context-value mapping with an
    optional default list or a predicate with true/false option lists.
    """

    __slots__ = ("key", "mapping", "default", "condition", "if_true", "if_false")

    def __init__(
        self,
        key: str,
        mapping_or_condition: Union[Dict[Any, List[Any]], Callable[[Any], bool]],
        default_or_if_true: Optional[List[Any]] = None,
        if_false: Optional[List[Any]] = None,
    ):
        self.key = key
        if callable(mapping_or_condition):
            self.mapping: Optional[Dict[Any, List[Any]]] = None
            self.default = None
            self.condition = mapping_or_condition
            self.if_true = default_or_if_true
            self.if_false = if_false
        else:
            self.mapping = mapping_or_condition
            self.default = default_or_if_true
            self.condition = None
            self.if_true = None
            self.if_false = None

    def resolve(self, ctx: Dict[str, Any]) -> Any:
        """Resolve to a ``typing.Literal`` type based on context.

        Raises:
            ValueError: If no mapping/default exists or the selected option list is empty.
        """
        value = ctx.get(self.key)
        if self.condition is not None:
            condition_result = self.condition(value)
            options = self.if_true if condition_result else self.if_false
            if options is None:
                raise ValueError(f"CSliteral condition returned {condition_result}, but corresponding options list is None")
        else:
            mapping = self.mapping
            if mapping is None:
                raise ValueError("CSliteral has no mapping")
            options = mapping.get(value, self.default)
            if options is None:
                raise ValueError(
                    f"No Literal options defined for {self.key}={value!r} and no default provided. "
                    f"Available keys: {list(mapping.keys())}"
                )

        if not options:
            raise ValueError(f"Empty options list for {self.key}={value!r}")

        resolved_options = [
            _resolve_implicit_literal_template(option, ctx) if isinstance(option, str) else option for option in options
        ]
        return Literal[tuple(resolved_options)]

    def __repr__(self) -> str:
        if self.condition is not None:
            return f"CSliteral({self.key!r}, <condition>, if_true={self.if_true!r}, if_false={self.if_false!r})"
        return f"CSliteral({self.key!r}, {self.mapping!r})"


@overload
def CSliteral(
    key: str,
    mapping_or_condition: Dict[Any, List[Any]],
    default_or_if_true: Optional[List[Any]] = None,
    if_false: Optional[List[Any]] = None,
    *,
    if_true: Optional[List[Any]] = None,
) -> LiteralTemplate: ...


@overload
def CSliteral(
    key: str,
    mapping_or_condition: Callable[[Any], bool],
    default_or_if_true: Optional[List[Any]] = None,
    if_false: Optional[List[Any]] = None,
    *,
    if_true: Optional[List[Any]] = None,
) -> LiteralTemplate: ...


def CSliteral(
    key: str,
    mapping_or_condition: Union[Dict[Any, List[Any]], Callable[[Any], bool]],
    default_or_if_true: Optional[List[Any]] = None,
    if_false: Optional[List[Any]] = None,
    *,
    if_true: Optional[List[Any]] = None,
) -> LiteralTemplate:
    """Create a mapping- or predicate-based bind-time Literal template."""
    actual_if_true = if_true if if_true is not None else default_or_if_true
    return LiteralTemplate(key, mapping_or_condition, actual_if_true, if_false)


__all__ = ["Template", "LiteralTemplate", "CStemplate", "CSliteral"]

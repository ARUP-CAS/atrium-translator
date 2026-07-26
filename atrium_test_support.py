from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parent.parent if _HERE.parent.name in {"tests", "test"} else _HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def import_any(module_names: Iterable[str]):
    """Import the first module that exists."""
    last_error: Exception | None = None
    for name in module_names:
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as exc:
            last_error = exc
            continue
    raise ModuleNotFoundError(f"None of the candidate modules could be imported: {list(module_names)}") from last_error


def resolve_attr(module: Any, names: Iterable[str]) -> Any:
    for name in names:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"None of these attributes exist on {module!r}: {list(names)}")


def maybe_resolve_attr(module: Any, names: Iterable[str]) -> Any | None:
    try:
        return resolve_attr(module, names)
    except AttributeError:
        return None


def _coerce_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return value


def _parameter_aliases() -> dict[str, str]:
    return {
        "source_lang": "src_lang",
        "target_lang": "tgt_lang",
        "vocabulary": "vocab_path",
        "schema_path": "xsd_path",
        "xsd": "xsd_path",
        "out_file": "out_path",
    }


def call_best_effort(func, *positional, **candidates):
    """
    Call a helper using only the kwargs supported by its signature.

    The helper also understands a few common alias names used across the repo:
    source_lang -> src_lang
    target_lang -> tgt_lang
    vocabulary  -> vocab_path
    xsd/schema_path -> xsd_path
    """
    sig = inspect.signature(func)
    alias_map = _parameter_aliases()

    normalized: dict[str, Any] = {}
    for key, value in candidates.items():
        normalized[key] = value
        alias = alias_map.get(key)
        if alias:
            normalized.setdefault(alias, value)

    kwargs = {name: _coerce_value(value) for name, value in normalized.items() if name in sig.parameters}
    args = tuple(_coerce_value(arg) for arg in positional)

    try:
        return func(*args, **kwargs)
    except TypeError:
        if kwargs:
            try:
                return func(*args)
            except TypeError:
                pass
        raise


@dataclass
class FakeTranslator:
    """Deterministic translator used by tests."""

    prefix: str = "EN:"
    suffix: str = ""

    def _render(self, text: str) -> str:
        return f"{self.prefix}{text}{self.suffix}"

    def translate_line(self, text: str, *args: Any, **kwargs: Any) -> str:
        return self._render(text)

    def translate_text(self, text: str, *args: Any, **kwargs: Any) -> str:
        return self._render(text)

    def translate(self, text: str, *args: Any, **kwargs: Any) -> str:
        return self._render(text)

    def __call__(self, text: str, *args: Any, **kwargs: Any) -> str:
        return self._render(text)

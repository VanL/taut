"""One strict import-string resolver for selected command implementations."""

from __future__ import annotations

import importlib
import re
from typing import Any

_MODULE_RE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\Z")
_ATTRIBUTE_RE = re.compile(r"[A-Za-z_]\w*\Z")


def validate_import_target(target: str) -> tuple[str, str]:
    module, separator, attribute = target.partition(":")
    if (
        separator != ":"
        or ":" in attribute
        or _MODULE_RE.fullmatch(module) is None
        or _ATTRIBUTE_RE.fullmatch(attribute) is None
    ):
        raise ValueError("implementation must use module:attribute form")
    return module, attribute


def resolve_import_target(target: str) -> Any:
    module_name, attribute = validate_import_target(target)
    module = importlib.import_module(module_name)
    return getattr(module, attribute)

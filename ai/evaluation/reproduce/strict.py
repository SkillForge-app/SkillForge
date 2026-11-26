"""Parsing that refuses duplicate keys (AI-25), for every JSON and YAML file `reproduce` reads.

`json.loads` and `yaml.safe_load` both keep the LAST of two equal keys without a word, so a
tracked-run line could hold request text under `id` and an allowed id under a second `id`: a
check would see the allowed one while the text stays in the file. The same trick in a report or
the registry would hide a changed metric or a `reproduces: false`. These loaders refuse a
duplicate key in any object, at any depth.

A message names the key only when it is safe to show (one of `names`, or by default a short
lowercase identifier) and never shows a value: either could be the text being kept out.
"""

import json
import re
from collections.abc import Collection
from typing import Any

import yaml

IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,39}")


class DuplicateKeyError(ValueError):
    """An object (JSON) or mapping (YAML) has the same key twice."""


def _shown(key: object, names: Collection[str] | None) -> str:
    if isinstance(key, str) and (
        key in names if names is not None else IDENTIFIER.fullmatch(key) is not None
    ):
        return repr(key)
    return "(name not shown)"


def _message(key: object, names: Collection[str] | None) -> str:
    return f"duplicate key {_shown(key, names)} in one object (values not shown)"


def loads_unique(text: str | bytes, names: Collection[str] | None = None) -> Any:
    """json.loads, refusing a duplicate key at any depth. `names`: the keys a message may show
    (default: any short lowercase identifier)."""

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise DuplicateKeyError(_message(key, names))
            out[key] = value
        return out

    return json.loads(text, object_pairs_hook=unique)


class _UniqueKeyLoader(yaml.SafeLoader):
    """yaml.SafeLoader that refuses a duplicate key in any mapping (merge keys `<<` aside)."""


def _construct_unique(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: list[Any] = []
    for key_node, _ in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise DuplicateKeyError(_message(key, None))
        seen.append(key)
    return loader.construct_mapping(node, deep=True)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique)


def yaml_unique(text: str | bytes) -> Any:
    """yaml.safe_load, refusing a duplicate key in any mapping."""
    return yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 (a SafeLoader subclass)


__all__ = ["DuplicateKeyError", "loads_unique", "yaml_unique"]

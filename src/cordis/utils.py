"""Shared internal constants and utilities for cordis.

This module contains only truly shared components:
- symbols: String constants for internal attribute names
- DisposableList: O(1) deletion collection used by fiber and registry

All other utilities are inlined into their respective modules to keep
related code together and reduce indirection.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, TypeVar


# ---------------------------------------------------------------------------
# Symbols - String constants with prefix to avoid collisions
# ---------------------------------------------------------------------------

class _Symbols:
    """Symbol-like constants for internal use.
    
    Using string constants with "_cordis_" prefix instead of custom Symbol class.
    This is simpler and more Pythonic while achieving the same goal of avoiding
    naming collisions with user attributes.
    """
    # Internal symbols
    shadow = "_cordis_shadow"
    original = "_cordis_original"
    initHooks = "_cordis_initHooks"
    
    # Context symbols
    effect = "_cordis_effect"
    filter = "_cordis_filter"
    isolate = "_cordis_isolate"
    intercept = "_cordis_intercept"
    
    # Service symbols
    init = "_cordis_init"
    check = "_cordis_check"
    config = "_cordis_config"
    invoke = "_cordis_invoke"
    extend = "_cordis_extend"
    tracker = "_cordis_tracker"
    resolveConfig = "_cordis_resolveConfig"


symbols = _Symbols()


# ---------------------------------------------------------------------------
# DisposableList
# ---------------------------------------------------------------------------

T = TypeVar('T')


class DisposableList:
    """Ordered collection with O(1) deletion via remover closure.
    
    Used by Fiber and RegistryService to manage disposers.
    Provides efficient add/remove operations while maintaining insertion order.
    Direct delete() by value is O(n) but safe against id-reuse collisions.
    """
    
    __slots__ = ('_sn', '_map')
    
    def __init__(self) -> None:
        self._sn = 0
        self._map: dict[int, Any] = {}
    
    @property
    def length(self) -> int:
        return len(self._map)
    
    def __len__(self) -> int:
        return len(self._map)
    
    def push(self, value: T) -> Callable[[], bool]:
        """Add value and return remover function."""
        self._sn += 1
        sn = self._sn
        self._map[sn] = value
        
        def remove() -> bool:
            if self._map.get(sn) is value:
                del self._map[sn]
                return True
            return False
        
        return remove
    
    def delete(self, value: T) -> bool:
        """Remove specific value by identity. Returns True if found and removed."""
        for sn, v in self._map.items():
            if v is value:
                del self._map[sn]
                return True
        return False
    
    def clear(self) -> list[T]:
        """Remove all values and return them in reverse insertion order."""
        values = list(self._map.values())
        self._map.clear()
        values.reverse()
        return values
    
    def __iter__(self) -> Iterator[T]:
        return iter(self._map.values())
    
    def __repr__(self) -> str:
        return f"DisposableList({list(self._map.values())})"

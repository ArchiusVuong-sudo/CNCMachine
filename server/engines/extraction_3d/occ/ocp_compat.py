"""OCP API compatibility layer.

The cadquery-ocp fork appends '_s' to static/class methods
(e.g. TopoDS.Face_s, BRepGProp.VolumeProperties_s).
The conda-forge 'ocp' package uses the plain names
(e.g. TopoDS.Face, BRepGProp.VolumeProperties).

This module detects which convention is installed and provides
a helper so calling code works with either version.
"""

from __future__ import annotations

import functools


def _resolve(cls: type, method_name: str):
    """Return the bound method, trying ``name_s`` first, then ``name``."""
    suffixed = f"{method_name}_s"
    if hasattr(cls, suffixed):
        return getattr(cls, suffixed)
    if hasattr(cls, method_name):
        return getattr(cls, method_name)
    raise AttributeError(
        f"{cls.__name__} has neither '{suffixed}' nor '{method_name}'"
    )


@functools.lru_cache(maxsize=None)
def static_method(cls: type, method_name: str):
    """Cached lookup: return callable for *cls.method* (tries _s first)."""
    return _resolve(cls, method_name)


def call_static(cls: type, method_name: str, *args, **kwargs):
    """Call a static/class method with automatic _s suffix resolution."""
    return static_method(cls, method_name)(*args, **kwargs)

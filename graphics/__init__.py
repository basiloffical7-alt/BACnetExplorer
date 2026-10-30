"""
Equipment graphics. Every module in this folder that defines ``TEMPLATE`` (a subclass of
graphics.base.GraphicTemplate) is loaded automatically and offered in the Graphics tab.

Extra templates can also be dropped - without rebuilding the .exe - into a ``graphics``
folder next to BACnetExplorer.exe (or next to bacnet_explorer.py), or into
``%USERPROFILE%\\BACnetExplorer\\graphics``.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
import traceback
from typing import Dict, List, Tuple, Type

from graphics.base import GraphicTemplate

_SKIP = {"base", "panel"}

# Modules bundled into the .exe (PyInstaller cannot list them from a folder at run time).
BUILTIN = ["ahu", "ahu_supply_return", "chiller", "exhaust_fan", "fcu", "pump_set", "vav"]


def extra_folders() -> List[str]:
    """Folders searched for user-added template files."""
    here = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(here)
    folders = [os.path.join(app_dir, "graphics"),
               os.path.join(os.path.expanduser("~"), "BACnetExplorer", "graphics")]
    out = []
    for f in folders:
        f = os.path.normcase(os.path.abspath(f))
        if f != os.path.normcase(here) and f not in out:
            out.append(f)
    return out


def _register(cls, source: str, templates: Dict[str, Type[GraphicTemplate]], errors: List[str]):
    if cls is None:
        return
    if not (isinstance(cls, type) and issubclass(cls, GraphicTemplate)):
        errors.append(f"{source}: TEMPLATE is not a GraphicTemplate subclass")
        return
    if cls.TEMPLATE_ID in templates:
        if templates[cls.TEMPLATE_ID] is not cls:
            errors.append(f"{source}: duplicate TEMPLATE_ID '{cls.TEMPLATE_ID}' (ignored)")
        return
    templates[cls.TEMPLATE_ID] = cls


def load_templates() -> Tuple[Dict[str, Type[GraphicTemplate]], List[str]]:
    """Return ({template_id: class}, [error messages])."""
    templates: Dict[str, Type[GraphicTemplate]] = {}
    errors: List[str] = []
    folder = os.path.dirname(os.path.abspath(__file__))
    names = set(BUILTIN)
    names.update(m.name for m in pkgutil.iter_modules([folder]))
    for name in sorted(names):
        if name in _SKIP or name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"graphics.{name}")
        except ModuleNotFoundError:
            continue
        except Exception:
            errors.append(f"graphics/{name}.py failed to load:\n{traceback.format_exc(limit=3)}")
            continue
        _register(getattr(module, "TEMPLATE", None), f"graphics/{name}.py", templates, errors)

    for extra in extra_folders():
        if not os.path.isdir(extra):
            continue
        for fn in sorted(os.listdir(extra)):
            if not fn.endswith(".py") or fn.startswith("_") or fn[:-3] in _SKIP:
                continue
            path = os.path.join(extra, fn)
            try:
                spec = importlib.util.spec_from_file_location(f"graphics.user_{fn[:-3]}", path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)  # type: ignore[attr-defined]
                _register(getattr(module, "TEMPLATE", None), path, templates, errors)
            except Exception:
                errors.append(f"{path} failed to load:\n{traceback.format_exc(limit=3)}")
    return templates, errors

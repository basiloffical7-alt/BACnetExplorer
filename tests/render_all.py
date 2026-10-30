"""Render every graphic template (demo values) to PNG files for visual review."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_canvas import RecCanvas
from graphics import load_templates
from graphics.base import Drawer, PointState

def demo_states(tpl, t):
    st = {}
    for gp in tpl.POINTS:
        v, an = tpl.demo_value(gp.key, t)
        if an:
            st[gp.key] = PointState(True, v, f"{v:.1f}", v > 1.0, max(0.0, min(100.0, v)), True, True)
        else:
            st[gp.key] = PointState(True, v, "ACTIVE" if v else "INACTIVE", bool(v), 100.0 if v else 0.0, False, True)
    return st

out = sys.argv[1]; only = sys.argv[2:]
tpls, errs = load_templates(); assert not errs, errs
for tid, cls in tpls.items():
    if only and tid not in only: continue
    import json as _j
    tpl = cls(_j.loads(os.environ.get("TPL_OPTIONS", "{}")))
    for t, tag in ((tpl_t, n) for tpl_t, n in getattr(cls, "RENDER_TIMES", ((10.0, "run"), (37.0, "stop")))):
        w = int(os.environ.get("RENDER_W", 1300))
        cv = RecCanvas(w=w, h=int(w * tpl.HEIGHT / tpl.WIDTH))
        tpl.draw(Drawer(cv, tpl.WIDTH, tpl.HEIGHT, dark=os.environ.get("DARK") == "1"), demo_states(tpl, t), t)
        if os.environ.get("DARK") == "1":
            cv.ops.insert(0, ("rect", [0, 0, cv.w, cv.h], {"fill": "#1e2227", "outline": ""}))
        cv.render(os.path.join(out, f"g_{tid}{os.environ.get('TPL_SUFFIX', '')}_{tag}.png"))
    print("rendered", tid, len(cv.ops), "items")

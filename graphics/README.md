# Adding equipment graphics

Every `.py` file in this folder that defines `TEMPLATE` is loaded automatically and appears in
**Graphics ▸ New page…**. `ahu.py` is a complete example.

```python
from graphics.base import GraphicTemplate, GraphicPoint

class FCUGraphic(GraphicTemplate):
    TEMPLATE_ID = "fcu"            # unique; saved in page links, don't change later
    NAME = "Fan Coil Unit"
    DESCRIPTION = "2-pipe FCU"
    WIDTH, HEIGHT = 1000, 520      # logical drawing area, scaled to the window
    POINTS = [
        GraphicPoint("fan", "Fan Status", "binary", "Blades rotate when active",
                     match=["fan status", "fan sts"]),   # Auto-link name patterns
        GraphicPoint("valve", "CHW Valve", "analog", "0-100 %"),
    ]

    def draw(self, d, s, t):       # d = Drawer, s = {key: PointState}, t = seconds
        d.fan(500, 260, 60, s["fan"].active, s["fan"].speed, t, point="fan")
        d.valve(700, 400, s["valve"].percent if s["valve"].active else 0, point="valve")
        d.legend(780, 30, [(p.key, p.label) for p in self.POINTS], s)   # clickable point list

TEMPLATE = FCUGraphic
```

`PointState` gives you `active`, `percent` (0–100), `speed` (0–1 for animation), `text`,
`linked` and `online`. Drawing helpers in `Drawer`: `fan`, `damper`, `valve`, `dps`, `filter`,
`coil`, `pipe`, `duct`, `air_arrows`, `value_box`, `legend`, `pump`, `damper_h`, `bag_filter`,
`sensor`, `lamp`, `vfd`, `grille`, `louvre`, `thermostat`, `cooling_tower`, `chiller`,
`flow_switch`, `iso_valve`, `check_valve`, `speed_bars`, `level_bar`, `tag`,
plus `rect/oval/line/poly/text`. The existing templates are good examples to copy.
Pass `point="key"` to make an element clickable / a drop target for linking.
Optionally override `demo_value()` to control the demo animation.

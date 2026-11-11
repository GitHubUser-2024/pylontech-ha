#!/usr/bin/env python3
"""Generate the Pylontech Lovelace dashboard (one sections view) on stdout.

The output is JSON, which is also valid YAML, so it can be pasted as-is into
Home Assistant: Settings -> Dashboards -> Add dashboard -> (open it) -> ⋮ -> Edit
dashboard -> ⋮ -> Raw configuration editor -> replace everything -> Save.
It can also be saved via the websocket command
  {"type": "lovelace/config/save", "url_path": "<dashboard url>", "config": <this JSON>}

Entity ids follow the HA device name set in config.ini ([homeassistant] device_name,
default "Pylontech" -> sensor.pylontech_*). If you use another device name, or HA gave
your entities other ids, pass --prefix.

    python3 dashboard/mkdash.py                          # defaults (device "Pylontech", 15 cells)
    python3 dashboard/mkdash.py --prefix house_battery --title "House battery"
    python3 dashboard/mkdash.py --date-format '%Y-%m-%d %H:%M' > dashboard.json
"""
import argparse
import json
import sys

TEMP_SLUGS = ["cells_1_4", "cells_5_8", "cells_9_12", "cells_13_15"]
TEMP_LABELS = ["Cells 1–4", "Cells 5–8", "Cells 9–12", "Cells 13–15"]


def build(prefix="pylontech", title="Pylontech", cells=15, date_format="%d.%m. %H:%M"):
    S = "sensor.%s_" % prefix
    B = "binary_sensor.%s_" % prefix
    md = ("{% set a = states." + S + "cell_table.attributes %}" + """{% set t = a.cells %}{% if t %}{% set nows = t | map(attribute='now') | list %}{% set lo = nows | min %}{% set hi = nows | max %}
| Cell | Now | Δ now | Min 7d | Max 7d | Avg 7d | Δ avg 7d |
|:--:|--:|--:|--:|--:|--:|--:|
{% for r in t -%}
| {{ r.cell }} | {% if r.now == hi %}**▲ {{ r.now }}**{% elif r.now == lo %}**▼ {{ r.now }}**{% else %}{{ r.now }}{% endif %} | {{ '%+.1f' | format(r.dev_now) }} | {{ r.min }} | {{ r.max }} | {{ '%.1f' | format(r.avg) }} | {{ '%+.1f' | format(r.dev) }} |
{% endfor -%}
| **Spread** | **{{ a.spread_now }}** | | | **{{ a.spread_max_7d }}** max | **{{ '%.1f' | format(a.spread_avg_7d) }}** avg | |

<small>All values in mV. **Δ** = cell minus pack average at the same moment (imbalance); Min/Max 7d mostly follow the state of charge. Spread = highest − lowest cell. 7-day window: {{ a.samples_7d }} samples over {{ '%.1f' | format(a.history_days) }} days (fills up over a week). Updated {{ a.updated | timestamp_custom('""" + date_format + """') }}, every 10 min.</small>
{% else %}No data yet.{% endif %}""")

    def tile(e, name=None):
        c = {"type": "tile", "entity": e}
        if name:
            c["name"] = name
        return c

    cell_ids = ["%scell_%02d_voltage" % (S, i) for i in range(1, cells + 1)]
    temps = [S + "temperature_" + s for s in TEMP_SLUGS]
    full = {"columns": "full"}
    sections = [
        {"type": "grid", "cards": [
            {"type": "heading", "heading": "Now", "icon": "mdi:battery-high"},
            tile(S + "soc_bms_remaining_full", "SOC"), tile(S + "power", "Power"),
            tile(S + "pack_voltage", "Voltage"), tile(S + "current", "Current"),
            tile(S + "remaining_capacity", "Remaining"), tile(S + "full_capacity", "Full capacity"),
            tile(S + "cell_spread", "Cell spread"), tile(S + "cell_spread_7d_avg", "Spread 7d avg"),
            tile(S + "alarms", "Alarms"), tile(S + "cycles", "Cycles"),
            tile(S + "bms_state", "BMS state"), tile(B + "bms_protection", "Protection"),
            tile(B + "charge_enabled", "Charge enabled"), tile(B + "discharge_enabled", "Discharge enabled")]},
        {"type": "grid", "column_span": 2, "cards": [
            {"type": "heading", "heading": "Cells", "icon": "mdi:table"},
            {"type": "markdown", "content": md, "grid_options": full}]},
        {"type": "grid", "cards": [
            {"type": "heading", "heading": "Temperatures & limits", "icon": "mdi:thermometer"},
            tile(S + "bms_temperature", "BMS"), tile(temps[0], TEMP_LABELS[0]),
            tile(temps[1], TEMP_LABELS[1]), tile(temps[2], TEMP_LABELS[2]),
            tile(temps[3], TEMP_LABELS[3]), tile(B + "charge_immediately_request", "Charge request"),
            tile(S + "charge_voltage_limit", "Charge V limit"), tile(S + "discharge_voltage_limit", "Discharge V limit"),
            tile(S + "charge_current_limit", "Charge A limit"), tile(S + "discharge_current_limit", "Discharge A limit"),
            tile(B + "charge_mosfet", "Charge MOSFET"), tile(B + "discharge_mosfet", "Discharge MOSFET"),
            tile(B + "fully_charged", "Fully charged"), tile(B + "heater", "Heater")]},
        {"type": "grid", "column_span": 2, "cards": [
            {"type": "heading", "heading": "History", "icon": "mdi:chart-line"},
            {"type": "history-graph", "title": "Cell spread (7 days)", "hours_to_show": 168,
             "entities": [S + "cell_spread", S + "cell_spread_7d_avg"], "grid_options": full},
            {"type": "history-graph", "title": "Cell min / max (7 days)", "hours_to_show": 168,
             "entities": [S + "cell_min_voltage", S + "cell_max_voltage"], "grid_options": full},
            {"type": "history-graph", "title": "All cells (24 h)", "hours_to_show": 24,
             "entities": cell_ids, "grid_options": full},
            {"type": "history-graph", "title": "Voltage, current & SOC (24 h)", "hours_to_show": 24,
             "entities": [S + "pack_voltage", S + "current", S + "soc_bms_remaining_full"], "grid_options": full},
            {"type": "history-graph", "title": "Temperatures (7 days)", "hours_to_show": 168,
             "entities": [S + "bms_temperature"] + temps, "grid_options": full}]},
    ]
    return {"title": title, "views": [{"title": title, "path": "pylontech", "type": "sections",
                                       "max_columns": 3, "sections": sections}]}


def main(argv=None):
    p = argparse.ArgumentParser(description="Print the Pylontech Lovelace dashboard as JSON (= valid YAML).")
    p.add_argument("--prefix", default="pylontech",
                   help="entity id prefix, i.e. the slug of the HA device name (default: pylontech)")
    p.add_argument("--title", default="Pylontech", help="dashboard and view title (default: Pylontech)")
    p.add_argument("--cells", type=int, default=15, help="number of cells (default: 15)")
    p.add_argument("--date-format", default="%d.%m. %H:%M",
                   help="strftime format of the 'Updated' time in the cell table (default: %%d.%%m. %%H:%%M)")
    a = p.parse_args(argv)
    json.dump(build(a.prefix, a.title, a.cells, a.date_format), sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

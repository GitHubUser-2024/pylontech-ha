"""Read the battery with pylontech-rs485 and publish to Home Assistant via MQTT discovery.

Topics (with the default base topic ``pylontech``):

* ``pylontech/state``  - all live values, flat JSON (one HA entity per key)
* ``pylontech/cells``  - per-cell 7-day table (attributes of ``sensor.pylontech_cell_table``)
* ``pylontech/status`` - availability, retained ``online`` / ``offline``
* ``homeassistant/{sensor,binary_sensor}/pylontech_<key>/config`` - discovery, retained

With the default ``unique_id_prefix`` (``pylontech``) the keys, topics and unique IDs are
stable across versions, so entities, their history and the dashboard carry on after updates.
"""

import argparse
import configparser
import json
import sys

from pylontech_rs485 import Battery, history
from pylontech_rs485.port import PortBusy
from pylontech_rs485.protocol import ProtocolError

from . import __version__
from .mqtt import Client

DEFAULTS = {
    "battery": {"device": "", "baud": "115200", "address": "2", "timeout": "2", "retries": "3"},
    "history": {"file": "history.json", "window_days": "7"},
    "mqtt": {"host": "", "port": "1883", "username": "", "password_file": "", "client_id": "pylontech-ha",
             "base_topic": "pylontech", "discovery_prefix": "homeassistant"},
    "homeassistant": {"device_name": "Pylontech", "unique_id_prefix": "pylontech", "via_device": "",
                      "expire_after": "1800"},
}


def load_config(path):
    cp = configparser.ConfigParser()
    cp.read_dict(DEFAULTS)
    if path:
        with open(path) as f:
            cp.read_file(f)
    return cp


# ---------------------------------------------------------------- mapping
def to_state(data, info, stats):
    """Flatten a pylontech-rs485 read_all() result (+ info + history stats) into the state JSON."""
    a, al, m = data["analog"], data["alarms"], data["management"]
    temps = list(a["temperatures_c"].values())
    s = {
        "voltage": a["voltage_v"], "current": a["current_a"], "power": a["power_w"],
        "remaining_ah": round(a["remaining_ah"], 2), "full_ah": round(a["full_ah"], 2),
        "soc": a["soc_pct"], "cycles": a["cycles"], "temp_bms": temps[0] if temps else None,
        "alarms": ", ".join(al["active"]) if al["active"] else "OK",
        "status_raw": " ".join("%02X" % b for b in al["status_bytes"]),
        "charge_voltage_limit": m["charge_voltage_limit_v"],
        "discharge_voltage_limit": m["discharge_voltage_limit_v"],
        "charge_current_limit": m["charge_current_limit_a"],
        "discharge_current_limit": m["discharge_current_limit_a"],
        "charge_enabled": m["charge_enabled"], "discharge_enabled": m["discharge_enabled"],
        "charge_immediately": m["charge_immediately"],
        "model": info["model"], "sw_version": info["software_version"], "serial": info["serial"],
        "cell_min": a["cell_min_mv"], "cell_max": a["cell_max_mv"],
        "cell_min_id": a["cell_min_index"], "cell_max_id": a["cell_max_index"],
        "spread": a["cell_spread_mv"],
    }
    if stats:
        s.update(spread_avg_7d=stats["spread_avg_mv"], spread_max_7d=stats["spread_max_mv"],
                 spread_min_7d=stats["spread_min_mv"], samples_7d=stats["samples"],
                 history_days=stats["span_days"])
    st = al.get("status")
    if st:  # decoded 0x44 status bytes (pylontech-rs485 >= 0.2.0)
        s.update(charge_mosfet=st["charge_mosfet"], discharge_mosfet=st["discharge_mosfet"],
                 fully_charged=st["fully_charged"], heater=st["heater"],
                 protection=bool(st["protections"] or st["cell_errors"]),
                 bms_state="charging" if st["charge_current"] else
                 "discharging" if st["discharge_current"] else "idle")
    for i, v in enumerate(a["cells_mv"], 1):
        s["cell_%02d" % i] = v
    for i, t in enumerate(temps[1:], 1):
        s["temp_%d" % i] = t
    return s


def to_cells(stats, timestamp):
    """Per-cell table payload (attribute names used by the dashboard markdown card)."""
    return {
        "samples_7d": stats["samples"], "history_days": stats["span_days"],
        "spread_now": stats["spread_now_mv"], "spread_avg_7d": stats["spread_avg_mv"],
        "spread_max_7d": stats["spread_max_mv"], "updated": timestamp,
        "cells": [{"cell": c["cell"], "now": c["now_mv"], "min": c["min_mv"], "max": c["max_mv"],
                   "avg": c["avg_mv"], "dev": c["dev_avg_mv"], "dev_now": c["dev_now_mv"],
                   "dev_max": c.get("dev_max_mv")}
                  for c in stats["cells"]],
    }


# ---------------------------------------------------------------- discovery
V = ("V", "voltage", "measurement")
A = ("A", "current", "measurement")
W = ("W", "power", "measurement")
C = ("°C", "temperature", "measurement")
MV = ("mV", "voltage", "measurement")
NONE = (None, None, None)
TEMP_NAMES = ["Cells 1-4", "Cells 5-8", "Cells 9-12", "Cells 13-15"]


def sensor_defs(n_cells, n_temps):
    s = [("voltage", "Pack voltage", V, 3, None), ("current", "Current", A, 1, None),
         ("power", "Power", W, 0, None),
         ("soc", "SOC (BMS remaining/full)", ("%", "battery", "measurement"), 1, None),
         ("remaining_ah", "Remaining capacity", ("Ah", None, "measurement"), 2, None),
         ("full_ah", "Full capacity", ("Ah", None, "measurement"), 2, None),
         ("cycles", "Cycles", (None, None, "total_increasing"), None, "mdi:counter"),
         ("temp_bms", "BMS temperature", C, 1, None),
         ("cell_min", "Cell min voltage", MV, 0, None), ("cell_max", "Cell max voltage", MV, 0, None),
         ("cell_min_id", "Cell min ID", NONE, None, "mdi:numeric"),
         ("cell_max_id", "Cell max ID", NONE, None, "mdi:numeric"),
         ("spread", "Cell spread", MV, 0, "mdi:arrow-expand-vertical"),
         ("spread_avg_7d", "Cell spread 7d avg", MV, 1, "mdi:arrow-expand-vertical"),
         ("spread_max_7d", "Cell spread 7d max", MV, 0, "mdi:arrow-expand-vertical"),
         ("charge_voltage_limit", "Charge voltage limit", V, 2, None),
         ("discharge_voltage_limit", "Discharge voltage limit", V, 2, None),
         ("charge_current_limit", "Charge current limit", A, 1, None),
         ("discharge_current_limit", "Discharge current limit", A, 1, None),
         ("alarms", "Alarms", NONE, None, "mdi:alert-circle-outline"),
         ("bms_state", "BMS state", NONE, None, "mdi:battery-sync")]
    s += [("cell_%02d" % i, "Cell %02d voltage" % i, MV, 0, None) for i in range(1, n_cells + 1)]
    s += [("temp_%d" % i, "Temperature %s" % (TEMP_NAMES[i - 1] if i <= len(TEMP_NAMES) else i), C, 1, None)
          for i in range(1, n_temps)]
    return s


# key, name, icon, device_class
BINARY_DEFS = [("charge_enabled", "Charge enabled", "mdi:battery-arrow-up", None),
               ("discharge_enabled", "Discharge enabled", "mdi:battery-arrow-down", None),
               ("charge_immediately", "Charge immediately request", "mdi:battery-alert", None),
               ("charge_mosfet", "Charge MOSFET", "mdi:electric-switch-closed", None),
               ("discharge_mosfet", "Discharge MOSFET", "mdi:electric-switch-closed", None),
               ("fully_charged", "Fully charged", "mdi:battery-check", None),
               ("heater", "Heater", "mdi:radiator", None),
               ("protection", "BMS protection", None, "problem")]


def discovery(cfg, state, n_cells, n_temps):
    """List of (topic, payload_dict) discovery messages."""
    base_t = cfg["mqtt"]["base_topic"]
    prefix = cfg["mqtt"]["discovery_prefix"]
    ha = cfg["homeassistant"]
    uid = ha["unique_id_prefix"] or "pylontech"
    dev = {"identifiers": ["pylontech_%s" % state["serial"]], "name": ha["device_name"],
           "manufacturer": "Pylontech", "model": state["model"], "sw_version": state["sw_version"],
           "serial_number": state["serial"]}
    if ha["via_device"]:
        dev["via_device"] = ha["via_device"]
    base = {"state_topic": "%s/state" % base_t, "expire_after": int(ha["expire_after"]), "device": dev,
            "availability_topic": "%s/status" % base_t}
    out = []
    for key, name, (unit, dc, sc), prec, icon in sensor_defs(n_cells, n_temps):
        if key not in state:
            continue
        c = dict(base, name=name, unique_id="%s_%s" % (uid, key),
                 value_template="{{ value_json['%s'] }}" % key)
        if unit:
            c["unit_of_measurement"] = unit
        if dc:
            c["device_class"] = dc
        if sc:
            c["state_class"] = sc
        if prec is not None:
            c["suggested_display_precision"] = prec
        if icon:
            c["icon"] = icon
        if key == "alarms":
            c["json_attributes_topic"] = "%s/state" % base_t
            c["json_attributes_template"] = "{{ {'status_raw': value_json['status_raw']} | tojson }}"
        out.append(("%s/sensor/%s_%s/config" % (prefix, uid, key), c))
    c = dict(base, name="Cell table", unique_id="%s_cell_table" % uid, state_topic="%s/cells" % base_t,
             value_template="{{ value_json['samples_7d'] }}", json_attributes_topic="%s/cells" % base_t,
             icon="mdi:table", unit_of_measurement="samples")
    out.append(("%s/sensor/%s_cell_table/config" % (prefix, uid), c))
    for key, name, icon, dc in BINARY_DEFS:
        if key not in state:
            continue
        c = dict(base, name=name, unique_id="%s_%s" % (uid, key),
                 value_template="{{ value_json['%s'] | lower }}" % key, payload_on="true", payload_off="false")
        if icon:
            c["icon"] = icon
        if dc:
            c["device_class"] = dc
        out.append(("%s/binary_sensor/%s_%s/config" % (prefix, uid, key), c))
    return out


# ---------------------------------------------------------------- run
def collect(cfg, battery=None):
    """Read the battery, update history. Returns (state, cells_payload, n_cells, n_temps)."""
    b = cfg["battery"]
    bat = battery or Battery(b["device"], int(b["baud"]), int(b["address"]), float(b["timeout"]),
                             int(b["retries"]))
    with bat:
        info = bat.info()
        data = bat.read_all()
    h = cfg["history"]
    samples = history.add(history.load(h["file"]), data["timestamp"], data["analog"]["cells_mv"],
                          float(h["window_days"]) * 86400)
    history.save(h["file"], samples)
    stats = history.stats(samples)
    state = to_state(data, info, stats)
    return state, to_cells(stats, data["timestamp"]), len(data["analog"]["cells_mv"]), \
        len(data["analog"]["temperatures_c"])


def mqtt_client(cfg):
    m = cfg["mqtt"]
    if not m["host"]:
        raise SystemExit("config: [mqtt] host is empty")
    password = None
    if m["password_file"]:
        with open(m["password_file"]) as f:
            password = f.read().strip()
    return Client(m["host"], int(m["port"]), m["username"] or None, password, m["client_id"])


def messages(cfg, state, cells, n_cells, n_temps):
    t = cfg["mqtt"]["base_topic"]
    msgs = [(topic, json.dumps(p), True) for topic, p in discovery(cfg, state, n_cells, n_temps)]
    msgs += [("%s/status" % t, "online", True), ("%s/state" % t, json.dumps(state), False),
             ("%s/cells" % t, json.dumps(cells), False)]
    return msgs


def main(argv=None, battery=None, client=None):
    p = argparse.ArgumentParser(prog="pylontech-ha",
                                description="Publish a Pylontech battery to Home Assistant (MQTT discovery)")
    p.add_argument("-c", "--config", required=True, help="INI file, see config.example.ini")
    p.add_argument("--dry-run", action="store_true", help="read the battery and print messages, publish nothing "
                                                          "(the history file is still updated)")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    try:
        state, cells, n_cells, n_temps = collect(cfg, battery)
    except (ProtocolError, PortBusy, OSError) as e:
        print("read failed: %s" % e, file=sys.stderr)
        if not args.dry_run:
            try:
                with (client or mqtt_client(cfg)) as c:
                    c.publish("%s/status" % cfg["mqtt"]["base_topic"], "offline", retain=True)
            except Exception as e2:  # broker down too: nothing more we can do
                print("could not publish offline: %s" % e2, file=sys.stderr)
        return 1
    msgs = messages(cfg, state, cells, n_cells, n_temps)
    if args.dry_run:
        for topic, payload, retain in msgs:
            print("%s%s %s" % (topic, " (retain)" if retain else "", payload))
        return 0
    with (client or mqtt_client(cfg)) as c:
        for topic, payload, retain in msgs:
            c.publish(topic, payload, retain)
    print(json.dumps(state))
    return 0

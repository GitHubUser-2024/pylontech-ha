# Changelog

## 0.3.0 — 2026-11-11

Made usable for others; existing installs carry on unchanged (same entities and IDs).

- README rewritten as a general install guide (HA OS step by step, other Linux hosts, Docker, configuration reference, entities, troubleshooting).
- `[homeassistant] unique_id_prefix` (default `pylontech`) for a second battery.
- `dashboard/mkdash.py`: options `--prefix`, `--title`, `--cells`, `--date-format`; output pasteable into the raw configuration editor; pre-generated `dashboard/pylontech-dashboard.json`.
- The Unlicense (`LICENSE`).

## 0.2.0 — 2026-11-11

- pylontech-rs485 submodule → v0.2.0 (decoded 0x44 status bytes).
- New entities: `sensor.pylontech_bms_state` (charging / discharging / idle, from the BMS "effective current" bits), binary sensors Charge MOSFET, Discharge MOSFET, Fully charged, Heater and BMS protection (device class problem; on for any active protection or cell error). Active protections also appear in the Alarms sensor text.
- Dashboard: BMS state + Protection in "Now", MOSFETs / fully charged / heater in "Temperatures & limits".
- `config.example.ini`: MQTT host `core-mosquitto` (works from the HA core container on HA OS).
- Discovery skips entities whose key the reader does not deliver.

## 0.1.0 — 2026-11-11

First version.

- Publisher on top of pylontech-rs485 v0.1.0 (git submodule): MQTT discovery + state with the same topics, keys and unique IDs as the original stand-alone publisher, so existing HA entities, history and the dashboard carry on.
- Built-in minimal MQTT 3.1.1 client (stdlib only, no paho / mosquitto_pub needed).
- `--dry-run`, INI config, `offline` availability on read failure.
- HA package (10-minute automation + shell_command), dashboard generator, deploy script.

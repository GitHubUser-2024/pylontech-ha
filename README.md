# pylontech-ha

Get a **Pylontech** LiFePO₄ battery into **Home Assistant** over its **RS485** port: every cell voltage, temperatures, current, voltage, capacity, cycles, alarms, BMS limits and BMS status, plus a per-cell 7-day statistics table and a ready-made dashboard.

- Reads the battery with **[pylontech-rs485](https://github.com/GitHubUser-2024/pylontech-rs485)** (included as a git submodule) and publishes to HA via **MQTT discovery**.
- **Python standard library only**, including a tiny built-in MQTT client: runs inside Home Assistant OS without installing anything, or on any Linux machine with Python 3.
- Polls every **10 minutes** (an HA automation calls it), so it is light on the battery, the network and the HA database.

Released into the public domain under [The Unlicense](LICENSE): do whatever you want with it.

> Prefer a normal integration you add in the HA UI, without MQTT and SSH? See the HACS custom integration **[ha-pylontech-rs485](https://github.com/GitHubUser-2024/ha-pylontech-rs485)**. It shows the same data. This repo is the MQTT route: useful when the dongle sits on another machine than Home Assistant, or when you want the data on MQTT anyway.

## Tested with

| | |
|---|---|
| Battery | Pylontech **US3000C**, 15 cells, BMS software 2.2, single module |
| Adapter | USB-RS485 dongle with a **CH340** USB chip and an RS485 transceiver |
| Home Assistant | HA OS on a Home Assistant Green; Mosquitto broker add-on |

Other Pylontech low-voltage modules with the same protocol (US2000C, US5000, …) will probably work but are untested. Only **one module** is read (RS485 address 2); stacks of several modules connected to each other are not supported.

## What you need

1. The battery's **RS485** port wired to a **USB-RS485 adapter** (pins 7 = A, 8 = B; A/B labels vary, swap if there is no answer). The adapter must contain an RS485 transceiver: some "Pylontech RS485 cables" are only a USB-UART chip and cannot work. Details, pinout and DIP switches: [pylontech-rs485 → Wiring](https://github.com/GitHubUser-2024/pylontech-rs485#wiring).
2. **MQTT** in Home Assistant: the **Mosquitto broker** add-on (or any broker) and the **MQTT** integration.
3. The adapter plugged into the Home Assistant machine (or into another Linux machine, see [Other setups](#other-setups)).

## How it works

```
battery ──RS485── USB dongle ── HA machine
                                  │  every 10 min: automation → shell_command → run.py
                                  │      reads the battery (pylontech-rs485)
                                  │      keeps a 7-day cell history (history.json)
                                  ▼
                               MQTT broker ── MQTT discovery ──▶ HA entities + dashboard
```

## Install on Home Assistant OS

### 1. MQTT user

Settings → People → **Users** → Add user, e.g. name `pylontech`, username `pylontech`, a long random password. (The Mosquitto add-on accepts HA users; its own "logins" option works too.) You need **Advanced mode** in your user profile to see the Users tab.

### 2. Find the dongle

Plug it in, then Settings → System → Hardware → ⋮ **All hardware** and look for a `/dev/serial/by-id/usb-…` entry that appeared, or in the Terminal add-on:

```bash
ls -l /dev/serial/by-id/
# usb-1a86_USB_Serial-if00-port0 -> ../../ttyUSB1      ← CH340 dongle
```

Always use the `/dev/serial/by-id/…` path: `/dev/ttyUSB0`/`1` can swap after a reboot (e.g. with a Zigbee stick).

### 3. Copy the files

On a PC with git (GitHub's "Download ZIP" does **not** include the submodule, so use git):

```bash
git clone --recurse-submodules https://github.com/GitHubUser-2024/pylontech-ha.git
cd pylontech-ha
```

Then either

- **over SSH** (Terminal & SSH add-on with your public key):

  ```bash
  ./deploy.sh root@homeassistant.local
  # SSH_OPTS="-i ~/.ssh/my_key -p 22" ./deploy.sh root@homeassistant.local
  ```

  This copies the program to `/config/scripts/pylontech/` and the HA package to `/config/packages/pylontech.yaml`. It never overwrites `config.ini`, the password file or `history.json`, so it is also the update command.

- **or by hand** (Samba share, File editor or Studio Code Server add-on):

  ```bash
  ./deploy.sh --stage out     # builds the folder to copy
  ```

  Copy the **contents** of `out/` to `/config/scripts/pylontech/` and `ha/packages/pylontech.yaml` to `/config/packages/pylontech.yaml`.

### 4. Enable packages

If `configuration.yaml` doesn't load packages yet, add:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

### 5. Configure

In `/config/scripts/pylontech/`:

- copy `config.example.ini` to **`config.ini`** and set at least `[battery] device` (step 2) and `[mqtt] username`;
- create **`mqtt.pw`** containing only the MQTT password (Terminal: `printf '%s' 'the-password' > /config/scripts/pylontech/mqtt.pw && chmod 600 /config/scripts/pylontech/mqtt.pw`).

On HA OS keep `host = core-mosquitto` (the Mosquitto add-on). `127.0.0.1` does **not** work from the Terminal add-on, but `core-mosquitto` works everywhere on HA OS.

### 6. Restart and test

Developer tools → YAML → **Check configuration**, then **Restart**. Afterwards, Developer tools → Actions → `shell_command.pylontech_publish` → *Perform action* (tick "return response" if offered). `stdout` shows the values read; `returncode` 0 = OK. A device **Pylontech** with about 49 entities appears under Settings → Devices → MQTT. From now on it runs every 10 minutes.

### 7. Dashboard

```bash
python3 dashboard/mkdash.py > dashboard.json
```

Settings → Dashboards → **Add dashboard** → "New dashboard from scratch", open it, ⋮ → Edit dashboard → ⋮ → **Raw configuration editor**, replace everything with the content of `dashboard.json` (JSON is valid YAML) and save. A pre-generated copy with the defaults is in [`dashboard/pylontech-dashboard.json`](dashboard/pylontech-dashboard.json).

If you changed `device_name` (or HA gave your entities other ids), generate it with `--prefix your_device_slug`. `--help` lists the other options (title, cell count, date format).

## Other setups

**Dongle on another Linux machine** (Raspberry Pi, server, …): clone the repo there (Python 3; tested with 3.11 and 3.13), create `config.ini` + password file next to `run.py`, set `[mqtt] host` to your broker's IP, and run it from cron or a systemd timer instead of the HA package:

```ini
# /etc/systemd/system/pylontech-ha.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/pylontech-ha/run.py --config /opt/pylontech-ha/config.ini

# /etc/systemd/system/pylontech-ha.timer
[Timer]
OnCalendar=*:0/10
[Install]
WantedBy=timers.target
```

The user needs access to the serial device (group `dialout`). `./deploy.sh user@host /opt/pylontech-ha ""` copies the program without the HA package.

**Home Assistant Container (Docker):** pass the dongle into the container (`devices: - /dev/serial/by-id/usb-…:/dev/serial/by-id/usb-…`), then follow the HA OS steps; the paths are under your mapped `/config`. **HA Core (venv):** same, with the user running HA in `dialout`.

## Configuration (`config.ini`)

| Section | Key | Default | |
|---|---|---|---|
| `battery` | `device` | | serial device, use `/dev/serial/by-id/…` |
| | `baud` | `115200` | DIP switch 1 OFF = 115200, ON = 9600 |
| | `address` | `2` | RS485 address of a single module |
| | `timeout`, `retries` | `2`, `3` | seconds per reply, attempts per command |
| `history` | `file` | `history.json` | rolling cell history for the 7-day statistics (~40 kB, one write per run) |
| | `window_days` | `7` | |
| `mqtt` | `host`, `port` | | broker (`core-mosquitto` on HA OS) |
| | `username`, `password_file` | | password only in the separate file, never in the INI |
| | `client_id` | `pylontech-ha` | |
| | `base_topic` | `pylontech` | |
| | `discovery_prefix` | `homeassistant` | |
| `homeassistant` | `device_name` | `Pylontech` | HA device name → entity ids `sensor.pylontech_*` |
| | `unique_id_prefix` | `pylontech` | prefix of unique ids and discovery topics; change it for a second battery |
| | `via_device` | | optional identifier of a parent device |
| | `expire_after` | `1800` | seconds without data before entities become unavailable (3 missed runs) |

**Two batteries** (two separate modules, each with its own dongle): run two copies with different `config.ini` files and give the second one its own `device`, `history.file`, `client_id`, `base_topic`, `device_name` and `unique_id_prefix`.

## Entities

With the default device name `Pylontech`:

| | |
|---|---|
| Pack | `sensor.pylontech_pack_voltage`, `_current`, `_power`, `_soc_bms_remaining_full`, `_remaining_capacity`, `_full_capacity`, `_cycles` |
| Cells | `sensor.pylontech_cell_01_voltage` … `_cell_15_voltage`, `_cell_min_voltage`, `_cell_max_voltage`, `_cell_min_id`, `_cell_max_id`, `_cell_spread`, `_cell_spread_7d_avg`, `_cell_spread_7d_max` |
| Table | `sensor.pylontech_cell_table`: state = samples in the 7-day window; attributes `cells[]` (`cell`, `now`, `min`, `max`, `avg`, `dev`, `dev_now`, `dev_max` = largest deviation from the pack mean in 7 days), `spread_now`, `spread_avg_7d`, `spread_max_7d`, `history_days`, `updated` |
| Temperatures | `sensor.pylontech_bms_temperature`, `_temperature_cells_1_4`, `_5_8`, `_9_12`, `_13_15` |
| BMS limits | `sensor.pylontech_charge_voltage_limit`, `_discharge_voltage_limit`, `_charge_current_limit`, `_discharge_current_limit` |
| Status | `sensor.pylontech_alarms` (`OK` or a readable list), `sensor.pylontech_bms_state` (`charging` / `discharging` / `idle`), binary sensors `charge_enabled`, `discharge_enabled`, `charge_immediately_request`, `charge_mosfet`, `discharge_mosfet`, `fully_charged`, `heater`, `bms_protection` (problem) |

Notes: current is positive while charging. The SOC here is remaining ÷ full capacity as reported over RS485; an inverter or GX device reading SOC over CAN may show a slightly different number. Cell values are in mV.

## MQTT topics

| Topic | Retained | Content |
|---|---|---|
| `homeassistant/sensor/pylontech_<key>/config`, `homeassistant/binary_sensor/pylontech_<key>/config` | yes | discovery |
| `pylontech/status` | yes | `online` / `offline` (offline after a failed read) |
| `pylontech/state` | no | all values, flat JSON |
| `pylontech/cells` | no | the per-cell 7-day table |

## Troubleshooting

| Symptom | Check |
|---|---|
| `read failed: no response` | A/B swapped (swap the two wires), wrong port (RS485, not CAN/CONSOLE), DIP switch 1 / `baud`, adapter without transceiver. Try `python3 -m pylontech_rs485 -d /dev/serial/by-id/… probe` in the deployed folder. |
| `port busy` | something else has the dongle open (another copy of this, a serial terminal). |
| `bad user name or password` | MQTT user / `mqtt.pw` (no trailing newline needed, it is stripped). |
| Entities unavailable | 30 min without data (`expire_after`) or `offline` after a failed read; run the action by hand and read `stderr`. |
| Action not found | the package isn't loaded: step 4, then restart. |
| `could not connect` on HA OS | use `host = core-mosquitto`. |

Run it by hand with output: Terminal add-on can't run it (no Python there), so use the action in Developer tools, or on another Linux host `./run.py -c config.ini --dry-run` (reads and prints, publishes nothing; it does update the history file).

## Updating

`git pull && git submodule update --init`, then deploy again (step 3). Your `config.ini`, password and history stay.

## Development

```bash
python3 -m unittest discover -s tests -t .
```

Uses the frames recorded from a real US3000C in the submodule, a fake serial port, a fake MQTT client and a fake local broker: no hardware, no network. Updating the battery library: `cd lib/pylontech-rs485 && git fetch --tags && git checkout v0.x.y`, run the tests, commit.

| Path | |
|---|---|
| `lib/pylontech-rs485/` | submodule: the battery library |
| `pylontech_ha/publisher.py` | read → history → state JSON → discovery + publish |
| `pylontech_ha/mqtt.py` | minimal MQTT 3.1.1 client (QoS 0, retain, user/password, no TLS) |
| `run.py` | entry point for a checkout or a deployed copy |
| `ha/packages/pylontech.yaml` | HA package: `shell_command` + automation every 10 min |
| `dashboard/mkdash.py` | dashboard generator |
| `deploy.sh` | copy to a host over SSH, or `--stage DIR` |

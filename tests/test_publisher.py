import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
import io

from tests.helpers import FakeClient, FakePort  # noqa: F401 (sets sys.path)
from pylontech_rs485 import Battery
from pylontech_ha import publisher

# Keys and unique IDs of the first version; must stay identical so existing installs carry on.
LEGACY_STATE_KEYS = set(
    "voltage current power remaining_ah full_ah soc cycles temp_bms alarms status_raw "
    "charge_voltage_limit discharge_voltage_limit charge_current_limit discharge_current_limit "
    "charge_enabled discharge_enabled charge_immediately model sw_version serial spread_avg_7d "
    "spread_max_7d spread_min_7d samples_7d history_days cell_min cell_max cell_min_id cell_max_id "
    "spread".split()) | {"cell_%02d" % i for i in range(1, 16)} | {"temp_%d" % i for i in range(1, 5)}

LEGACY_UNIQUE_IDS = {"pylontech_" + k for k in (
    "voltage current power soc remaining_ah full_ah cycles temp_bms cell_min cell_max cell_min_id "
    "cell_max_id spread spread_avg_7d spread_max_7d charge_voltage_limit discharge_voltage_limit "
    "charge_current_limit discharge_current_limit alarms cell_table charge_enabled discharge_enabled "
    "charge_immediately".split())} | {"pylontech_cell_%02d" % i for i in range(1, 16)} | \
    {"pylontech_temp_%d" % i for i in range(1, 5)}


# Added in 0.2.0 (decoded 0x44 status bytes).
NEW_STATE_KEYS = set("charge_mosfet discharge_mosfet fully_charged heater protection bms_state".split())
NEW_UNIQUE_IDS = {"pylontech_" + k for k in NEW_STATE_KEYS}


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ini = os.path.join(self.tmp.name, "config.ini")
        with open(self.ini, "w") as f:
            f.write("[history]\nfile = %s\n[mqtt]\nhost = 127.0.0.1\n[homeassistant]\nvia_device = parent_host\n"
                    % os.path.join(self.tmp.name, "h.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *extra):
        client = FakeClient()
        out = io.StringIO()
        with redirect_stdout(out):
            rc = publisher.main(["-c", self.ini] + list(extra), battery=Battery(None, port=FakePort()),
                                client=client)
        return rc, client, out.getvalue()

    def test_publish_matches_legacy(self):
        rc, client, _ = self.run_main()
        self.assertEqual(rc, 0)
        topics = {t: (json.loads(p) if p.startswith("{") else p, r) for t, p, r in client.published}
        state, _ = topics["pylontech/state"]
        self.assertEqual(set(state), LEGACY_STATE_KEYS | NEW_STATE_KEYS)
        self.assertEqual((state["charge_mosfet"], state["discharge_mosfet"], state["protection"]), (True, True, False))
        self.assertEqual((state["fully_charged"], state["heater"], state["bms_state"]), (False, False, "charging"))
        self.assertEqual(state["cell_09"], 3312)
        self.assertEqual(state["alarms"], "OK")
        self.assertEqual(state["status_raw"], "00 0E 80 00 00 00")
        self.assertEqual(state["serial"], "TESTSERIAL000001")
        self.assertEqual(topics["pylontech/status"], ("online", True))
        uids = {p["unique_id"] for t, (p, r) in topics.items() if t.endswith("/config")}
        self.assertEqual(uids, LEGACY_UNIQUE_IDS | NEW_UNIQUE_IDS)
        prot = topics["homeassistant/binary_sensor/pylontech_protection/config"][0]
        self.assertEqual(prot["device_class"], "problem")
        self.assertNotIn("icon", prot)
        self.assertTrue(all(r for t, (p, r) in topics.items() if t.endswith("/config")))
        cells, retain = topics["pylontech/cells"]
        self.assertFalse(retain)
        self.assertEqual(set(cells["cells"][0]), {"cell", "now", "min", "max", "avg", "dev", "dev_now", "dev_max"})
        self.assertEqual(len(cells["cells"]), 15)
        dev = topics["homeassistant/sensor/pylontech_voltage/config"][0]["device"]
        self.assertEqual(dev["via_device"], "parent_host")
        self.assertEqual(dev["identifiers"], ["pylontech_TESTSERIAL000001"])

    def test_unique_id_prefix(self):
        with open(self.ini, "a") as f:
            f.write("unique_id_prefix = battery2\n")
        rc, client, _ = self.run_main()
        configs = {t: json.loads(p) for t, p, r in client.published if t.endswith("/config")}
        self.assertIn("homeassistant/sensor/battery2_voltage/config", configs)
        self.assertIn("homeassistant/binary_sensor/battery2_protection/config", configs)
        self.assertTrue(all(c["unique_id"].startswith("battery2_") for c in configs.values()))
        self.assertEqual(len(configs), len(LEGACY_UNIQUE_IDS | NEW_UNIQUE_IDS))

    def test_dashboard_defaults(self):
        import importlib.util, os as _os
        spec = importlib.util.spec_from_file_location(
            "mkdash", _os.path.join(_os.path.dirname(__file__), "..", "dashboard", "mkdash.py"))
        mk = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mk)
        d = json.dumps(mk.build())
        self.assertIn("sensor.pylontech_cell_15_voltage", d)
        self.assertNotIn("cell_16", d)
        d2 = json.dumps(mk.build(prefix="house", cells=16))
        self.assertIn("binary_sensor.house_bms_protection", d2)
        self.assertIn("sensor.house_cell_16_voltage", d2)

    def test_history_grows(self):
        self.run_main()
        rc, client, _ = self.run_main()
        state = json.loads(dict((t, p) for t, p, r in client.published)["pylontech/state"])
        self.assertIn(state["samples_7d"], (1, 2))  # 2 runs; same second -> replaced, not duplicated
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "h.json")))

    def test_dry_run_publishes_nothing(self):
        rc, client, out = self.run_main("--dry-run")
        self.assertEqual(rc, 0)
        self.assertEqual(client.published, [])
        self.assertIn("pylontech/state ", out)

    def test_read_failure_publishes_offline(self):
        class DeadPort(FakePort):
            def transact(self, data, timeout=2.0):
                return b""
        client = FakeClient()
        bat = Battery(None, port=DeadPort(), retries=1)
        rc = publisher.main(["-c", self.ini], battery=bat, client=client)
        self.assertEqual(rc, 1)
        self.assertEqual(client.published, [("pylontech/status", "offline", True)])


if __name__ == "__main__":
    unittest.main()

"""Shared test setup: import paths for the submodule + a replaying fake serial port."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "pylontech-rs485")
for p in (os.path.join(LIB, "src"), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

# Recorded frames from the submodule's tests (loaded by path: both repos have a `tests` package).
_ns = {}
with open(os.path.join(LIB, "tests", "frames.py")) as _f:
    exec(compile(_f.read(), _f.name, "exec"), _ns)
FRAMES = _ns["FRAMES"]


class FakePort:
    def __init__(self):
        self.by_request = {req.encode(): resp.encode() for req, resp in FRAMES.values()}

    def open(self):
        return self

    def close(self):
        pass

    def transact(self, data, timeout=2.0):
        return self.by_request.get(data, b"")


class FakeClient:
    def __init__(self):
        self.published = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))

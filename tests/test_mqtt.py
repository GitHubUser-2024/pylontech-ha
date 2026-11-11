import socket
import threading
import unittest

from tests import helpers  # noqa: F401
from pylontech_ha import mqtt


def read_packet(conn):
    hdr = conn.recv(1)
    if not hdr:
        return None
    mult, n = 1, 0
    while True:
        b = conn.recv(1)[0]
        n += (b & 0x7F) * mult
        mult *= 128
        if not b & 0x80:
            break
    body = b""
    while len(body) < n:
        body += conn.recv(n - len(body))
    return hdr[0], body


class FakeBroker(threading.Thread):
    def __init__(self, rc=0):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.rc, self.packets = rc, []

    def run(self):
        conn, _ = self.srv.accept()
        with conn:
            while True:
                p = read_packet(conn)
                if p is None:
                    break
                self.packets.append(p)
                if p[0] == 0x10:
                    conn.sendall(bytes([0x20, 2, 0, self.rc]))
                    if self.rc:
                        break
                if p[0] == 0xE0:
                    break
        self.srv.close()


class MqttTest(unittest.TestCase):
    def test_varint(self):
        self.assertEqual(mqtt._varint(0), b"\x00")
        self.assertEqual(mqtt._varint(127), b"\x7f")
        self.assertEqual(mqtt._varint(128), b"\x80\x01")
        self.assertEqual(mqtt._varint(16383), b"\xff\x7f")
        self.assertEqual(mqtt._varint(2097152), b"\x80\x80\x80\x01")

    def test_connect_packet_flags(self):
        p = mqtt.connect_packet("id", "u", "pw")
        self.assertEqual(p[0], 0x10)
        self.assertEqual(p[2:10], b"\x00\x04MQTT\x04\xc2")

    def test_publish_to_fake_broker(self):
        b = FakeBroker()
        b.start()
        big = "x" * 5000  # multi-byte remaining length
        with mqtt.Client("127.0.0.1", b.port, "user", "secret", "cid") as c:
            c.publish("a/b", "online", retain=True)
            c.publish("a/c", big)
        b.join(5)
        types = [t for t, _ in b.packets]
        self.assertEqual(types, [0x10, 0x31, 0x30, 0xE0])
        self.assertTrue(b.packets[0][1].endswith(b"\x00\x04user\x00\x06secret"))
        self.assertEqual(b.packets[1][1], b"\x00\x03a/bonline")
        self.assertEqual(len(b.packets[2][1]), 2 + 3 + 5000)

    def test_bad_password(self):
        b = FakeBroker(rc=4)
        b.start()
        with self.assertRaisesRegex(mqtt.MqttError, "bad user name"):
            mqtt.Client("127.0.0.1", b.port, "u", "wrong").connect()
        b.join(5)


if __name__ == "__main__":
    unittest.main()

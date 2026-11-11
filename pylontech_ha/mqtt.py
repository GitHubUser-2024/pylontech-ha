"""Tiny MQTT 3.1.1 publisher (QoS 0 only), standard library only.

Enough for publishing discovery and state messages: CONNECT (optional username /
password), PUBLISH with optional retain, DISCONNECT. No subscriptions, no TLS.
"""

import socket
import struct


class MqttError(Exception):
    pass


CONNACK_CODES = {
    1: "unacceptable protocol version",
    2: "identifier rejected",
    3: "server unavailable",
    4: "bad user name or password",
    5: "not authorized",
}


def _varint(n):
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            return bytes(out)


def _str(s):
    b = s.encode("utf-8") if isinstance(s, str) else s
    return struct.pack("!H", len(b)) + b


def connect_packet(client_id, username=None, password=None, keepalive=60):
    flags = 0x02  # clean session
    payload = _str(client_id)
    if username is not None:
        flags |= 0x80
        payload += _str(username)
        if password is not None:
            flags |= 0x40
            payload += _str(password)
    var = _str("MQTT") + bytes([4, flags]) + struct.pack("!H", keepalive)
    body = var + payload
    return b"\x10" + _varint(len(body)) + body


def publish_packet(topic, payload, retain=False):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    body = _str(topic) + payload
    return bytes([0x30 | (1 if retain else 0)]) + _varint(len(body)) + body


DISCONNECT = b"\xe0\x00"


class Client:
    def __init__(self, host, port=1883, username=None, password=None, client_id="pylontech-ha", timeout=10):
        self.host, self.port, self.timeout = host, port, timeout
        self.username, self.password, self.client_id = username, password, client_id
        self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise MqttError("connection closed by broker")
            buf += chunk
        return buf

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.sendall(connect_packet(self.client_id, self.username, self.password))
        ack = self._recv_exact(4)
        if ack[0] != 0x20 or ack[1] != 0x02:
            raise MqttError("unexpected reply to CONNECT: %r" % ack)
        if ack[3] != 0:
            raise MqttError("CONNECT refused: %s" % CONNACK_CODES.get(ack[3], ack[3]))

    def publish(self, topic, payload, retain=False):
        self.sock.sendall(publish_packet(topic, payload, retain))

    def close(self):
        if self.sock is not None:
            try:
                self.sock.sendall(DISCONNECT)
            except OSError:
                pass
            self.sock.close()
            self.sock = None

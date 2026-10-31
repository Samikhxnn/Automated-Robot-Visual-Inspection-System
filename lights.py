
import socket
import struct


class LightsController:
    def __init__(self, config):
        self.ip = config["ip"]
        self.port = int(config["port"])
        self.unit_id = int(config.get("unit_id", 1))
        self.timeout = float(config.get("timeout", 3))
        self.max_channels = int(config.get("max_channels", 30))

        self.enabled_channels = {
            int(ch) for ch in config.get("enabled_channels", [])
        }

        if not 1 <= self.max_channels <= 30:
            raise ValueError("max_channels must be between 1 and 30")

        for channel in self.enabled_channels:
            self._validate_channel(channel)

        self.sock = None
        self.transaction_id = 0

    def _validate_channel(self, channel):
        if not 1 <= channel <= self.max_channels:
            raise ValueError(f"Invalid relay channel: {channel}")

        if channel not in self.enabled_channels:
            raise ValueError(
                f"Channel {channel} is not enabled in YAML"
            )

    def connect(self):
        if self.sock is not None:
            return

        self.sock = socket.create_connection(
            (self.ip, self.port),
            timeout=self.timeout
        )
        self.sock.settimeout(self.timeout)
        print(f"Relay connected: {self.ip}:{self.port}")

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _receive_exactly(self, size):
        data = bytearray()

        while len(data) < size:
            chunk = self.sock.recv(size - len(data))

            if not chunk:
                raise ConnectionError("Relay closed the connection")

            data.extend(chunk)

        return bytes(data)

    def _write_single_coil(self, address, value):
        if self.sock is None:
            raise ConnectionError("Connect to relay first")

        self.transaction_id = (self.transaction_id + 1) % 65536
        pdu = struct.pack(">BHH", 5, address, value)

        header = struct.pack(
            ">HHHB",
            self.transaction_id,
            0,
            len(pdu) + 1,
            self.unit_id
        )

        self.sock.sendall(header + pdu)

        response_header = self._receive_exactly(7)
        tid, protocol, length, unit = struct.unpack(
            ">HHHB", response_header
        )

        if tid != self.transaction_id or protocol != 0:
            raise RuntimeError("Invalid Modbus response header")

        if unit != self.unit_id or length < 2:
            raise RuntimeError("Unexpected Modbus response")

        response = self._receive_exactly(length - 1)

        if response[0] & 0x80:
            raise RuntimeError(
                f"Modbus exception: {response.hex()}"
            )

        if response != pdu:
            raise RuntimeError(
                f"Unexpected relay response: {response.hex()}"
            )

    def _set_light(self, channel, turn_on):
        channel = int(channel)
        self._validate_channel(channel)

        # Assumes channel 1 maps to coil address 0.
        address = channel - 1
        value = 0xFF00 if turn_on else 0x0000

        self._write_single_coil(address, value)

        print(
            f"Relay channel {channel}: "
            f"{'ON' if turn_on else 'OFF'}"
        )

    def light_on(self, channel):
        self._set_light(channel, True)

    def light_off(self, channel):
        self._set_light(channel, False)

    def lights_on(self, channels):
        for channel in channels:
            self.light_on(channel)

    def lights_off(self, channels):
        for channel in channels:
            self.light_off(channel)

    def all_enabled_off(self):
        self.lights_off(sorted(self.enabled_channels))

"""Offline checks of network scope, request semantics and hostile replies."""
import importlib.util
from pathlib import Path
import socket
import struct
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "udp_discovery", Path(__file__).resolve().parents[1] / "tools" / "udp_discovery.py")
udp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(udp)


class DiscoveryTests(unittest.TestCase):
    def test_invalid_targets_and_limits_never_open_socket(self):
        for host in ("example.com", "8.8.8.8", "127.0.0.1", "169.254.1.2", "::1",
                     "224.0.0.251", "192.168.1.255", "0.0.0.0", "100.64.0.1"):
            with self.subTest(host=host), patch.object(udp.socket, "socket") as factory:
                with self.assertRaises(ValueError):
                    udp.probe(host, "coap")
                factory.assert_not_called()
        for timeout in (0, -1, 6, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), patch.object(udp.socket, "socket") as factory:
                with self.assertRaises(ValueError):
                    udp.probe("192.168.1.123", "coap", timeout)
                factory.assert_not_called()

    def test_queries_only_request_discovery(self):
        coap = udp.coap_query(0x1234, b"test")
        self.assertEqual(coap[:8], b"\x54\x01\x12\x34test")  # NON GET
        # Independently decode options: only two Uri-Path segments, no payload.
        pos, option, paths = 8, 0, []
        while pos < len(coap):
            header = coap[pos]
            pos += 1
            option += header >> 4
            length = header & 15
            self.assertEqual(option, 11)
            paths.append(coap[pos:pos+length])
            pos += length
        self.assertEqual(paths, [b".well-known", b"core"])
        dns = udp.mdns_query(0x1234)
        self.assertEqual(struct.unpack("!6H", dns[:12]), (0x1234, 0, 1, 0, 0, 0))
        self.assertEqual(dns[-4:], b"\x00\x0c\x00\x01")  # PTR, IN

    def test_response_correlation_and_no_raw_payload(self):
        response = b"\x54\x45\x12\x34test\xffsecret-IP-temperature"
        self.assertEqual(udp.summarize("coap", response, 0x1234, b"test"),
                         {"status": "response", "code": "2.05", "bytes": len(response)})
        for data in (b"", b"\x5f\x45\x00\x00", response.replace(b"test", b"nope")):
            self.assertIsNone(udp.summarize("coap", data, 0x1234, b"test"))
        self.assertIsNone(udp.summarize("mdns", udp.mdns_query(1), 1, b""))
        self.assertIsNone(udp.summarize("mdns", struct.pack("!6H", 2, 0x8400, 0, 1, 0, 0), 1, b""))

    def test_silence_sends_one_packet_without_retry_or_dns(self):
        with patch.object(udp.socket, "socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.recv.side_effect = socket.timeout
            result = udp.probe("192.168.1.123", "coap")
            sock.connect.assert_called_once_with(("192.168.1.123", 5683))
            sock.send.assert_called_once()
            sock.setsockopt.assert_not_called()
            self.assertEqual(result["status"], "no_matching_response")

    def test_unrelated_or_oversized_replies_cannot_keep_probe_running(self):
        with patch.object(udp.socket, "socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.recv.return_value = b"x" * (udp.MAX_REPLY + 1)
            self.assertEqual(udp.probe("192.168.1.123", "mdns")["status"], "no_matching_response")
            self.assertEqual(sock.recv.call_count, 8)
            sock.send.assert_called_once()

    def test_errors_do_not_expose_addresses(self):
        with patch.object(udp.socket, "socket") as factory:
            sock = factory.return_value.__enter__.return_value
            sock.connect.side_effect = OSError(101, "secret address")
            self.assertEqual(udp.probe("192.168.1.123", "coap"),
                             {"protocol": "coap", "port": 5683,
                              "status": "network_error", "errno": 101})


if __name__ == "__main__":
    unittest.main()

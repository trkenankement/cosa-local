"""Offline regressions: resource limits and argument validation, no device traffic."""
import asyncio
import importlib.util
import io
from pathlib import Path
import struct
import threading
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dns = load("dns_logger")
scanner = load("port_scan")


class DnsTests(unittest.TestCase):
    def test_dns_event_logging_is_rate_limited(self):
        with patch.object(dns.time, "monotonic", side_effect=[0, 0, 0, 0, 0, 0, 2]), \
             patch("builtins.print") as output:
            logger = dns.RateLimitedLogger(limit=2)
            for _ in range(5):
                logger.write("query")
            logger.write("next")
        self.assertEqual(output.call_count, 4)
        output.assert_any_call("  ! 3 gunluk satiri atlandi", flush=True)

    def test_workers_and_pending_queue_are_bounded_and_capacity_is_reused(self):
        gate, full, drained = threading.Event(), threading.Event(), threading.Event()
        lock = threading.Lock()
        counts = {"active": 0, "peak": 0, "completed": 0}

        def slow_forward(*_args):
            with lock:
                counts["active"] += 1
                counts["peak"] = max(counts["peak"], counts["active"])
                if counts["active"] == 2:
                    full.set()
            if not gate.wait(5):
                raise RuntimeError("test gate timed out")
            with lock:
                counts["active"] -= 1
                counts["completed"] += 1
                if counts["completed"] == 3:
                    drained.set()

        with patch.object(dns, "forward", slow_forward):
            pool = dns.BoundedForwarder(object(), "192.168.1.1", workers=2, queue_size=1)
            try:
                self.assertTrue(pool.submit(b"one", ("192.168.1.2", 1000)))
                self.assertTrue(pool.submit(b"two", ("192.168.1.2", 1001)))
                self.assertTrue(full.wait(2))
                self.assertTrue(pool.submit(b"queued", ("192.168.1.2", 1002)))
                self.assertTrue(all(not pool.submit(b"overload", ("192.168.1.2", 1003))
                                    for _ in range(1000)))
                self.assertEqual(counts["peak"], 2)
                gate.set()
                self.assertTrue(drained.wait(2))
            finally:
                gate.set()
                pool.close()
        self.assertEqual(counts["completed"], 3)

    def test_worker_failure_releases_capacity(self):
        with patch.object(dns, "forward", side_effect=OSError("offline")):
            pool = dns.BoundedForwarder(object(), "192.168.1.1", workers=1, queue_size=0)
            try:
                self.assertTrue(pool.submit(b"query", ("192.168.1.2", 1000)))
                # Drain workers without closing the pool before checking reuse.
                pool._executor.submit(lambda: None).result(timeout=2)
                self.assertTrue(pool.submit(b"retry", ("192.168.1.2", 1001)))
            finally:
                pool.close()

    def test_submit_failure_releases_capacity(self):
        with patch.object(dns, "forward"):
            pool = dns.BoundedForwarder(object(), "192.168.1.1", workers=1, queue_size=0)
            try:
                with patch.object(pool._executor, "submit", side_effect=RuntimeError("unavailable")):
                    with self.assertRaises(RuntimeError):
                        pool.submit(b"query", ("192.168.1.2", 1000))
                self.assertTrue(pool.submit(b"retry", ("192.168.1.2", 1001)))
            finally:
                pool.close()

    def test_invalid_limits_fail_before_opening_socket(self):
        for args in (("--workers", "0"), ("--workers", "-1"), ("--queue-size", "-1")):
            with self.subTest(args=args), patch("sys.argv", ["dns_logger.py", *args]), \
                    patch("sys.stderr", new_callable=io.StringIO), \
                    patch.object(dns.socket, "socket") as socket, \
                    self.assertRaises(SystemExit) as error:
                dns.main()
            self.assertEqual(error.exception.code, 2)
            socket.assert_not_called()

    def test_zero_queue_is_supported(self):
        pool = dns.BoundedForwarder(object(), "192.168.1.1", workers=1, queue_size=0)
        pool.close()

    def test_dns_question_parser_still_reads_valid_queries(self):
        packet = struct.pack("!6H", 1, 0x100, 1, 0, 0, 0) + b"\x07example\x03org\x00\x00\x01\x00\x01"
        self.assertEqual(dns.parse_question(packet), ("example.org", "A"))
        self.assertIsNone(dns.parse_question(b"short"))

    def test_dns_question_rejects_terminal_controls_and_missing_class(self):
        header = struct.pack("!6H", 1, 0x100, 1, 0, 0, 0)
        for question in (b"\x03a\x1bb\x00\x00\x01\x00\x01",
                         b"\x01a\x00\x00\x01", b"\x04ab"):
            self.assertIsNone(dns.parse_question(header + question))

    def test_dns_forward_checks_peer_transaction_and_response_flag(self):
        query = struct.pack("!6H", 12, 0x100, 1, 0, 0, 0) + b"\x01a\x00\x00\x01\x00\x01"
        for ident, flags, allowed in ((12, 0x8180, True), (13, 0x8180, False), (12, 0x100, False)):
            reply = struct.pack("!6H", ident, flags, 1, 0, 0, 0) + query[12:]
            with self.subTest(ident=ident, flags=flags), patch.object(dns.socket, "socket") as factory:
                srv = unittest.mock.Mock()
                factory.return_value.recv.return_value = reply
                dns.forward(srv, query, ("127.0.0.1", 1000), "127.0.0.2")
                factory.return_value.connect.assert_called_once_with(("127.0.0.2", 53))
                factory.return_value.send.assert_called_once_with(query)
                self.assertEqual(srv.sendto.call_count, int(allowed))
                factory.return_value.close.assert_called_once()

    def test_dns_default_listens_on_loopback_only(self):
        with patch("sys.argv", ["dns_logger.py"]), patch("builtins.print"), \
             patch.object(dns.socket, "socket") as factory:
            factory.return_value.recvfrom.side_effect = KeyboardInterrupt
            dns.main()
            factory.return_value.bind.assert_called_once_with(("127.0.0.1", 53))


class ScannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_library_entry_rejects_public_reserved_and_invalid_port_ranges(self):
        cases = [(host, 1, 1) for host in ("8.8.8.8", "0.0.0.0", "192.0.2.1", "example.com", "::")]
        cases += [("127.0.0.1", start, end) for start, end in ((0, 1), (2, 1), (1, 65536))]
        for host, start, end in cases:
            with self.subTest(host=host, start=start, end=end), \
                 patch.object(scanner.asyncio, "open_connection", new_callable=AsyncMock) as connect:
                with self.assertRaises(ValueError):
                    await scanner.scan(host, start, end, 1, 1)
                connect.assert_not_called()

    async def test_invalid_concurrency_is_rejected_before_network(self):
        for concurrency in (0, -1):
            with self.subTest(concurrency=concurrency), \
                    patch.object(scanner.asyncio, "open_connection", new_callable=AsyncMock) as connect:
                with self.assertRaisesRegex(ValueError, "concurrency"):
                    await asyncio.wait_for(scanner.scan("127.0.0.1", 1, 1, 0.1, concurrency), 1)
                connect.assert_not_called()

    async def test_invalid_timeout_is_rejected_before_network(self):
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout), \
                    patch.object(scanner.asyncio, "open_connection", new_callable=AsyncMock) as connect:
                with self.assertRaisesRegex(ValueError, "timeout"):
                    await scanner.scan("127.0.0.1", 1, 1, timeout, 1)
                connect.assert_not_called()

    async def test_valid_concurrency_bounds_connections_and_preserves_open_ports(self):
        active = peak = 0

        async def probe(_host, port):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            if port % 2 == 0:
                raise OSError("closed")
            writer = unittest.mock.Mock()
            writer.wait_closed = AsyncMock()
            return object(), writer

        with patch.object(scanner.asyncio, "open_connection", side_effect=probe):
            self.assertEqual(await scanner.scan("127.0.0.1", 1, 20, 1, 3), list(range(1, 20, 2)))
        self.assertLessEqual(peak, 3)


class CliTests(unittest.TestCase):
    def test_invalid_scanner_options_fail_before_running_scan(self):
        for args in (("--concurrency", "0"), ("--concurrency", "-1"),
                     ("--timeout", "0"), ("--timeout", "nan"), ("--timeout", "inf")):
            with self.subTest(args=args), \
                    patch("sys.argv", ["port_scan.py", "127.0.0.1", *args]), \
                    patch("sys.stderr", new_callable=io.StringIO), \
                    patch.object(scanner.asyncio, "run") as run, \
                    self.assertRaises(SystemExit) as error:
                scanner.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

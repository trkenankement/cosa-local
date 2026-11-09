"""Run the suite with real outbound socket connections prohibited."""
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch


def blocked(*args, **kwargs):
    raise AssertionError("Real network traffic is prohibited during offline tests")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    with patch.object(socket.socket, "connect", blocked), \
         patch.object(socket.socket, "connect_ex", blocked), \
         patch.object(socket.socket, "sendto", blocked):
        suite = unittest.defaultTestLoader.discover(str(root / "tests"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())

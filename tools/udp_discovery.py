"""Two bounded, read-only UDP discovery queries to one configured LAN device.

No multicast, cloud, thermostat commands, retries, or raw response logging.
Silence is inconclusive: a device may ignore unicast or generic discovery.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import math
import secrets
import socket
import struct
import time

NETWORKS = tuple(ipaddress.ip_network(n) for n in
                 ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
MAX_REPLY = 4096


def require_lan(host: str) -> str:
    """Accept only literal RFC1918 IPv4, without DNS resolution."""
    address = ipaddress.ip_address(host)
    if address.version != 4 or not any(address in n for n in NETWORKS):
        raise ValueError("target must be a literal RFC1918 IPv4 address")
    # Reject common /24 network/broadcast addresses as an additional guard.
    if address.packed[-1] in (0, 255):
        raise ValueError("target must be an individual device address")
    return str(address)


def coap_query(message_id: int, token: bytes) -> bytes:
    # RFC 7252: NON GET /.well-known/core. No confirmable retransmissions.
    if len(token) != 4:
        raise ValueError("four-byte token required")
    return (struct.pack("!BBH", 0x54, 1, message_id) + token
            + b"\xbb.well-known\x04core")


def mdns_query(message_id: int) -> bytes:
    # RFC 6762 legacy unicast query, PTR service enumeration (RFC 6763 §9).
    name = b"\x09_services\x07_dns-sd\x04_udp\x05local\x00"
    return struct.pack("!6H", message_id, 0, 1, 0, 0, 0) + name + b"\x00\x0c\x00\x01"


def summarize(protocol: str, data: bytes, message_id: int, token: bytes) -> dict | None:
    """Return protocol metadata only; never echo names, values or payload."""
    if protocol == "coap":
        if len(data) < 4 or data[0] >> 6 != 1:
            return None
        tkl = data[0] & 15
        if tkl > 8 or len(data) < 4 + tkl:
            return None
        # Responses correlate by token; an empty Reset correlates by message ID.
        if len(data) == 4 and data[0] == 0x70 and data[1] == 0 and int.from_bytes(data[2:4], "big") == message_id:
            return {"status": "reset", "bytes": len(data)}
        if (data[0] >> 4) & 3 == 3:
            return None  # A Reset cannot carry a response code or payload.
        if tkl != len(token) or data[4:4+tkl] != token or data[1] >> 5 not in (2, 4, 5):
            return None
        return {"status": "response", "code": f"{data[1] >> 5}.{data[1] & 31:02}",
                "bytes": len(data)}
    if len(data) < 12:
        return None
    ident, flags, _, answers, _, _ = struct.unpack("!6H", data[:12])
    if ident != message_id or not flags & 0x8000:
        return None
    return {"status": "response", "answers": answers, "rcode": flags & 15,
            "bytes": len(data)}


def probe(host: str, protocol: str, timeout: float = 2.0) -> dict:
    host = require_lan(host)
    if not math.isfinite(timeout) or not 0 < timeout <= 5:
        raise ValueError("timeout must be finite, positive and at most five seconds")
    if protocol not in ("coap", "mdns"):
        raise ValueError("unsupported discovery protocol")
    ident, token = secrets.randbelow(65536), secrets.token_bytes(4)
    port = 5683 if protocol == "coap" else 5353
    packet = coap_query(ident, token) if protocol == "coap" else mdns_query(ident)
    result = {"protocol": protocol, "port": port}
    # Connected UDP accepts only the chosen peer. No broadcast option is enabled.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.send(packet)
            deadline = time.monotonic() + timeout
            for _ in range(8):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                data = sock.recv(MAX_REPLY + 1)
                if len(data) > MAX_REPLY:
                    continue
                info = summarize(protocol, data, ident, token)
                if info is not None:
                    return result | info
        except socket.timeout:
            pass
        except OSError as exc:
            # errno is safe; exception strings can contain the target address.
            return result | {"status": "network_error", "errno": exc.errno}
    return result | {"status": "no_matching_response"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    try:
        results = [probe(args.host, name, args.timeout) for name in ("coap", "mdns")]
    except ValueError:
        parser.error("use a single RFC1918 IPv4 device and a timeout in (0, 5]")
    print(json.dumps({"results": results, "interpretation":
                      "No response does not establish absence of a local protocol."}))


if __name__ == "__main__":
    main()

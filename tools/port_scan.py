"""Salt okunur TCP baglanti taramasi: bir cihazda hangi TCP portlari acik?

Yalnizca KENDI cihazinda kullan. Veri gonderilmez; her port icin yalnizca bir TCP
baglantisi acilip kapatilir. Sonucu terminale yazar, dosyaya kaydetmez.

Kullanim:
    python -I tools/port_scan.py <ana-makine> [--start 1] [--end 65535]
                                 [--timeout 1.0] [--concurrency 200]

Yalnizca ozel (RFC 1918) ve link-local adreslere izin verilir.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import sys


def _require_private(host: str) -> None:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        sys.exit("Hata: ana makine bir IP adresi olmali (ornek: 192.168.x.y).")
    if not (addr.is_private or addr.is_link_local):
        sys.exit("Hata: yalnizca ozel/yerel ag adreslerine izin verilir.")


async def _probe(host: str, port: int, timeout: float, sem: asyncio.Semaphore) -> int | None:
    async with sem:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        except (OSError, asyncio.TimeoutError):
            return None
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return port


async def scan(host: str, start: int, end: int, timeout: float, concurrency: int) -> list[int]:
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(_probe(host, p, timeout, sem) for p in range(start, end + 1))
    )
    return [p for p in results if p is not None]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=65535)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--concurrency", type=int, default=200)
    args = parser.parse_args()

    if not (1 <= args.start <= args.end <= 65535):
        sys.exit("Hata: port araligi 1-65535 icinde olmali.")
    _require_private(args.host)

    open_ports = asyncio.run(
        scan(args.host, args.start, args.end, args.timeout, args.concurrency)
    )
    print(f"Taranan aralik: {args.start}-{args.end}")
    print("Acik TCP portlari:", ", ".join(map(str, open_ports)) if open_ports else "yok")
    print("Not: kapali gorunen port baska servis olmadigini kanitlamaz (UDP taranmadi).")


if __name__ == "__main__":
    main()

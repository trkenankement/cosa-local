"""Salt gunluk tutan DNS yonlendirici: kim hangi adi sordu?

Gelen UDP DNS sorgusunu degistirmeden ust sunucuya iletir, cevabi aynen geri
doner. Yalnizca (istemci IP, sorgu adi, tur) terminale yazilir; dosyaya kaydedilmez.
Cevaplar degistirilmez, engelleme yapilmaz.

Yalnizca KENDI aginda, gecici olarak kullan. Ornek:
    python -I tools/dns_logger.py --client 192.168.0.125
    python -I tools/dns_logger.py --port 5353          # yerel test

Not: 53. port icin Windows guvenlik duvari izin sorabilir.
Yalnizca ozel (RFC 1918) adreslere ust sunucu olarak izin verilir, ya da --upstream ile
acikca verilen adres kullanilir.
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import threading
import time

QTYPES = {1: "A", 28: "AAAA", 5: "CNAME", 15: "MX", 16: "TXT", 12: "PTR", 33: "SRV", 65: "HTTPS"}


def parse_question(packet: bytes) -> tuple[str, str] | None:
    """Sorgu paketinden (ad, tur) cikarir; bozuk paketlerde None doner."""
    try:
        if len(packet) < 12 or struct.unpack("!H", packet[4:6])[0] < 1:
            return None
        i, labels = 12, []
        while True:
            n = packet[i]
            if n == 0:
                i += 1
                break
            if n & 0xC0:  # sorguda sikistirma beklenmez
                return None
            labels.append(packet[i + 1 : i + 1 + n].decode("ascii", "replace"))
            i += 1 + n
        qtype = struct.unpack("!H", packet[i : i + 2])[0]
        return ".".join(labels), QTYPES.get(qtype, str(qtype))
    except (IndexError, struct.error):
        return None


def forward(srv: socket.socket, data: bytes, addr: tuple, upstream: str) -> None:
    """Sorguyu ust sunucuya iletir; yavas bir sorgu digerlerini bekletmesin diye ayri is parcaciginda."""
    up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    up.settimeout(3.0)
    try:
        up.sendto(data, (upstream, 53))
        reply, _ = up.recvfrom(4096)
        srv.sendto(reply, addr)
    except OSError as exc:
        # ust sunucu yanit vermedi; istemci kendi yeniden denemesini yapar
        print(f"  ! ust sunucu hatasi: {type(exc).__name__}", flush=True)
    finally:
        up.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=53)
    ap.add_argument("--upstream", default="192.168.0.1", help="sorgularin iletilecegi DNS (varsayilan: router)")
    ap.add_argument("--client", help="yalnizca bu istemci IP'sinin sorgularini yazdir (digerleri yine iletilir)")
    args = ap.parse_args()

    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind((args.listen, args.port))
    print(f"Dinleniyor {args.listen}:{args.port} -> ust sunucu {args.upstream}:53 (Durdurmak icin Ctrl+C)", flush=True)

    try:
        while True:
            try:
                data, addr = srv.recvfrom(4096)
            except ConnectionResetError:
                continue  # Windows: onceki cevaba ICMP "port ulasilamaz" dondu; yoksay
            q = parse_question(data)
            if q and (args.client is None or addr[0] == args.client):
                print(f"{time.strftime('%H:%M:%S')}  {addr[0]:<15}  {q[1]:<5}  {q[0]}", flush=True)
            threading.Thread(target=forward, args=(srv, data, addr, args.upstream), daemon=True).start()
    except KeyboardInterrupt:
        print("\nDurduruldu.")


if __name__ == "__main__":
    sys.exit(main())

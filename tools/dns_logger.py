"""Salt gunluk tutan DNS yonlendirici: kim hangi adi sordu?

Gelen UDP DNS sorgusunu degistirmeden ust sunucuya iletir, cevabi aynen geri
doner. Yalnizca (istemci IP, sorgu adi, tur) terminale yazilir; dosyaya kaydedilmez.
Cevaplar degistirilmez, engelleme yapilmaz.

Yalnizca KENDI aginda, gecici olarak kullan. Ornek:
    python -I tools/dns_logger.py --listen 192.168.0.10 --client 192.168.0.125
    python -I tools/dns_logger.py --port 5353          # yerel test

Not: 53. port icin Windows guvenlik duvari izin sorabilir.
Yalnizca ozel (RFC 1918) adreslere ust sunucu olarak izin verilir, ya da --upstream ile
acikca verilen adres kullanilir.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import socket
import struct
import sys
import threading
import time

QTYPES = {1: "A", 28: "AAAA", 5: "CNAME", 15: "MX", 16: "TXT", 12: "PTR", 33: "SRV", 65: "HTTPS"}


class BoundedForwarder:
    """Limit running and queued requests; drop overload so clients can retry."""

    def __init__(self, srv, upstream, workers=32, queue_size=128):
        if workers < 1 or queue_size < 0:
            raise ValueError("workers must be positive and queue_size non-negative")
        self.srv, self.upstream = srv, upstream
        self._slots = threading.BoundedSemaphore(workers + queue_size)
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dns-forward")

    def submit(self, data, addr):
        if not self._slots.acquire(blocking=False):
            return False
        try:
            future = self._executor.submit(forward, self.srv, data, addr, self.upstream)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _future: self._slots.release())
        return True

    def close(self):
        self._executor.shutdown(wait=True, cancel_futures=True)


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
            label = packet[i + 1 : i + 1 + n]
            if len(label) != n or any(c < 33 or c > 126 for c in label):
                return None  # Do not print terminal controls or binary labels.
            labels.append(label.decode("ascii"))
            i += 1 + n
            if i - 12 > 254:
                return None
        if len(packet) < i + 4:
            return None
        qtype = struct.unpack("!H", packet[i : i + 2])[0]
        return ".".join(labels), QTYPES.get(qtype, str(qtype))
    except (IndexError, struct.error):
        return None


def forward(srv: socket.socket, data: bytes, addr: tuple, upstream: str) -> None:
    """Sorguyu ust sunucuya iletir; sinirli isci havuzunda calisir."""
    up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    up.settimeout(3.0)
    try:
        # Connected UDP rejects packets from a different source address/port.
        up.connect((upstream, 53))
        up.send(data)
        reply = up.recv(4096)
        if len(data) >= 12 and len(reply) >= 12 and reply[:2] == data[:2] and reply[2] & 0x80:
            srv.sendto(reply, addr)
    except OSError as exc:
        # ust sunucu yanit vermedi; istemci kendi yeniden denemesini yapar
        print(f"  ! ust sunucu hatasi: {type(exc).__name__}", flush=True)
    finally:
        up.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--listen", default="127.0.0.1", help="LAN kullanimi icin yerel ag IP'sini acikca belirt")
    ap.add_argument("--port", type=int, default=53)
    ap.add_argument("--upstream", default="192.168.0.1", help="sorgularin iletilecegi DNS (varsayilan: router)")
    ap.add_argument("--client", help="yalnizca bu istemci IP'sinin sorgularini yazdir (digerleri yine iletilir)")
    ap.add_argument("--workers", type=int, default=32, help="en fazla eszamanli DNS sorgusu (varsayilan: 32)")
    ap.add_argument("--queue-size", type=int, default=128, help="bekleyen sorgu siniri (varsayilan: 128)")
    args = ap.parse_args()
    if args.workers < 1 or args.queue_size < 0:
        ap.error("--workers en az 1, --queue-size en az 0 olmali")

    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind((args.listen, args.port))
    print(f"Dinleniyor {args.listen}:{args.port} -> ust sunucu {args.upstream}:53 (Durdurmak icin Ctrl+C)", flush=True)

    forwarder = BoundedForwarder(srv, args.upstream, args.workers, args.queue_size)
    try:
        while True:
            try:
                data, addr = srv.recvfrom(4096)
            except ConnectionResetError:
                continue  # Windows: onceki cevaba ICMP "port ulasilamaz" dondu; yoksay
            q = parse_question(data)
            if q and (args.client is None or addr[0] == args.client):
                print(f"{time.strftime('%H:%M:%S')}  {addr[0]:<15}  {q[1]:<5}  {q[0]}", flush=True)
            forwarder.submit(data, addr)
    except KeyboardInterrupt:
        print("\nDurduruldu.")
    finally:
        forwarder.close()
        srv.close()


if __name__ == "__main__":
    sys.exit(main())

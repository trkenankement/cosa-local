# Yerel Protokol Keşfi

Amaç: cihazın internetsiz, yerel ağda nasıl kontrol edilebileceğini **ölçerek** belirlemek. Tahmin yürütmeyiz; her bulgu kanıtla kaydedilir.

> Kendi cihazın dışındaki cihazlarda yapma. Bu araçlar yalnızca sahibi olduğun cihaz içindir.
> Çıktılara MAC, IP, seri numarası veya belirteç girerse depoya **koyma** (`scan-results/` ve `captures/` git tarafından yok sayılır).

## Aşama 1 — Pasif ve salt okunur

| Adım | Araç | Ne öğreniriz |
|---|---|---|
| Cihaz kimliği | Router cihaz listesi / ARP | Hangi fiziksel cihaz Wi-Fi'da? (termostat mı, alıcı mı) |
| Üretici ön eki | MAC OUI sorgusu | Çip ailesi ipucu (ör. Espressif) |
| TCP port taraması | `tools/port_scan.py` | Açık yerel servis var mı? |
| mDNS / SSDP | Pasif dinleme | Cihaz kendini duyuruyor mu? |

**Hangi cihaz Wi-Fi'da?** Termostatı pilinden/adaptöründen, ardından alıcıyı prizden çıkarıp router'da hangisinin listeden düştüğüne bak. Bir seferde yalnızca birini dene, ısıtma sezonunda kombiyi kapalı bırakma.

## Aşama 2 — Trafik gözlemi (müdahaleci)

Cihazın dışarı giden trafiğini gözlemlemek için cihazı geçici olarak kendi kontrol ettiğin bir ağ geçidi (ör. mini PC / Linux köprü) arkasına alırız. Bakılacaklar:

- Hedef ana makine adları (DNS) ve portlar.
- Protokol: MQTT, HTTPS, WebSocket, CoAP, özel UDP/TCP.
- TLS varsa sertifika sabitleme (pinning) var mı?

**Karar noktası:**

| Bulgu | Sonuç |
|---|---|
| Cihaz yerel bir arayüz sunuyor | Entegrasyonu bu arayüze yaz. |
| Cihaz yalnızca buluta bağlanıyor, TLS sabitli | Yerel kontrol mümkün değil; belgeleyip dur. |
| Cihaz yalnızca buluta bağlanıyor, TLS sabit değil | Yerel bir sunucuyla taklit mümkün olabilir ama kırılgandır ve cihaz sürümüne bağlıdır. Ayrıca değerlendirilir. |

## Aşama 3 — Donanım (yalnızca son çare)

Cihazı açmak, firmware yazmak 230V alıcı ünitede **önerilmez** ([SECURITY.md](../SECURITY.md)). Ancak tüm yazılım yolları tükenir ve kullanıcı riski kabul ederse ayrı bir belgede ele alınır.

## Bulgu kaydı

Her bulguyu aşağıya `[ölçüldü]` / `[varsayım]` etiketiyle ekle. IP, MAC ve seri numarası **yazma**.

- _(henüz bulgu yok)_

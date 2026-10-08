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

### 2026-10-08

- `[ölçüldü]` Wi-Fi'daki Cosa cihazının MAC ön eki Espressif Inc. adına kayıtlı (ESP32/ESP8266 ailesi ipucu; model kanıtı değil).
- `[ölçüldü]` Tam TCP taraması (1–65535, zaman aşımı 1,5 sn): **açık port yok.** Ping yanıt veriyor (2–350 ms dalgalı; Wi-Fi güç tasarrufu olası). Dalgalı gecikme nedeniyle bazı bağlantı denemeleri zaman aşımına uğramış olabilir; cihazın hiç TCP servisi olmadığı **kesin kanıtlanmadı**.
- `[ölçüldü]` Pasif mDNS dinlemesi (45 sn): sonuçsuz. Dinleyici ağdaki hiçbir cihazdan paket alamadı, bu yüzden cihazın mDNS kullanmadığı söylenemez.
- `[varsayım]` Açık TCP portu olmaması, cihazın yalnızca dışa bağlanan bir istemci olduğuna (bulut, MQTT vb.) işaret edebilir. Doğrulama için Aşama 2 (trafik gözlemi) gerekir.
- `[açık]` Wi-Fi'daki parçanın oda termostatı mı, alıcı ünite mi olduğu doğrulanmadı.
- `[açık]` UDP portları taranmadı.

### Üretici belgelerinden (2026-10-08)

Kaynaklar: Nuvia `Cosa_v5_Installation_User_Manual.pdf` ve `Cosa_Product_Docs_v5.pdf` (resmî dosya sunucusu; telif nedeniyle depoya konmadı).

- `[belgeli]` Alıcı ünite model ailesi **C5KKU…** (ör. `C5KKU1-230V`), oda termostatı ailesi **C5CTU…**.
- `[belgeli]` **Her iki cihaz da 2.4 GHz bandında kablosuz haberleşir** ve verileri "bulut tabanlı sistemle veya eşleştirilmiş diğer cihazlarla" paylaşır.
- `[belgeli]` İnternet bağlantısını **ya alıcı ünite ya da termostat** kurar. Alıcı ünite uzaksa termostat (adaptörle beslenirse) Wi-Fi'ya bağlanabilir; uygulamada "Reset Device → Continue Installation" ile. Yani Wi-Fi'daki cihazın hangisi olduğu kuruluma bağlıdır.
- `[belgeli]` Wi-Fi: yalnızca 2.4 GHz; WPA/WPA2/WPA+WPA2. Alıcıda "Wifi" düğmesi (uzun basış) bağlantı kurulumunu hazırlar; kurulum Cosa mobil uygulamasıyla adım adım yapılır.
- `[belgeli]` Termostat ↔ alıcı eşleşmesi ayrı bir mekanizmadır ("zincir" simgeli Pair düğmesi; termostatta P09). Cihazlar fabrikada eşleşmiş gelir; eşleşme 1 dakika içinde tamamlanmazsa moddan çıkar.
- `[belgeli]` Alıcı ünite LED'i "Uzaktan yazılım güncellemesi" durumunu gösterir: cihaz **buluttan OTA güncelleme** alıyor.
- `[belgeli]` Mobil uygulama: bulut hesabı gerektirir ("Cosa should be connected to a Wi-Fi network to be controlled from mobile phones"). Yerel kontrol, çevrimdışı mod veya API belgelenmemiş.
- `[belgeli]` Uygunluk beyanı RED, EN 300 328 (2.4 GHz) ve EN 300 220 (sub-GHz SRD) standartlarını sayıyor. EN 300 220'nin cihaza özgü ikinci bir sub-GHz radyoyu gösterip göstermediği **belirsiz**.
- `[varsayım]` Termostat ile alıcı arasındaki bağlantı, Wi-Fi'ya girmeyen 2.4 GHz özel bir radyo protokolü olabilir (çip ailesi ESP olduğu için ESP-NOW gibi bir şey olası). Doğrulanmadı.
- `[çıkarım]` Mimari bulut öncelikli: cihaz buluta bağlanıyor, uygulama da buluta bağlanıyor; açık yerel TCP portu olmaması bununla uyumlu.


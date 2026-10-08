# cosa-local

Cosa akıllı termostat (v5) için **bulutsuz, yerel ağda çalışan** Home Assistant entegrasyonu girişimi.

> **Durum: araştırma aşaması, henüz çalışan bir entegrasyon yok.**
> Cihazın yerel bir protokol sunup sunmadığı kanıtlanmadı. Bu depo şu an keşif araçlarını, gizlilik ilkelerini ve yol haritasını içerir. Yerel yol bulunamazsa bunu açıkça yazacağız; bulut tabanlı bir "yerel" taklit sunmayacağız.

*English: an early-stage effort to build a cloud-free, LAN-only Home Assistant integration for the Cosa smart thermostat (v5). No working integration yet; local-protocol discovery comes first.*

## Hedefler

- Cihaz internete çıkmadan Home Assistant ile çalışmak (`iot_class: local_polling` veya `local_push`).
- Bulut hesabı, parola veya belirteç gerektirmemek ve saklamamak.
- Ham cihaz verisini günlüğe yazmamak.
- Bağımlılıkları minimumda tutmak, CI aksiyonlarını commit SHA'sına sabitlemek.

Ayrıntı: [SECURITY.md](SECURITY.md).

## Yol haritası

1. [ ] Cihazın yerel ağdaki davranışını belirle ([docs/protocol-discovery.md](docs/protocol-discovery.md)).
2. [ ] Yerel protokol varsa: bağımsız bir istemci kütüphanesi (HA'dan bağımsız, test edilebilir).
3. [ ] `custom_components/cosa_local`: yapılandırma akışı (yalnızca ana makine adresi), koordinatör, `climate` varlığı.
4. [ ] HACS uyumluluğu, `hassfest` ve birim testleri.

Yerel protokol yoksa 2–4. adımlar yapılmaz; sonuç belgelenir.

## Kapsam

Hedef donanım: Cosa v5 sıcaklık/oda termostatı ve "Wireless Heater Control Unit v5" alıcı ünitesi. Cihazın hangi parçasının Wi-Fi'ya bağlandığı ve iki parça arasındaki radyo bağlantısının türü henüz doğrulanmadı.

## Kaynaklar ve teşekkür

Bulut tabanlı [aykutvr/smartcosa-home-assistant-integration](https://github.com/aykutvr/smartcosa-home-assistant-integration) projesi, Cosa cihazlarının Home Assistant ile kullanılabileceğini gösterdiği ve bu projeye ilham verdiği için anılır.

- Lisansı **MIT**'dir (telif satırı şablon halinde `[Your Name]` bırakılmıştır).
- Bu depo onun **kodunu içermez**. Mimari bulut API'sinden bağımsız ve baştan yazılmıştır; yalnızca "cihaz hangi bilgileri sunuyor" konusunda genel fikir edinilmiştir.
- Bu proje Cosa'nın / Nuvia Enerji Teknolojileri'nin resmî bir ürünü değildir ve onlarla bağlantılı değildir. "Cosa" adı ilgili sahibine aittir.

## Lisans

[MIT](LICENSE) © 2026 trkenankement

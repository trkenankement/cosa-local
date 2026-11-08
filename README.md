# cosa-local

Cosa akıllı termostat için Home Assistant çalışmaları: **Cosa Cloud** bulut entegrasyonu ve ayrı yerel protokol araştırması.

> `custom_components/cosa_cloud` internet üzerinden Cosa/Nuvia hizmetini kullanır. **Yerel veya bulutsuz değildir.** Yerel protokol araştırmasında henüz çalışan bir kontrol yolu bulunmadı.

## Cosa Cloud

Kendi hesabımızda bakımı yapılan `cosa_cloud` entegrasyonu; Home Assistant **2026.11.0 veya üzeri** için hazırlanmıştır. İlk sürümün otomatik testleri sentetik veriler kullanır; gerçek cihaz doğrulaması ayrıca yapılır.

- Sıcaklık, nem, bağlantı ve gerçek kombi çalışma bilgisi.
- Hedef sıcaklık, Evde/Uyku/Dışarı/Manuel/Otomatik/Haftalık program seçimi.
- 60 saniyede bir tek cihaz sorgusu; kurulum ve sorgulama ısıtma ayarlarını değiştirmez.
- Sıcaklık değiştirirken Evde/Uyku/Dışarı değerleri cihazdan yeniden okunur ve korunur; yeni değer Manuel profile uygulanır. Eksik profil verisiyle yazma yapılmaz.
- Kapalı komutu Cosa'nın **donma koruması** profilidir; elektriksel izolasyon anlamına gelmez.
- Başarısız yazmalar otomatik tekrarlanmaz. Durum buluttan yeniden okunur; komut başarılı görünmesi için tahmini değer üretilmez.
- Hesap bilgileri HA yapılandırmasında saklanır; bu deponun veya GitHub'ın parolaya ihtiyacı yoktur. HAM yanıtlar ve kimlik bilgileri günlüğe yazılmaz.

Kurulum: `custom_components/cosa_cloud` klasörünü HA `config/custom_components/` altına koy, HA'yı yeniden başlat, **Ayarlar → Cihazlar ve hizmetler → Entegrasyon ekle → Cosa Cloud** ekranından hesabını bağla. Geri almak için entegrasyonu kaldırıp bileşen klasörünü yedek konuma taşı ve HA'yı yeniden başlat.

Bu sürüm için Nuvia'nın HTTPS API alanları topluluk projesi [ahamitd/cosa-homeassistant](https://github.com/ahamitd/cosa-homeassistant) incelenerek öğrenildi. İstemci, yapılandırma akışı ve varlıklar bu depo için yeniden yazıldı. Cosa/Nuvia ile resmî bağlantımız yoktur.

Testler:

```sh
python -m pip install homeassistant==2026.11.0
python -m unittest discover -s tests -v
```

## Yerel protokol araştırması

*The local-protocol research is still experimental. The separately named Cosa Cloud integration requires internet access and a Cosa account.*

### Yerel araştırmanın hedefleri

- Cihaz internete çıkmadan Home Assistant ile çalışmak (`iot_class: local_polling` veya `local_push`).
- Bulut hesabı, parola veya belirteç gerektirmemek ve saklamamak.
- Ham cihaz verisini günlüğe yazmamak.
- Bağımlılıkları minimumda tutmak, CI aksiyonlarını commit SHA'sına sabitlemek.

Ayrıntı: [SECURITY.md](SECURITY.md).

## Keşif araçları ve kontroller

DNS aracı varsayılan olarak en fazla 32 sorguyu eşzamanlı işler ve 128 sorguyu kuyrukta tutar. `--workers` ile çalışan sayısı, `--queue-size` ile kuyruk sınırı değiştirilebilir. İkisi de doluysa yeni paket düşürülür; istemcinin yeniden denemesi beklenir. `--client` yalnız günlük filtresidir; diğer istemcilerin sorguları da bu ortak sınıra tabidir.

Port taramasında `--concurrency` en az 1, `--timeout` sonlu ve sıfırdan büyük olmalıdır. Geçersiz değerler bağlantı açılmadan reddedilir.

`tools/udp_discovery.py`, tek bir RFC1918 IPv4 cihazına CoAP kaynak keşfi ve mDNS servis keşfi için birer **salt okunur unicast** UDP paketi gönderir. Isıtma komutu, bulut bağlantısı, multicast, yeniden deneme veya ham yanıt kaydı yoktur. Her sorgu en fazla 5 saniye ve 8 yanıtla sınırlıdır; varsayılan süre 2 saniyedir. Adres komut satırından verilir, çıktıya yazılmaz:

```sh
python -I tools/udp_discovery.py <cihaz-ip-adresi>
```

Yanıt alınmaması yerel protokol olmadığını kanıtlamaz. Araç genel bir UDP port tarayıcısı değildir; yalnızca 5683 ve 5353 portlarını sorgular.

Cihaza trafik göndermeyen birim testleri:

```sh
python -m unittest discover -s tests -v
```

## Yol haritası

1. [ ] Cihazın yerel ağdaki davranışını belirle ([docs/protocol-discovery.md](docs/protocol-discovery.md)).
2. [ ] Yerel protokol varsa: bağımsız bir istemci kütüphanesi (HA'dan bağımsız, test edilebilir).
3. [ ] `custom_components/cosa_local`: yapılandırma akışı (yalnızca ana makine adresi), koordinatör, `climate` varlığı.
4. [ ] HACS uyumluluğu, `hassfest` ve birim testleri.

Yerel protokol yoksa 2–4. adımlar yapılmaz; sonuç belgelenir.

## Kapsam

Hedef donanım: Cosa v5 oda termostatı (`C5CTU…`) ve "Wireless Heater Control Unit v5" alıcı ünitesi (`C5KKU…`). Üretici belgelerine göre iki cihaz da 2.4 GHz Wi-Fi ile buluta bağlanabilir ve birbirleriyle ayrı bir 2.4 GHz bağlantıyla eşleşir; hangisinin Wi-Fi'da olduğu kuruluma bağlıdır. Ayrıntılar: [docs/protocol-discovery.md](docs/protocol-discovery.md).

## Kaynaklar ve teşekkür

Bulut tabanlı [aykutvr/smartcosa-home-assistant-integration](https://github.com/aykutvr/smartcosa-home-assistant-integration) projesi, Cosa cihazlarının Home Assistant ile kullanılabileceğini gösterdiği ve bu projeye ilham verdiği için anılır.

- Lisansı **MIT**'dir (telif satırı şablon halinde `[Your Name]` bırakılmıştır).
- Bu depo onun **kodunu içermez**. Mimari bulut API'sinden bağımsız ve baştan yazılmıştır; yalnızca "cihaz hangi bilgileri sunuyor" konusunda genel fikir edinilmiştir.
- Bu proje Cosa'nın / Nuvia Enerji Teknolojileri'nin resmî bir ürünü değildir ve onlarla bağlantılı değildir. "Cosa" adı ilgili sahibine aittir.

## Lisans

[MIT](LICENSE) © 2026 trkenankement

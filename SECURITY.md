# Güvenlik ve Gizlilik İlkeleri

Bu proje "gizlilik önce" tasarlanmıştır. Aşağıdakiler hedef değil, **kabul koşuludur**; bir değişiklik bunları bozuyorsa birleştirilmez.

1. **Dışarıya çıkış yok.** Entegrasyon yalnızca kullanıcının yapılandırdığı yerel ağ adresiyle konuşur. Kodda sabit bir bulut adresi, telemetri, analitik veya güncelleme sorgusu bulunmaz.
2. **Hesap bilgisi yok.** Yerel kontrol bulut hesabı gerektirmez; e-posta, parola veya bulut belirteci istenmez ve saklanmaz.
3. **Günlükte ham veri yok.** Cihaz yanıtlarının tamamı `DEBUG` düzeyinde bile günlüğe yazılmaz. Gerekirse yalnızca yapı bilgisi (alan adları, uzunluk) yazılır; sıcaklık, nem, mod ve MAC/IP gibi değerler maskelenir.
4. **En az yetki.** CI iş akışları açık `permissions:` bildirir (varsayılan `contents: read`); üçüncü taraf aksiyonlar tam commit SHA'sına sabitlenir.
5. **Depo temiz kalır.** Trafik kayıtları, tarama çıktıları, MAC/IP/seri numarası ve belirteçler depoya girmez (`.gitignore` bunları engeller).

## Güvenlik açığı bildirme

Bir zafiyet bulursan lütfen herkese açık issue yerine GitHub'ın **Private vulnerability reporting** özelliğini (Security sekmesi → Report a vulnerability) kullan.

## Donanım uyarısı

Cosa alıcı ünitesi 230V şebekeye bağlıdır ve kombi/kat ısıtmasını sürer. Bu proje cihazı **açmayı veya firmware'ini değiştirmeyi önermez**. Bunu yaparsan garantiyi, güvenliği ve olası sigorta/servis haklarını kendi sorumluluğunda riske atarsın.

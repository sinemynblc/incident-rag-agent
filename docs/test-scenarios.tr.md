# Test Senaryoları — Yeni Set (Önceki Setlerden Farklı Servisler)

`rca_dataset_1.csv` (100 kayıt) ile birebir doğrulanmıştır. Önceki test
dosyalarında kullanılmayan servisler (fraud, cart, wishlist, notification,
cdn, streaming, order-service, promotion, pricing, sms, media, catalog,
integration, serverless, reporting, logging, admin, analytics, cms,
infrastructure) tercih edildi — çeşitlilik için.

Kategoriler: filtreli sorular, doğrudan incident soruları, "what did I ask"
tarzı kronolojik hafıza, incident + geçmişe atıf çiftleri, dolaylı sorular.

---

## 1) Filtre kullanan sorular

**1.1**
```json
{"question": "why was checkout blocked by the fraud filter?", "service": "fraud", "severity": "medium"}
```
**Beklenen:** **INC-1070** – Checkout blocked by fraud filter. Kök neden: yeni bir fraud kuralı, eşik değişikliğinden sonra çok agresif kalmış. Çözüm: eşik ayarlandı, sert bloklama yerine manuel inceleme kuyruğu eklendi.

**1.2**
```json
{"question": "why do cart items disappear after a page refresh?", "service": "cart", "severity": "high"}
```
**Beklenen:** **INC-1006** – Cart items disappear after refresh. Kök neden: yeni node eklenince session affinity kaybolmuş, sepet sadece local memory'de tutuluyormuş. Çözüm: sepet durumu Redis'e taşındı.

**1.3**
```json
{"question": "why were notification emails not delivered?", "service": "notification", "severity": "high"}
```
**Beklenen:** **INC-1005** – Notification emails not delivered. Kök neden: e-posta sağlayıcı API anahtarının süresi dolmuş, rotate edilmemiş. Çözüm: anahtar yenilendi, 14 gün önceden süre dolum uyarısı eklendi.

**1.4**
```json
{"question": "why is Kafka consumer lag growing?", "service": "streaming", "severity": "high"}
```
**Beklenen:** **INC-1049** – Kafka consumer lag growing. Kök neden: kötü partition key seçimi yüzünden tek bir partition aşırı yüklenmiş. Çözüm: daha iyi bir key ile yeniden partition'landı, consumer paralelliği artırıldı.

**1.5**
```json
{"question": "why do orders get stuck in pending status?", "service": "order-service", "severity": "high"}
```
**Beklenen:** **INC-1007** – Order status stuck in pending. Kök neden: state machine worker'ı, işlenmeyen bir null alan yüzünden çökmüş, tüketmeyi durdurmuş. Çözüm: null kontrolleri eklendi, worker'ı otomatik yeniden başlatan bir supervisor eklendi.

**1.6**
```json
{"question": "why did DNS resolution fail intermittently?", "service": "infrastructure", "severity": "critical"}
```
**Beklenen:** **INC-1043** – DNS resolution failures. Kök neden: DNS cache TTL'i çok yüksekmiş, kaldırılmış bir host'a işaret ediyormuş. Çözüm: TTL'ler düşürüldü, sağlık kontrollü DNS kayıtları eklendi.

---

## 2) Doğrudan incident soruları (filtresiz)

**2.1** Why did coupon codes stop applying at checkout?
**Beklenen:** **INC-1033** – Coupon codes not applying. Kök neden: promosyon kuralı değişikliğinden sonra cache geçersiz kılınmamış. Çözüm: promosyon kuralı güncellemesinde cache invalidation eklendi.

**2.2** Why are users seeing stale prices that don't match checkout?
**Beklenen:** **INC-1066** – Stale pricing shown to users. Kök neden: fiyat kampanyası sonrası pricing cache TTL'i çok uzun kalmış. Çözüm: TTL düşürüldü, event tabanlı cache invalidation eklendi.

**2.3** Why are OTP codes arriving late?
**Beklenen:** **INC-1011** – SMS one-time codes delayed. Kök neden: retry fırtınası yüzünden SMS sağlayıcısı trafiği kısıtlamış (throttle). Çözüm: exponential backoff ve kullanıcı başına gönderim limiti eklendi.

**2.4** Why is the image processing service crashing repeatedly?
**Beklenen:** **INC-1025** – Memory leak in image service. Kök neden: decode edilen görsel buffer'ları, cache'te tutulan bir referans yüzünden asla serbest bırakılmamış. Çözüm: referans tutulması düzeltildi, sınırlı boyutlu LRU cache eklendi.

**2.5** Why do product detail pages load so slowly during peak hours?
**Beklenen:** **INC-1008** – High latency on product detail pages. Kök neden: N+1 sorgu deseni, her ürün için döngü içinde ayrı sorgu atıyormuş. Çözüm: attribute çekme işlemi tek sorguda toplandı, index eklendi.

**2.6** Why did webhook events get lost occasionally?
**Beklenen:** **INC-1018** – Webhook events lost. Kök neden: webhook consumer, işleme tamamlanmadan mesajı onaylıyormuş (ack). Çözüm: onaylama, işleme başarıyla bittikten sonraya taşındı, retry eklendi.

---

## 3) "What did I ask" tarzı — kronolojik hafıza

**Not:** Önce bir soru sor (ör. 2.1), hemen ardından aşağıdakilerden birini dene.

**3.1** What did I just ask?
**3.2** What was my last question?
**3.3** Can you remind me what I just asked you?
**3.4** What was the previous incident we discussed?

**Beklenen (hepsi için):** Az önceki soruyu/cevabı birebir doğru hatırlamalı, `Kaynak: Geçmiş konuşma` demeli — kendi güncel mesajını yansıtmamalı.

---

## 4) Incident + geçmişe atıf çiftleri

Bu kategori, önce bir incident sorusu sorup, sonra ona **atıfla** başka bir soru sormayı test ediyor — "bahsettiğim o şey" gibi referanslarla.

**4.1**
1. Sor: *Why was checkout blocked by the fraud filter?*
2. Sonra sor: *What was the resolution for the issue I just asked about?*
**Beklenen (2. soru):** Manuel inceleme kuyruğu eklenmesi çözümünü (INC-1070) tekrar, "Geçmiş konuşma" kaynağıyla vermeli.

**4.2**
1. Sor: *Why do cart items disappear after a page refresh?*
2. Sonra sor: *Have we discussed anything about the shopping cart before?*
**Beklenen:** INC-1006'yı (session affinity, Redis'e taşıma) özetleyerek hatırlamalı.

**4.3**
1. Sor: *Why is Kafka consumer lag growing?*
2. Sonra sor: *What did we conclude about the streaming issue earlier?*
**Beklenen:** INC-1049'u (partition key, repartitioning çözümü) hatırlamalı.

**4.4**
1. Sor: *Why did DNS resolution fail intermittently?*
2. Sonra sor: *Going back to the infrastructure problem we talked about — what caused it?*
**Beklenen:** INC-1043'ü (DNS TTL, decommissioned host) hatırlamalı.

**4.5**
1. Sor: *Why are OTP codes arriving late?*
2. Sor: *Why did coupon codes stop applying at checkout?*
3. Sonra sor: *Between the SMS issue and the coupon issue, which one did we discuss first?*
**Beklenen:** Sıralamayı doğru vermeli — SMS (INC-1011) önce, coupon (INC-1033) sonra sorulmuştu; bu, kronolojik hafızanın sıra bilgisini de koruduğunun testi.

---

## 5) Dolaylı sorular (anahtar kelime değil, anlam eşleşmesi)

**5.1** Editors publish a new homepage banner but customers still see the old one.
**Beklenen:** **INC-1051** – Homepage banner not updating. Kök neden: CDN edge cache, sayfayı gereğinden uzun tutmuş. Çözüm: CMS sayfaları için cache TTL'i düşürüldü, yayınlamada purge eklendi.

**5.2** Some JavaScript files on the site are failing to run properly.
**Beklenen:** **INC-1071** – CDN serving wrong content type. Kök neden: origin sunucu yanlış Content-Type döndürmüş, CDN bunu cache'lemiş.

**5.3** Bulk product uploads keep failing when the file has non-English characters.
**Beklenen:** **INC-1063** – Failed CSV import for catalog. Kök neden: parser ASCII varsayıyormuş, UTF-8 içerikte takılmış.

**5.4** Our analytics dashboard is showing zero for everything today.
**Beklenen:** **INC-1019** – Analytics dashboard shows zeros. Kök neden: upstream şema değişikliğinden sonra ETL job'u sessizce başarısız olmuş.

**5.5** The service couldn't handle extra traffic and started dropping requests during a busy period.
**Beklenen:** **INC-1040** – Failed to scale during peak. Kök neden: autoscaling, güncel olmayan bir maksimum replica limitiyle sınırlanmış.

**5.6** Large report downloads are failing with a timeout error.
**Beklenen:** **INC-1046** – Report export times out. Kök neden: export işlemi, istek yaşam döngüsü içinde senkron çalışıyormuş. Çözüm: asenkron job'a taşındı.

---

## Kullanım notu

- **1, 2, 5** bağımsız kategoriler — herhangi bir sırada denenebilir.
- **3**, hemen öncesinde bir soru sorulmuşsa anlamlıdır.
- **4**, her madde kendi içinde sıralı bir mini-senaryo; maddeler arasında sıra önemli değil ama madde içindeki adımlar sırayla izlenmeli.
- Testleri aynı sohbette art arda yaparsan hafıza birikir; farklı sohbetlerde (yeni session) denersen izolasyonu da test etmiş olursun.
# Stage 1 Design

Bu dokuman ilk asamanin teknik temelini tanimlar. Hedef, eski uygulamadaki
lokasyon, geocoding ve matris akisini korurken yeni surumde solver secimini ve
filo modelini genisletmektir.

## 1. Uygulama kapsami

Yeni surum asagidaki kullanici akislarini destekleyecek:

1. Lokasyon kaydetme ve duzenleme
2. Adresleri geocode etme
3. OSRM uzerinden mesafe ve zaman matrisi uretme
4. Musteri taleplerini girme
5. Filo tanimlama
6. Uygun solver ile problemi calistirma
7. Sonuclari maliyet, sure, arac ve rota detaylari ile goruntuleme

## 2. Problem tipleri

### Homojen filo

Tum araclar asagidaki alanlarda ayniysa problem homojen kabul edilir:

- kapasite
- sabit maliyet
- km maliyeti
- hiz

Bu durumda kullanici iki secenek gorebilir:

- `NSGA-II (multiobjective)`
- `Bloodhound (single objective)`

### Heterojen filo

Arac parametrelerinden en az biri farkliysa problem heterojen kabul edilir.

Bu durumda:

- solver secimi `Bloodhound` olarak sabitlenir
- `NSGA-II` secenegi gizlenir veya pasiflestirilir

## 3. Solver ic temsilleri korunacak

Ortak girdi semasi kurmak, solver'larin ic temsillerini ortaklastirmak
anlamina gelmez.

### NSGA-II

- ic temsil: `giant tour`
- rota uretimi: `DP split`
- amaclar:
  - toplam maliyet
  - maksimum rota suresi
  - ortalama rota suresi

### Bloodhound

- ic temsil: `route matrix`
- arac atamasi: `vehicle_ids`
- amac: toplam maliyet
- komsuluk yapilari:
  - intra-route 2-opt
  - inter-route relocate
  - inter-route swap
  - intra-route reinsert
  - vehicle reassignment
  - alpha-guided rebuild
  - ruin-and-rebuild

## 4. Ortak problem semasi

UI ve veri katmani solver'a asagidaki ortak problem modeli ile gidecek:

- `locations`
- `distance_matrix`
- `time_matrix`
- `demands`
- `fleet`
- `time_windows`
- `service_times`
- `solver_choice`
- `solver_params`

Bu model solver adapter katmaninda ilgili algoritmanin bekledigi bicime
donusturulecek.

## 5. Ortak sonuc semasi

UI solver ciktilarini tek bir formatta okuyacak:

- `solver_key`
- `problem_type`
- `is_multiobjective`
- `objective_names`
- `solutions`
- `metadata`
- `warnings`

Her cozumde:

- objective degerleri
- toplam maliyet
- rota listesi
- rota sureleri
- rota mesafeleri
- rota maliyetleri
- kullanilan araclar

yer alacak.

## 6. Bloodhound icin OSRM entegrasyonu

Arastirma kodundaki mevcut Bloodhound yapisi `coords` uzerinden kendi
oklidyen mesafe matrisini uretir ve zamani `distance / speed` ile hesaplar.
Bu uygulamada bu davranis test amacli kalmali; canli kullanimda disaridan gelen
OSRM matrisleri esas alinmali.

### Gerekli degisiklik

`HCVRPProblem` su alanlari desteklemeli:

- `coords`
- `distance_matrix` opsiyonel
- `time_matrix` opsiyonel

### Beklenen davranis

- `distance_matrix` verilirse `dist` olarak dogrudan bu kullanilir
- verilmezse mevcut oklidyen fallback korunur
- `time_matrix` verilirse `travel_time()` bunu kullanir
- verilmezse mevcut `dist / speed` fallback'i korunur

### Sonuc

Bu degisiklik Bloodhound'un arama mantigini bozmaz; sadece maliyet ve zaman
degerlendirmesinde kullanilan kaynak matrisi degistirir.

## 7. Stage 2 icin acik isler

- Eski lokasyon kaydetme akisindaki sorunlari duzeltmek
- UI icin ilerleme gostergesi ve "calisiyor" durumu eklemek
- Solver adapter implementasyonlarini yazmak
- Bloodhound kodunu dis matris destekleyecek sekilde adapte etmek
- Sonuc ekraninda fixed cost / variable cost ayristirmasi yapmak

## 8. Buyuk homojen problem uyarisi

`NSGA-II` seciliyse ve musteri boyutu belirlenen esigin ustundeyse kullaniciya
uyari verilecek:

`Bu problem boyutu NSGA-II icin onerilen araligin ustunde olabilir.`

Bu uyari bloke edici olmayacak; karar kullanicida kalacak.

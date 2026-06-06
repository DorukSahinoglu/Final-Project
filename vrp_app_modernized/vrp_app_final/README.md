# VRP App Final

Bu klasor yeni surumun temelini tutar. Ilk asamada uygulama arayuzu degil,
ortak veri modeli, solver sozlesmeleri ve Bloodhound entegrasyon tasarimi
netlestirilir.

## Stage 1 kapsam

- Ortak problem semasi
- Ortak sonuc semasi
- Solver adapter sozlesmesi
- Homojen / heterojen ayrim kurali
- Bloodhound icin OSRM mesafe ve zaman matrisi entegrasyon notlari

## Temel kararlar

- `NSGA-II` ic temsil olarak `giant tour + DP split` yapisini korur.
- `Bloodhound` ic temsil olarak `route matrix + vehicle assignment` yapisini korur.
- UI ve veri katmani solver'lardan ortak bir problem modeli uzerinden yararlanir.
- Heterojen problemde solver secimi otomatik olarak `Bloodhound` olur.
- Homojen problemde kullanici `NSGA-II` veya `Bloodhound` secebilir.

## Sonraki asama

Bir sonraki adimda bu semalar kullanilarak:

- veri giris ekranlari,
- solver adapter implementasyonlari,
- ve arka planda calisma / progress gostergesi

olusturulacak.

## Calistirma

Klasor icinden:

`python -m vrp_app_final`

veya Windows'ta:

`run_app.bat`

## EXE alma

`pyinstaller` kuruluysa:

`build.bat`

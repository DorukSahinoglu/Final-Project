# VRP NSGA-II Optimizer

## Dosyalar
- main.py          → Ana uygulama (GUI)
- vrp_algorithm.py → NSGA-II algoritması
- default_data.py  → Varsayılan mesafe/zaman matrisleri
- build.bat        → .exe oluşturucu (Windows)

## .exe Oluşturma (Windows)

1. Python 3.8+ yüklü olsun (python.org)
2. build.bat dosyasına çift tıkla
3. dist/ klasöründe VRP_Optimizer.exe oluşur
4. Bu .exe dosyasını başka bilgisayara taşıyabilirsin
   (Python kurulu olmak zorunda değil)

## Direkt Python ile Çalıştırma
```
python main.py
```

## Uygulama Özellikleri
- Parametreler: Popülasyon, nesil sayısı, seed vb.
- Matris Editörü: Mesafe/zaman matrislerini JSON ile düzenle
- Canlı Log: Her nesil sonucu anlık göster
- Sonuçlar: Pareto cephesi tablosu + rota detayları
- Dışa Aktarma: Sonuçları .txt veya .json olarak kaydet

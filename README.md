# Native Researcher

`Native Researcher`, `Researcher_2` tabanından ayrılmış daha sade bir araştırma uygulamasıdır.

Bu sürümün odağı:

- PubMed üzerinden hızlı makale arama
- Ortadaki sonuç tablosu üstünden makale tarama
- `Searcher AI` ile doğrudan arama odaklı, hafif bir AI akışı

Şimdilik özellikle ekli olanlar:

- search-first arayüz
- search-only native assistant
- makale tablo görünümü
- detay popup ve abstract inceleme

Henüz özellikle sade tutuldu:

- PDF/full-text pipeline
- batch analyzer entegrasyonu
- gerçek autonomous multi-step researcher zinciri

Çalıştırma:

```bash
./start.sh
```

Uygulama varsayılan olarak root path üzerinde açılır:

```text
http://127.0.0.1:8000/
```

Eski `Researcher_2` görünümü kopya proje içinde hâlâ erişilebilir:

```text
/researcher_2
```

Test:

```bash
pytest -q
```

# Native Researcher

`Native Researcher`, literatur tarama, makale eleme, PDF/XML indirme ve yerel/uzak LLM destekli araştırma akışları için geliştirilen yerel bir FastAPI uygulamasıdır.

Proje ilk başta sade bir PubMed arama arayüzü olarak ayrıldı; şu an kapsamı daha geniş:

- PubMed ve ek kaynaklar üzerinden makale arama
- Proje bazlı workspace ve araştırma geçmişi
- Makale tablo görünümü, filtreleme, seçim ve detay inceleme
- Searcher AI / Research Agent sohbet akışları
- Ollama ve llama.cpp tabanlı yerel model ayarları
- PDF/XML çözümleme, indirme ve metin çıkarma endpointleri
- Research plan execution ve aday makale eleme raporları

## Calistirma

```bash
./start.sh
```

Uygulama varsayılan olarak:

```text
http://127.0.0.1:8000/
```

Boş değilse `start.sh` otomatik olarak yakın bir port seçer. Farklı host/port için:

```bash
HOST=127.0.0.1 PORT=8010 ./start.sh
```

## Test

```bash
.venv/bin/python -m pytest -q
```

İlk kurulumdan sonra `start.sh` bağımlılıkları `.venv` içine kurar.

## Ayarlar

Uygulama çalışma zamanı ayarlarını varsayılan olarak `runtime/settings/` altında tutar. API anahtarları, arama kaynağı, PDF fallback seçenekleri, Ollama ve llama.cpp ayarları buradan veya ilgili environment variable'lar üzerinden okunur.

Yeni bilgisayarda başlangıç için [`.env.example`](.env.example) dosyasındaki değişkenler referans alınabilir. Yerel GGUF modellerini otomatik listelemek için `LOCAL_LLM_MODEL_ROOTS` veya `LLAMACPP_MODEL_ROOTS` değerini model klasörlerine ayarla. Uygulama artık repo sahibinin makinesine özel LLM path'lerine bağlı değildir; path verilmezse llama.cpp ayarları boş kalır ve UI üzerinden yapılandırılabilir.

## Mevcut Odak

Şu an en önemli teknik hedefler:

1. Research Agent akışlarını ölçülebilir, tekrar üretilebilir ve kalite odaklı hale getirmek.
2. PDF/XML full-text analizini ana research execution akışına güvenilir şekilde bağlamak.
3. Yerel makineye özel hard-coded path ve varsayımları taşınabilir config yapısına almak.
4. Büyük frontend/backend dosyalarını risk almadan modüler hale getirmek.
5. Her değişikliği küçük git branch/commit adımlarıyla, test ve benchmark çıktılarıyla ilerletmek.

Detaylı uzun vadeli plan için:

- [`docs/LONG_TERM_AGENT_PLAN.md`](docs/LONG_TERM_AGENT_PLAN.md)
- [`docs/RESEARCH_AGENT_NEXT_PLAN.md`](docs/RESEARCH_AGENT_NEXT_PLAN.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)

## Repo Notlari

- `runtime/`, `logs/`, `downloads/`, `workspace/` ve `output/` runtime verisidir ve git dışında tutulur.
- Eski/deneysel downloader parçaları `old/` altında durur.
- Benchmark ve geçmiş deneme çıktıları `scrape_test/`, `test_analysis/` ve `docs/` altında referans olarak tutulur.

# Long-Term Agent Plan

## Ana Vizyon

Native Researcher'ın uzun vadeli hedefi, yalnızca makale arayan bir arayüz değil; kullanıcının sorduğu bilimsel soruya en hızlı, en doğru ve en denetlenebilir cevabı getiren bir araştırma sistemi olmaktır.

Bu sistemin kalitesi üç şeye bağlı:

1. Doğru kaynakları bulmak.
2. Bulunan kaynakları hızlı ama güvenilir şekilde elemek.
3. Final cevabı abstract, PDF/XML full text ve açık kanıt tablosu ile doğrulamak.

Model ve prompt seçimi bu hedefe göre yapılmalı. "En zeki model" tek başına yeterli değil; ölçülen görevde en iyi sonuç veren model, prompt, tool contract ve execution akışı birlikte seçilmeli.

## Mevcut Durum

Güçlü taraflar:

- FastAPI backend ve statik frontend uçtan uca çalışıyor.
- PubMed/search, project workspace, assistant chat, local model ayarları ve research execution katmanları var.
- Research Agent için üç aşamalı planner fikri başlamış durumda: search strategy, screening criteria, extraction strategy.
- PDF/XML indirme ve `/pdf/extract` endpoint'i mevcut.
- Test altyapısı var ve mevcut suite temiz geçiyor.
- Eski benchmark ve PDF retrieval denemeleri repo içinde korunuyor.

Ana açıklıklar:

- Research plan hâlâ tam anlamıyla kalıcı, versiyonlu, tekrar çalıştırılabilir bir backend varlığı değil.
- Agent kalitesi için sistematik eval harness sınırlı; testler daha çok kodun kırılıp kırılmadığını ölçüyor.
- PDF extraction var ama ana research execution akışına otomatik, kanıt üreten bir stage olarak tam bağlanmamış.
- Screening bazı yerlerde yavaş; tek aday başına model çağrısı büyük araştırmalarda darboğaz.
- Query normalization ve database-specific arama kalitesi henüz sığ.
- Frontend ve bazı backend servisleri fazla büyük dosyalara dönüşmüş.
- Bazı LLM path/discovery varsayımları yerel makineye özel.

## Yol Haritasi

### Faz 0 - Versiyonlu Calisma Disiplini

Amaç: Büyük sistemi bozmadan, her değişikliği geri alınabilir küçük adımlarla ilerletmek.

Kurallar:

- Her iş için ayrı branch: `chore/readme-agent-plan`, `refactor/config-portability`, `agent/eval-harness-v1` gibi.
- Her branch küçük tutulur ve tek niyet taşır.
- Her commit öncesi en az `pytest -q` çalışır.
- Agent/PDF değişikliklerinde ilgili benchmark script'i veya eval case çıktısı dokümana eklenir.
- Riskli refactorlar önce "behavior preserving" yapılır; davranış değişikliği sonraki committe gelir.

Önerilen ilk repo işleri:

- `pyproject.toml` veya en azından `requirements-lock` stratejisi oluşturmak.
- Basit CI eklemek: test, import smoke, lint.
- `docs/CHANGELOG_AGENT.md` veya benzeri bir agent deney günlüğü tutmak.

### Faz 1 - Tasınabilir Config ve Hard-Coded Path Temizligi

Amaç: Projenin farklı bilgisayarda kod değiştirmeden ayağa kalkması.

Yapılacaklar:

- LLM model discovery root'larını sadece env/runtime settings üzerinden yönetmek.
- `/home/sina/...` gibi yerel varsayılanları koddan çıkarmak veya "optional local preset" dosyasına taşımak.
- `.env.example` eklemek.
- Runtime settings için tek bir açıklayıcı doküman yazmak.
- llama.cpp executable/model/library path discovery davranışını testlerle sabitlemek.

Başarı kriteri:

- Temiz bir makinede repo clone + `./start.sh` ile uygulama açılır.
- LLM path yoksa uygulama bozulmaz; UI bunu açık ve sakin biçimde gösterir.

### Faz 2 - Agent Eval Harness

Amaç: "Hangi model/prompt daha iyi?" sorusunu hissiyatla değil, tekrar üretilebilir ölçümle cevaplamak.

Eval case formatı:

- Kullanıcı sorusu
- Beklenen cevap türü
- Zorunlu kanıt tipleri
- Kabul edilebilir kaynaklar
- Altın cevap veya rubrik
- Başarı metrikleri

İlk metrikler:

- Doğru arama kapsamı
- Kritik makaleleri bulma oranı
- Yanlış pozitif aday oranı
- PDF/full-text kanıt bulma başarısı
- Final cevap doğruluğu
- Kaynak gösterme doğruluğu
- Latency ve model çağrı maliyeti

İlk eval setleri:

- 10 hızlı literatür sorusu
- 10 derin research agent sorusu
- 10 PDF/full-text extraction sorusu
- 5 negatif kontrol: cevap yok veya literatür belirsiz

Başarı kriteri:

- Aynı eval seti Gemini, Ollama ve llama.cpp modelleri üzerinde çalıştırılabilir.
- Prompt/model değişikliği öncesi ve sonrası kalite farkı raporlanır.

### Faz 3 - Research Plan'i Backend'de Birinci Sinif Varlik Yapmak

Amaç: Agent planları kaybolmayan, versiyonlanan, tekrar çalıştırılabilir araştırma nesneleri olsun.

Yapılacaklar:

- `research_plan` için project state içinde net schema.
- Plan versiyonları: created, edited, executed, superseded.
- Plan edit/revision semantiği.
- Execution run ile kullanılan plan snapshot'ını ilişkilendirme.
- UI'da plan diff ve run geçmişi.

Başarı kriteri:

- Backend restart/cache expiry sonrası plan takip akışı bozulmaz.
- Aynı plan aynı inputlarla tekrar koşturulabilir.

### Faz 4 - Uc Asamali Agent Mimarisini Sabitlemek

Amaç: Planner'ın tek büyük prompt yerine uzmanlaşmış aşamalarla güvenilir plan üretmesi.

Aşamalar:

1. Search Strategy Agent
   - kaynaklar, yıl aralıkları, branch'ler, query intent ve genişletme politikası
2. Screening Criteria Agent
   - inclusion/exclusion kriterleri, required alanlar, skor rubriği
3. Full-Text Extraction Agent
   - PDF'den aranacak alanlar, evidence formatı, belirsizlik bayrakları

Backend sorumluluğu:

- LLM'in raw query'sine kör güvenmemek.
- Query'leri kaynak adapter'larına göre normalize etmek.
- Kriter skorlarını deterministik hesaplamak.
- Tool call yoksa veya JSON bozuksa görünür hata ve retry üretmek.

Başarı kriteri:

- Planner output'u strict schema ile valide edilir.
- Her aşama ayrı eval edilebilir.
- Plan neden o aramaları seçtiğini raporlar.

### Faz 5 - Screening'i Hizlandirmak ve Guvenilir Kilmak

Amaç: Büyük aday havuzlarını hızlıca daraltmak ama kritik eski/seminal makaleleri kaçırmamak.

Yapılacaklar:

- Token-aware batch screening.
- Tek aday başına çağrı yerine chunk bazlı structured output.
- Required criteria enforcement backendde kalsın.
- Recency-only prefilter yerine çeşitlilik stratejisi: yıl, citation, source, query branch.
- Partial source failure'ları raporda belirgin göstermek.

Başarı kriteri:

- 200-500 adaylık araştırmalarda kabul edilebilir sürede top aday çıkar.
- Eval setinde kritik makale kaçırma oranı düşer.

### Faz 6 - PDF/XML Full-Text Akisini Ana Pipeline'a Baglamak

Amaç: Final cevap, sadece abstract'a değil indirilen metin kanıtına dayanabilsin.

Yapılacaklar:

- Research execution sonrası kullanıcı onaylı PDF/XML retrieval stage.
- PDF/XML extraction sorularını planın parçası yapmak.
- Full text chunking ve evidence table üretmek.
- Exact quote, section, page veya XML konumu saklamak.
- "Kanıt bulunamadı" sonucunu da birinci sınıf çıktı yapmak.

Başarı kriteri:

- Final rapor her iddia için evidence row gösterebilir.
- PDF yoksa sistem bunu saklamaz; açıkça "full text unavailable" der.
- PDF extraction eval setinde doğruluk ölçülür.

### Faz 7 - Model/Prompt Optimizasyon Dongusu

Amaç: En hızlı doğru araştırma ajanını deneysel olarak bulmak.

Döngü:

1. Eval setini sabitle.
2. Baseline model/prompt çalıştır.
3. Hata sınıflarını çıkar: yanlış query, eksik kriter, PDF kanıt kaçırma, hallucinated conclusion.
4. Tek değişken değiştir: prompt, model, tool schema veya retrieval strategy.
5. Aynı evalı tekrar çalıştır.
6. Kazananı kaydet, kaybedeni gerekçesiyle arşivle.

Takip edilecek kayıt:

- model
- prompt version
- tool schema version
- runtime settings
- eval set version
- skorlar
- örnek başarısızlıklar

Başarı kriteri:

- "Bu model daha iyi" kararı raporla savunulabilir.
- Latency/kalite tradeoff'u görünür olur.

### Faz 8 - Moduler Kod Dizayni

Amaç: Mevcut çalışan sistemi bozmadan bakım maliyetini düşürmek.

Frontend parçalama sırası:

1. API client fonksiyonları.
2. State persistence/project state.
3. Assistant/session yönetimi.
4. Settings dialog/model yönetimi.
5. Research report rendering.
6. Table/filter rendering.

Backend parçalama sırası:

1. Config discovery ve runtime settings servisleri.
2. Research plan schema/execution/run repository.
3. Screening service ve eval runner ayrımı.
4. PDF retrieval ve extraction orchestration ayrımı.
5. Agent prompt/tool contract versiyonlama.

Refactor kuralı:

- Önce dosya böl, public davranışı değiştirme.
- Test ve smoke geçsin.
- Sonra davranış iyileştirmesini ayrı branchte yap.

## Ilk 6 Haftalik Uygulama Plani

### Hafta 1

- README ve uzun vadeli planı güncelle.
- Hard-coded LLM path envanteri çıkar.
- `.env.example` ve config dokümanı ekle.

### Hafta 2

- LLM discovery/config portability refactor.
- İlgili unit testleri ekle.
- Temiz makine senaryosu için smoke checklist.

### Hafta 3

- Agent eval case formatını ve runner iskeletini ekle.
- İlk 10 eval case'i oluştur.
- Mevcut Research Agent baseline raporunu üret.

### Hafta 4

- Research plan persistence schema.
- Plan snapshot ve run ilişkilendirme.
- Restart sonrası plan continuity testi.

### Hafta 5

- Screening batch/chunk contract'ını netleştir.
- Tek aday çağrı darboğazını azaltacak ilk batch implementation.
- Eval ile kalite/hız karşılaştırması.

### Hafta 6

- PDF extraction stage'i research execution raporuna bağlayan ilk kontrollü akış.
- User approval, evidence table ve failure reporting.
- PDF extraction eval setiyle baseline.

## Oncelik Sirasi

1. Config portability ve hard-coded path temizliği.
2. Agent eval harness.
3. Research plan persistence.
4. Üç aşamalı planner'ın schema ve eval ile sabitlenmesi.
5. Batch screening hız/kalite iyileştirmesi.
6. PDF/XML full-text stage entegrasyonu.
7. Model/prompt optimizasyon döngüsü.
8. Büyük dosyaların modüler refactoru.

Bu sıranın mantığı: önce proje taşınabilir ve ölçülebilir hale gelsin; sonra agent davranışını iyileştirelim. Ölçüm olmadan prompt/model değiştirmek kısa vadede iyi hissettirir ama uzun vadede sistemi nereye götürdüğümüzü belirsizleştirir.

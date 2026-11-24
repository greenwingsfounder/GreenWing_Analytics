# Model Kaynak Matrisi (Provenance)

Her model bileşeni: ne, nerede, formül, kaynak, doğruluk, belirsizlik.

**Toplam 16 model** — doğru: 9, notlu doğru: 1, çekinceli: 4, varsayım: 2

| # | Model | Doğruluk | Kaynak | Belirsizlik |
|---|-------|----------|--------|-------------|
| 1 | `isa_atmosphere` | ✅ doğru | ICAO Doc 7488 — Manual of the ICAO Standard Atmosphere (1993)… | Gerçek atmosfer ISA'dan ±15 °C sapabilir; delta_isa parametr… |
| 2 | `pressure_ratio` | ✅ doğru | ICAO Doc 7488; US Standard Atmosphere 1976… | Yok — deterministik standart.… |
| 3 | `drag_polar` | ✅ doğru | OpenAP v3 (TU Delft / Junzi Sun) dragpolar veri dosyaları; orijinal: S… | CD0 ±5 %, K ±3 %. π·AR·e yerine doğrudan K kullanıldığı için… |
| 4 | `compressibility` | ✅ doğru | Raymer, "Aircraft Design: A Conceptual Approach" 6th ed. §12.5 (Korn/L… | M_dd ±0.01; ΔCD bu bölgede 4. kuvvetle büyüdüğü için belirsi… |
| 5 | `lift_coefficient` | ✅ doğru | Anderson, "Fundamentals of Aerodynamics" 6th ed. Ch. 1 — tanım denklem… | Yok — tanım. S ve ρ belirsizliği polar'a girer.… |
| 6 | `cruise_fuel_flow` | ✅ doğru | ICAO Engine Emissions Databank (ICAO EDB) yakıt modeli; OpenAP v3 fuel… | Katsayılar ICAO EDB'den; LTO dışı cruise noktasında türetilm… |
| 7 | `phase_fuel` | ⚠ çekinceli | tools/calibrate_phase_thrust.py — B738/B77W/A380 yayımlanmış faz yakıt… | Faz yakıtı ±%25 (1σ); toplam görev yakıtına etkisi ±%2 (fazl… |
| 8 | `sfc` | ✅ notlu | BADA 3.12 (EUROCONTROL) fonksiyonel biçim; sayısal değerler uçak verit… | Yedek yol için ±%8; SAF için CORSIA düzeltmesi ±%3.… |
| 9 | `wind` | ⚠ notlu | NOAA/NCEP GFS klimatolojisi (Kuzey yarımküre 45° enlem, yıllık ortalam… | ±20 kt (1σ). Doğu rotasında yakıt ×0.82 (−%18), batı rotasın… |
| 10 | `co2` | ✅ doğru | ICAO CORSIA / IPCC 2006 Guidelines — Jet A-1 emisyon faktörü 3.16 kg C… | Yakıt hatasını devralır; SAF karışımı varsa düşer.… |
| 11 | `nox_co` | ⚠ çekinceli | ICAO EDB (Engine Emissions Databank) — LTO ve cruise emisyon indeksler… | NOₓ cruise ±%30; CO/HC LTO ±%15; PM ±%40.… |
| 12 | `annual_projection` | ⚠ notlu | IATA/Airbus GMF kullanım oranları (345 operasyonel gün); Boeing/Airbus… | Sefer/gün ±%30; realization factor ±%15. Müşteri schedule ve… |
| 13 | `realization_factor` | 🔶 varsayım | Sektör deneyimi — ATC kısıtları, hava, slot. Yayımlanmış tek bir evren… | ±%15; müşteri kabulüyle sıfıra iner.… |
| 14 | `fuel_price` | 🔴 en zayıf | IATA Fuel Monitor genel eğilimi (varsayılan $0.85/kg)… | ±%10 günlük; müşteri kontratı ±%30 farklı olabilir.… |
| 15 | `aircraft_database` | ✅ doğru | OpenAP v3 aircraft/*.yml + dragpolar/*.yml (11 tip, birebir); OEW/kolt… | OEW ±%3 (müşteri konfigürasyonu); CD0 ±%5.… |
| 16 | `airport_database` | ✅ doğru | OurAirports açık veri seti (koordinat, irtifa, pist) + ICAO Doc 7910 k… | Konum ±11 m; irtifa ±1 ft. Rota hesabı için yeterli.… |

## 1. ISA standart atmosfer — sıcaklık, basınç, yoğunluk

**Nerede** — `src/units.py::density_at_altitude, mach_to_tas`

**Formül** —
```
T = T0 − 0.0065·h (troposfer); p = p0·(1−2.25577e-5·h)^5.25588
```

**Kaynak** — ICAO Doc 7488 — Manual of the ICAO Standard Atmosphere (1993)
  
<https://www.icao.int/>
  
_tür: uluslararası standart_

**Doğruluk** — correct

Troposfer üs ve katsayılar ICAO Doc 7488 ile birebir. Stratosferde izotermal katman (11–20 km) doğru uygulanıyor. Doğrulama: 0 ft→15 °C / 35 000 ft→−54.3 °C / 40 000 ft→−56.5 °C.

**Belirsizlik** — Gerçek atmosfer ISA'dan ±15 °C sapabilir; delta_isa parametresi ile modellenir.

## 2. Basınç oranı δ = p/p₀ (motor thrust lapse için)

**Nerede** — `src/models/fuel_model.py::_pressure_ratio`

**Formül** —
```
δ = (1 − 6.87559e-6·h_ft)^5.25588 ; h>36 089 ft → 0.223361·exp(−(h_m−11000)/6341.62)
```

**Kaynak** — ICAO Doc 7488; US Standard Atmosphere 1976
  
<https://ntrs.nasa.gov/citations/19770009539>
  
_tür: uluslararası standart_

**Doğruluk** — correct

Katsayı ft⁻¹ cinsindendir (2.25577e-5 m⁻¹ × 0.3048). Doğrulama: 0 ft→1.0000, 10 000→0.6877, 20 000→0.4595, 35 000→0.2353, 40 000→0.1851 — tablo değerleriyle uyumlu.

**Belirsizlik** — Yok — deterministik standart.

## 3. Sürükleme poları CD = CD0 + K·CL²

**Nerede** — `src/models/fuel_model.py::drag_coefficient`

**Formül** —
```
CD = CD0 + K·CL²  (parazit + indüklenmiş sürükleme)
```

**Kaynak** — OpenAP v3 (TU Delft / Junzi Sun) dragpolar veri dosyaları; orijinal: Sun et al. (2020) "OpenAP: An Open-Source Aircraft Performance Model for Air Transportation Studies"
  
<https://github.com/junzis/openap>
  
_tür: açık kaynak + hakemli yayın_

**Doğruluk** — correct

Klasik polar ayrışımı doğru. CD0/K değerleri 11 tip için OpenAP veri dosyalarından alındı (kullanıcı isteği: yayımlanmış kaynak). Öz-tutarlılık kanıtı: B738 K=0.042 = 1/(π·0.799·9.45), OpenAP'ın kendi kanat açıklığı 34.32 m ile.

**Belirsizlik** — CD0 ±5 %, K ±3 %. π·AR·e yerine doğrudan K kullanıldığı için geometri tutarsızlığı sonucu etkilemez.

## 4. Sıkıştırılabilirlik (dalga) sürüklemesi

**Nerede** — `src/models/fuel_model.py::drag_coefficient (+_critical_mach)`

**Formül** —
```
ΔCD = 20·(M − M_cr)⁴ (M>M_cr) ; M_cr = M_dd − 0.06·CL
```

**Kaynak** — Raymer, "Aircraft Design: A Conceptual Approach" 6th ed. §12.5 (Korn/Lock kritik Mach yaklaşımı); Shevell (1989) "Fundamentals of Flight" §6.6
  
<https://arc.aiaa.org/doi/book/10.2514/4.104909>
  
_tür: hakemli ders kitabı_

**Doğruluk** — correct

Dalga sürükleme eğrisi M_cr üzerinde 4. kuvvetle büyür — standart ampirik biçim. Etki: B738 M0.82'de ΔCD=+0.00025, L/D 17.3→16.7 (−%3.5) — yayımlanan değerlerle tutarlı. M_cr MMO−0.03 ile sınırlandığı için MMO üstü uçuşta bile fiziksel davranır.

**Belirsizlik** — M_dd ±0.01; ΔCD bu bölgede 4. kuvvetle büyüdüğü için belirsizlik M_cr yakınında küçük, MMO'da ±%20 CD artışı.

## 5. Kaldırma katsayısı CL

**Nerede** — `src/models/fuel_model.py::lift_coefficient`

**Formül** —
```
CL = W·g / (q·S) ; q = ½·ρ·V²
```

**Kaynak** — Anderson, "Fundamentals of Aerodynamics" 6th ed. Ch. 1 — tanım denklemi; yeni bir varsayım değil, fiziksel tanım
  
<https://www.mheducation.com/highered/product/fundamentals-aerodynamics-anderson/M9781259129919.html>
  
_tür: hakemli ders kitabı_

**Doğruluk** — correct

Kaldırma tanımının doğrudan uygulanması; seviye uçuşta L=W.

**Belirsizlik** — Yok — tanım. S ve ρ belirsizliği polar'a girer.

## 6. Cruise yakıt akışı

**Nerede** — `src/models/fuel_model.py::cruise_fuel_flow`

**Formül** —
```
Birincil: FF[kg/s]/motor = c1 − exp(−c2·(r·e^(c3·r) − ln(c1)/c2)), r = D/(n_eng·T_SL)
Yedek: FF = SFC·D (SFC kg/N/s, D Newton)
```

**Kaynak** — ICAO Engine Emissions Databank (ICAO EDB) yakıt modeli; OpenAP v3 fuel_models.csv katsayıları (openap/fuel.py)
  
<https://www.easa.europa.eu/en/domains/environment/icao-aircraft-engine-emissions-databank>
  
_tür: uluslararası veritabanı_

**Doğruluk** — correct

r = D/T_SL (δ ile BÖLÜNMEZ — thrust lapse zaten yakıt eğrisinin içinde). Doğrulama: 11 tip için OpenAP referansına karşı ortalama mutlak sapma %3.18; 9/11 tip <%5. B738 5.84 vs 6.05 kg/nm (−%3.5), A320 5.94 vs 5.95 (−%0.2), B77W 25.27 vs 25.23 (+%0.2).

**Belirsizlik** — Katsayılar ICAO EDB'den; LTO dışı cruise noktasında türetilmiş. Motor eşleştirmesi belirsizliği: B789 (−%9.2, GEnx-1B70 vs -1B76) ve A380 (+%7.2, GP7270 vs Trent 970). Neo/MAX tipler default×ff_to ile türetildi → aşağı yönlü sınır (A20N 3.88 kg/nm; gerçek ~4.5-5.5).

## 7. Faz yakıtı (taksi, kalkış, tırmanma, alçalma, yaklaşma, holding)

**Nerede** — `src/models/fuel_model.py::estimate_phase_fuel`

**Formül** —
```
FF_faz = EDB_eğrisi(r_faz)·n_eng·3600 ; r: TAKEOFF 0.295, CLIMB 0.214, DESCENT 0.059, APPROACH 0.105, HOLDING 0.143, GROUND 0.043
```

**Kaynak** — tools/calibrate_phase_thrust.py — B738/B77W/A380 yayımlanmış faz yakıtlarından thrust oranı geri çözümü (config/phase_thrust_table.yaml)
  
<https://github.com/junzis/openap>
  
_tür: türetilmiş (kalibre edilmiş)_

**Doğruluk** — acceptable_with_caveat

Thrust oranları üç uçakta fiziksel aralıkta (takılış %26-44, rölanti %3-5). B738 hatası ±%10. Geniş gövdede sistematik +%25 (B77W) / −%17 (A380) sapma VAR — model faz başına ortalama thrust kullanıyor, uçağa özgü derate profili değil.

**Belirsizlik** — Faz yakıtı ±%25 (1σ); toplam görev yakıtına etkisi ±%2 (fazlar toplamın ~%15'i). Gerçek FDR verisiyle uçak tipi başına kalibre edilebilir.

## 8. Spesifik yakıt tüketimi (SFC) ve düzeltmeleri

**Nerede** — `src/models/fuel_model.py::corrected_sfc`

**Formül** —
```
SFC_corr = SFC_ref × f(irtifa) × f(Mach) × f(ΔISA)
```

**Kaynak** — BADA 3.12 (EUROCONTROL) fonksiyonel biçim; sayısal değerler uçak veritabanından (Boeing/Airbus ACM)
  
<https://www.eurocontrol.int/model/bada>
  
_tür: lisanslı model (biçim) + üretici verisi_

**Doğruluk** — correct_with_note

Düzeltme fonksiyonları BADA biçimine uygun. ANCAK birincil yol artık ICAO EDB eğrisi olduğu için corrected_sfc yalnızca yedek yolda ve SAF düzeltmesinde kullanılıyor.

**Belirsizlik** — Yedek yol için ±%8; SAF için CORSIA düzeltmesi ±%3.

## 9. Rüzgar profili ve rota bileşeni

**Nerede** — `src/models/wind_model.py (yeni); src/analysis/fleet_analyzer.py::_block_hours`

**Formül** —
```
V_w(h): kırılma noktaları arası doğrusal interpolasyon, zemin 8 kt → FL380 109 kt → FL450 86 kt
W_along = V_w·cos(track − (dir+180)) ; GS = TAS + W_along
```

**Kaynak** — NOAA/NCEP GFS klimatolojisi (Kuzey yarımküre 45° enlem, yıllık ortalama); ICAO Doc 7488 rüzgarsız referans
  
<https://www.ncei.noaa.gov/products/global-forecast-system>
  
_tür: klimatolojik veri_

**Doğruluk** — correct_with_caveat

Profil sürekli (500 ft adımında maks 2.5 kt değişim) ve fiziksel: jet çekirdeği FL380'de 109 kt, FL350'de 98 kt — literatürle uyumlu. Yön Kuzey yarımküre batı rüzgarı (270°). Klimatolojik ortalama olduğu için GÜNLÜK rüzgarı temsil etmez.

**Belirsizlik** — ±20 kt (1σ). Doğu rotasında yakıt ×0.82 (−%18), batı rotasında ×1.27 (+%27) — yani belirsizlik tek uçuşta ±%20 mertebesinde. Uzun rota yıllık projeksiyonunda ortalamada dengelenir.

## 10. CO₂ emisyonu

**Nerede** — `src/models/emission_model.py`

**Formül** —
```
CO₂[kg] = yakıt[kg] × 3.16 (Jet A-1 tam yanma)
```

**Kaynak** — ICAO CORSIA / IPCC 2006 Guidelines — Jet A-1 emisyon faktörü 3.16 kg CO₂/kg yakıt
  
<https://www.icao.int/environmental-protection/CORSIA>
  
_tür: uluslararası standart_

**Doğruluk** — correct

3.16 değeri CORSIA varsayılanıdır (Jet A-1 için 3.157-3.16). Yakıt tüketimi CO₂'nin tek belirleyicisi olduğu için emisyon hatası = yakıt hatası.

**Belirsizlik** — Yakıt hatasını devralır; SAF karışımı varsa düşer.

## 11. NOₓ, CO, HC, PM emisyonları

**Nerede** — `src/models/emission_model.py`

**Formül** —
```
E = yakıt × EI(irtifa, thrust oranı) [ICAO EDB]
```

**Kaynak** — ICAO EDB (Engine Emissions Databank) — LTO ve cruise emisyon indeksleri
  
<https://www.easa.europa.eu/domains/environment/icao-aircraft-engine-emissions-databank>
  
_tür: uluslararası veritabanı_

**Doğruluk** — acceptable_with_caveat

LTO indeksleri doğrudan EDB'den. Cruise NOₓ için EDB yaklaşımı (BFFM2/FOA yöntemi) kullanılıyor — bu, pistonlu/az sayıda veri noktasına dayanan ampirik bir yöntemdir; ±%30 belirsizlik literatürde kabul edilir.

**Belirsizlik** — NOₓ cruise ±%30; CO/HC LTO ±%15; PM ±%40.

## 12. Yıllık tasarruf projeksiyonu

**Nerede** — `config/assumptions.py::annual_projection`

**Formül** —
```
yıllık = uçuş_tasarrufu × sefer/gün × 345 gün/yıl × RF
kısıt: yıllık blok-saat ≤ 4 500 h → sefer/gün kırpılır
```

**Kaynak** — IATA/Airbus GMF kullanım oranları (345 operasyonel gün); Boeing/Airbus operatör kılavuzları (4 500 blok-saat/yıl muhafazakâr üst sınır); sefer/gün frekansı KAYNAKSIZ TAHMİN (OAG eğilimi, ±%30)
  
<https://www.iata.org/en/publications/>
  
_tür: karma — fiziksel kısıt + tahmin_

**Doğruluk** — correct_with_caveat

Fiziksel blok-saat tavanı eklendi: 8 000 nm rotada 1 sefer/gün fiziksel değildi (6 246 h/yıl) → 0.72 sefer/gün'e kırpılıyor. Gün sayısı ve tavan endüstri standardında. ANCAK sefer/gün hâlâ tahmindir; 1 560 nm'de 4→2 sefer/gün gibi bant geçişleri keyfidir.

**Belirsizlik** — Sefer/gün ±%30; realization factor ±%15. Müşteri schedule verisiyle ±%5'e düşer. Yıllık projeksiyon ASLA tek başına bir sayı olarak sunulmamalı — aralık verilmeli.

## 13. Gerçekleşme faktörü (teorik → operasyonel tasarruf)

**Nerede** — `config/assumptions.py::REALIZATION_FACTOR`

**Formül** —
```
gerçekçi_tasarruf = teorik_tasarruf × 0.65
```

**Kaynak** — Sektör deneyimi — ATC kısıtları, hava, slot. Yayımlanmış tek bir evrensel katsayı YOK.

  
_tür: uzman varsayımı_

**Doğruluk** — assumption_only

0.65 muhafazakâr ve savunulabilir bir aralıkta (0.5-0.8), ama keyfîdir. Müşteri verisiyle (pilot uyum oranı, ATC kısıt istatistiği) kalibre edilmelidir.

**Belirsizlik** — ±%15; müşteri kabulüyle sıfıra iner.

## 14. Yakıt fiyatı

**Nerede** — `config/settings.py, src/optimization/altitude_optimizer.py`

**Formül** —
```
maliyet = yakıt_kg × fiyat_usd_per_kg
```

**Kaynak** — IATA Fuel Monitor genel eğilimi (varsayılan $0.85/kg)
  
<https://www.iata.org/en/publications/economics/fuel-monitor/>
  
_tür: piyasa verisi (statik)_

**Doğruluk** — weakest_link

Fiyat statik gömülü — güncel piyasa/müşteri kontratıyla değişir. Tüm $ KPI'ları bu değere doğrusal bağlı. Kod içinde sabit (altitude_optimizer L583-584) — konfigürasyona taşınmalı.

**Belirsizlik** — ±%10 günlük; müşteri kontratı ±%30 farklı olabilir.

## 15. Uçak veritabanı (OEW, MTOW, wing_area, CD0, K, e, SFC)

**Nerede** — `config/aircraft_database.yaml`

**Formül** —
```
—
```

**Kaynak** — OpenAP v3 aircraft/*.yml + dragpolar/*.yml (11 tip, birebir); OEW/koltu B38M Boeing, A20N Airbus
  
<https://github.com/junzis/openap>
  
_tür: açık kaynak + üretici verisi_

**Doğruluk** — correct

11 tipin CD0/K/e'si OpenAP'tan birebir. OEW/MTOW üretici verisiyle doğrulandı (B38M 45 070 kg, 777W S=436.8 m²). Kalan tutarsızlık: B77W AR 9.82 vs 9.613 (kanat açıklığı winglet dahil/hariç farkı — sonuca etkisiz, K doğrudan).

**Belirsizlik** — OEW ±%3 (müşteri konfigürasyonu); CD0 ±%5.

## 16. Havalimanı veritabanı (45 havalimanı)

**Nerede** — `src/data_collection/airport_database.py`

**Formül** —
```
—
```

**Kaynak** — OurAirports açık veri seti (koordinat, irtifa, pist) + ICAO Doc 7910 konum göstergeleri
  
<https://ourairports.com/data/>
  
_tür: açık veri + ICAO dokümanı_

**Doğruluk** — correct

45 kaydın tamamı OurAirports ile karşılaştırıldı: 27 havalimanında 0 hata, kalan 18 koordinat/irtifa için doğrulandı. Koordinat 4 ondalık ≈ 11 m hassasiyet.

**Belirsizlik** — Konum ±11 m; irtifa ±1 ft. Rota hesabı için yeterli.

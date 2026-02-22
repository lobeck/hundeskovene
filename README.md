# Danmarks Hundeskove – kort

Simpelt kort over danske hundeskove med oversigt og detaljer (størrelse, faciliteter). Plain HTML, CSS og JavaScript med data i lokale filer.

## Kør projektet

Browsere tillader som regel ikke at loade lokale JSON-filer via `file://`. Brug en lokal webserver, f.eks.:

```bash
# Fra projektmappen (hundeskov-map)
npx serve .
# eller
python3 -m http.server 8000
```

Åbn derefter `http://localhost:3000` (serve) eller `http://localhost:8000` (python) i browseren.

## Filer

- **index.html** – side med kort, sidebar-liste og sprogvælger (DA / EN / DE)
- **css/style.css** – layout og styling
- **js/app.js** – indlæsning af data og locale, Leaflet-kort, popups, detailpanel og oversættelser
- **locales/da.json**, **locales/en.json**, **locales/de.json** – tekster til UI og til faciliteter (kun disse oversættes; navne og beskrivelser står i data)
- **data/hundeskove.json** – genereret, kompakt GeoJSON (ét request, hurtig indlæsning)
- **data/forests/*.json** – én fil per hundeskov (navn, adresse, beskrivelse på originalsprog; id, størrelse, feature_keys)
- **scripts/build_hundeskove.py** – samler alle `data/forests/*.json` til én kompakt fil

## Byg data (efter ændringer i forests/)

```bash
python3 scripts/build_hundeskove.py
```

Kør fra projektmappen. Scriptet læser alle `.json` i `data/forests/`, bygger en `FeatureCollection` og skriver en minimal `data/hundeskove.json` uden mellemrum (hurtigere load, færre bytes).

## Dataformat

Kilde-data: hver fil i **data/forests/** er en enkelt GeoJSON `Feature`. Output **data/hundeskove.json** er en GeoJSON `FeatureCollection`. Hver `Feature` har:

- **geometry** – `Point` med `[lng, lat]` eller `Polygon`/`MultiPolygon` med koordinatringe (outline af området)
- **properties**
  - `id` – unikt id
  - `name` – navn (originalsprog, f.eks. dansk)
  - `address` – adresse/kommune
  - `size_hectares` – areal i hektar (tal)
  - `feature_keys` – array af facilitetsnøgler (f.eks. `"fenced"`, `"parking"`); oversættes via `feature.<key>` i locale-filerne
  - `description` – valgfri beskrivelse (originalsprog)

Kun **UI-tekster** og **facilitetslabels** (f.eks. "Parkering" / "Parking" / "Parkplatz") oversættes i **locales/**. Navne og beskrivelser vises som i data (typisk dansk).

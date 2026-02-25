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
- **data/forest_overrides.json** – valgfri overstyringer (størrelse, beskrivelse, faciliteter) når data opdateres via refresh-scriptet
- **data/geocode_cache.json** – cache af stedsnavne fra Nominatim (oprettes automatisk ved refresh med reverse geocoding)
- **scripts/build_hundeskove.py** – samler alle `data/forests/*.json` til én kompakt fil
- **scripts/refresh_forest_data.py** – henter hundeskove fra OpenStreetMap (Overpass), merger overrides/CSV og opdaterer `data/forests/` og `data/hundeskove.json`
- **scripts/refresh_forest_data_local.py** – samme pipeline som ovenstående, men læser fra en lokal OSM PBF-fil (f.eks. `data/denmark-260224.osm.pbf`); afhængigheder angives inline (PEP 723), kør med `uv run scripts/refresh_forest_data_local.py`

## Opdater forest-data (refresh)

For at hente alle hundeskove fra OpenStreetMap og opdatere `data/forests/` og `data/hundeskove.json`:

```bash
python3 scripts/refresh_forest_data.py
```

**Lokal PBF:** Hvis du har en Denmark-udtræk (f.eks. `data/denmark-260224.osm.pbf`), kan du opdatere uden Overpass:

```bash
uv run scripts/refresh_forest_data_local.py
```

Evt. anden fil: `python3 scripts/refresh_forest_data_local.py --pbf sti/til/fil.osm.pbf`. Samme overrides/CSV og reverse geocoding som Overpass-scriptet.

Kør fra projektmappen. Scriptet:

1. Henter `leisure=dog_park` i Danmark fra Overpass API (efter landegrænse, ikke bbox)
2. Konverterer til appens GeoJSON-format og skriver én fil per skov i `data/forests/`
3. Merger valgfri `data/forest_overrides.json` og valgfri `data/forest_updates.csv` (overskriver felter hvor OSM mangler data)
4. Hvor adressen stadig er "Danmark", slår scriptet stedsnavn op via Nominatim (reverse geocoding, 1 forespørgsel/sekund)
5. Kører `build_hundeskove.py` så `data/hundeskove.json` opdateres

Kør med `--no-reverse-geocode` for at springe stedsnavnsopslag over (hurtigere, adresse forbliver "Danmark" hvor OSM ikke har addr-tags).

**Override-fil** (`data/forest_overrides.json`): JSON-objekt med nøgler enten numerisk id (f.eks. `"1"`) eller OSM-id (f.eks. `"way/12345"`). Værdier er delvise properties der overskriver OSM-data, f.eks.:

```json
{
  "1": { "size_hectares": 4.2, "description": "Lille skov...", "feature_keys": ["fenced","parking","water"] },
  "way/12345": { "address": "Aarhus Kommune" }
}
```

**CSV** (`data/forest_updates.csv`, valgfri): Kolonner `id`, `name`, `address`, `size_hectares`, `description`, `feature_keys` (semicolon- eller kommasepareret). `id` matcher numerisk id eller OSM-id. Samme merge-logik som overrides.

For at bevare de oprindelige 6 hundeskove med manuelle tekster: lav et backup af `data/forests/` før første kørsel, eller udfyld `forest_overrides.json` med deres data keyed på det tilsvarende nye numeriske id eller OSM-id efter første refresh.

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

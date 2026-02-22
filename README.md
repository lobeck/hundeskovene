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

- **index.html** – side med kort og sidebar-liste
- **css/style.css** – layout og styling
- **js/app.js** – indlæsning af data, Leaflet-kort, popups og detailpanel
- **data/hundeskove.json** – genereret, kompakt GeoJSON (ét request, hurtig indlæsning)
- **data/forests/*.json** – én fil per hundeskov (rediger her; generer derefter `hundeskove.json` med scriptet)
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
  - `name` – navn
  - `address` – adresse/kommune
  - `size_hectares` – areal i hektar (tal)
  - `features` – array af faciliteter (f.eks. "Indhegnet", "Parkering", "Toilet")
  - `description` – valgfri kort beskrivelse

Du kan erstatte eller udvide `hundeskove.json` med data fra f.eks. [opendata.dk](https://www.opendata.dk) (Syddjurs, Aarhus, København m.fl.) ved at mappe deres felter til dette format.

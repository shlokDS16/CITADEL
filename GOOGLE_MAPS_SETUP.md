# Google Maps — optional upgrade for the Anomaly Monitoring city map

The Anomaly Monitoring map ships on **Leaflet + OpenStreetMap**: zero key,
zero billing, full search (Nominatim) + colored zone circles + popups. It
works out of the box.

If you later want Google basemaps / Street View, here is the exact flow.

## Is billing really required?

Yes — Google Maps Platform requires a billing account (a card on file)
even for the free allowance. **A card on file does not mean you are
charged.** Google grants a recurring monthly free usage tier; while you
stay under it, the invoice is ₹0. This is exactly the "mandate but no
payment taken" state you described from your earlier project — that *is*
the billing account, and it was never charged because usage stayed free.

## Step-by-step: get a Maps JavaScript API key

1. Go to <https://console.cloud.google.com/> and sign in.
2. Top bar → **Select a project** → **New Project** → name it
   `citadel-maps` → **Create**.
3. With the project selected, open
   <https://console.cloud.google.com/google/maps-apis/> (Google Maps
   Platform).
4. **Billing**: it will prompt to link a billing account. Add one
   (card / UPI mandate). You stay on the free tier.
5. **APIs**: enable **Maps JavaScript API** (and **Maps Static API** if
   you want raster tiles, **Geocoding API** if you want Google search
   instead of the free Nominatim we already use).
6. **Credentials** → **Create credentials** → **API key**. Copy it.
7. **Restrict the key** (important — prevents abuse / surprise bills):
   - *Application restrictions* → **HTTP referrers** → add your domain(s)
     e.g. `http://127.0.0.1:8080/*` for local, plus your prod domain.
   - *API restrictions* → restrict to just the APIs you enabled.
8. (Recommended) **Set a budget + quota cap**: Billing → Budgets &
   alerts → create a ₹0–₹1 budget alert; APIs & Services → Maps
   JavaScript API → Quotas → cap daily map loads so you can never exceed
   the free tier.

## Wiring the key into CITADEL

The map component is already **Google-ready**. In `pages.jsx`, near the
`AnomalyCityMap` component:

```js
const ANOMALY_TILE_URL  = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const ANOMALY_TILE_ATTR  = '© OpenStreetMap';
```

Google does not serve official raster XYZ tiles for arbitrary use — the
Maps JavaScript API renders its own canvas. Two supported paths:

- **Stay on Leaflet, swap the basemap** to another keyless provider
  (e.g. Carto, Stadia free tier) by changing only `ANOMALY_TILE_URL`.
- **Full Google Maps JS**: load
  `https://maps.googleapis.com/maps/api/js?key=YOUR_KEY` in
  `CITADEL.html` and replace the Leaflet block in `AnomalyCityMap`
  with a `google.maps.Map` instance. The zone/marker/popup logic maps
  1:1 (`L.circle` → `google.maps.Circle`, `L.marker` →
  `google.maps.Marker`, `bindPopup` → `InfoWindow`). Scoped, ~1 file.

Recommendation: keep Leaflet. It already does location search, colored
zone marking by reading, labels and popups with no billing surface. Only
move to Google if you specifically need Street View or Google's POI layer
for a client demo.

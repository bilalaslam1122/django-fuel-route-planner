# Fuel Route Planner

A Django API that plans a road trip between two places in the USA and suggests where to buy fuel along the way, choosing stops by **price**, not just distance.

You send a start and a finish such as `"New York, NY"` → `"Chicago, IL"`. The API finds the driving route, looks for fuel stations close to that route, and works out the cheapest set of stops that gets the vehicle there without running dry. It also tells you how much the fuel costs.

The vehicle rules come from the assignment:

- Maximum range: **500 miles** on a full tank
- Fuel economy: **10 miles per gallon**, so the tank effectively holds **50 gallons**
- Fuel prices: taken **only** from the supplied price file

---

## Quick start

You need **Python 3.12 or newer**, because Django 6.1 requires it. The project was built on Python 3.14.

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your local settings file
cp .env.example .env              # the defaults work as-is for local development

# 4. Create the database (SQLite, nothing to install)
python manage.py migrate

# 5. Load the fuel stations from the supplied CSV
python manage.py import_fuel_data

# 6. Run the tests
python manage.py test

# 7. Start the server
python manage.py runserver
```

The API is now at **`POST http://127.0.0.1:8000/api/route/`**.

Step 5 takes a couple of seconds and prints a short report:

```
Rows read:                 8151
Skipped (Canada):          620
Invalid rows:              0
Duplicate rows merged:     905 (487 stations had differing prices; lowest kept)
Unique US stations:        6626
  created / updated / deleted: 6626 / 0 / 0
  without coordinates:     5 (excluded from routing)
Fuel data import complete.
```

You can run the import as often as you like. It updates stations in place, and the running API picks up changes automatically.

---

## Using the API

### Request

```
POST /api/route/
Content-Type: application/json
```

```json
{
  "start": "New York, NY",
  "finish": "Chicago, IL"
}
```

| Field | Required | Notes |
|---|---|---|
| `start` | yes | Any US place: `"Austin, TX"`, `"Dallas, Texas"`, `"1600 Pennsylvania Avenue NW, Washington, DC"` |
| `finish` | yes | Same as `start` |
| `include_geometry` | no (default `true`) | Set to `false` to leave out the route line and keep the response short |

The trailing slash is optional: `/api/route` works too.

**Tip:** always include the state. A plain `"Paris"` resolves to Paris, France and is rejected. `"Paris, TX"` works.

### Response (real output, geometry shortened)

```json
{
  "start":  { "query": "New York, NY", "resolved_name": "New York, United States", "state": "NY", "latitude": 40.7127281, "longitude": -74.0060152 },
  "finish": { "query": "Chicago, IL", "resolved_name": "Chicago, ..., Illinois, United States", "state": "IL", "latitude": 41.8755616, "longitude": -87.6244212 },
  "route": {
    "distance_miles": 790.6,
    "duration_minutes": 891,
    "geometry": { "type": "LineString", "coordinates": [[-74.00574, 40.71212], "...", [-87.62435, 41.87556]] }
  },
  "vehicle": {
    "max_range_miles": 500.0,
    "fuel_economy_mpg": 10.0,
    "tank_capacity_gallons": 50.0,
    "starting_fuel_gallons": 50.0
  },
  "fuel_plan": {
    "currency": "USD",
    "number_of_stops": 2,
    "total_gallons_purchased": 29.057,
    "total_cost": 87.72,
    "fuel_used_gallons": 79.057,
    "fuel_remaining_at_finish_gallons": 0.0,
    "cost_basis": "total_cost is the money spent at fuel stops; the trip starts with a full tank.",
    "stops": [
      {
        "stop_number": 1,
        "station_id": 72445,
        "name": "SHEETZ #639",
        "address": "I-80 Exit 223",
        "city": "Youngstown",
        "state": "OH",
        "latitude": 41.099095,
        "longitude": -80.645902,
        "distance_from_start_miles": 390.8,
        "distance_from_route_miles": 3.8,
        "fuel_price_per_gallon": 3.059,
        "fuel_on_arrival_gallons": 10.922,
        "gallons_purchased": 5.674,
        "cost": 17.36
      },
      {
        "stop_number": 2,
        "station_id": 72288,
        "name": "S&G #88",
        "address": "I-475 Exit 13 & US-20",
        "city": "Toledo",
        "state": "OH",
        "distance_from_start_miles": 556.7,
        "fuel_price_per_gallon": 3.009,
        "fuel_on_arrival_gallons": 0.0,
        "gallons_purchased": 23.383,
        "cost": 70.36
      }
    ]
  },
  "meta": {
    "route_corridor_miles": 10.0,
    "candidate_stations": 226,
    "external_api_calls": 3,
    "cache_hits": 0,
    "timings_ms": { "geocoding": 500.0, "routing": 909.3, "station_matching": 73.9, "optimization": 0.2, "total": 1487.3 }
  }
}
```

Look at what the plan does here. At Youngstown it buys **only 5.7 gallons**, just enough to reach Toledo, where fuel is cheaper. Then it buys the rest at Toledo. That's the price optimisation at work.

### Errors

Every error has the same shape:

```json
{ "error": { "code": "location_outside_usa", "message": "Start location 'Toronto' resolved to Toronto, Ontario, Canada, which is outside the USA. ...", "details": { "field": "start", "did_you_mean": ["Toronto, Clinton County, Iowa, United States", "..."] } } }
```

| Status | `code` | When |
|---|---|---|
| 400 | `invalid_request` | `start` or `finish` missing or blank (`details` lists the fields) |
| 400 | `malformed_json` | Body isn't valid JSON |
| 405 | `method_not_allowed` | Anything other than POST |
| 422 | `location_not_found` | The geocoder can't find the place |
| 422 | `location_outside_usa` | The place is outside the 50 states and DC, including US territories such as Puerto Rico |
| 422 | `same_location` | Start and finish are the same place |
| 422 | `route_not_found` | No drivable route exists, e.g. to Hawaii |
| 422 | `no_feasible_fuel_plan` | Some stretch of the route is longer than 500 miles with no station in the data |
| 502 | `map_service_unavailable` | Geocoding or routing service is down or returned garbage |
| 503 | `fuel_data_unavailable` | No stations loaded; run `import_fuel_data` |
| 504 | `map_service_timeout` | Geocoding or routing service timed out |

Raw third-party errors are logged, never passed on to the caller.

### Postman

Import [`postman/fuel_route_planner.postman_collection.json`](postman/fuel_route_planner.postman_collection.json). It contains:

1. **Short trip**: Austin → Dallas, no stop needed
2. **Price-driven stops**: New York → Chicago
3. **Long trip**: New York → Los Angeles, many stops
4. **Full response with route geometry**
5. to 9. **Errors**: outside the USA, unknown place, missing field, malformed JSON, no feasible plan

The collection uses a `base_url` variable, set to `http://127.0.0.1:8000`.

---

## How it works

```
POST /api/route/
   │
   ├─ 1. Validate the body (DRF serializer)
   ├─ 2. Geocode start and finish  ── Nominatim ── cached 24h
   │      └─ top result must be in the 50 states or DC
   ├─ 3. Get the driving route     ── OSRM ─────── cached 1h
   ├─ 4. Find stations near the route        (local, numpy)
   ├─ 5. Choose the cheapest fuel stops      (local, pure Python)
   └─ 6. Price each stop with Decimal and return JSON
```

The view is a few lines long. All the logic lives in services that can be tested on their own.

### Finding stations near the route

1. OSRM returns the full road geometry, around 35,000 points for New York → Los Angeles. That's thinned to about **one point per mile**.
2. A bounding box around the route, padded by the corridor width, cheaply discards most of the 6,621 stations.
3. Every remaining station is projected onto the route line, which gives:
   - **how far it is from the road**. It's kept only if within **10 miles**.
   - **how many road miles from the start** it sits. This is its position on the trip.
4. Stations are loaded once into memory as numpy arrays. The whole matching step takes 5–80 ms.

**Road vs straight-line distance:** the trip distance, and every station's position along the trip, comes from the road route returned by OSRM. Straight-line (Haversine) maths is only used locally to measure how far a station sits from the road.

**Why 10 miles?** The fuel file has no coordinates, so each station is placed at its city's centre (see below). That's usually a few miles from the actual exit, so a 5-mile corridor would miss stations that really are on the highway. 10 miles catches them without pulling in far-away stations.

### Choosing the fuel stops

Once stations are positioned along the route, the problem becomes the classic "cheapest way to refuel along a road" problem. A simple greedy rule solves it exactly. At each stop:

1. **If a cheaper station is reachable on a full tank**, buy only enough fuel to get to the first such station. Any more would mean buying fuel here that could be bought cheaper there.
2. **Otherwise, if the destination is reachable on a full tank**, buy only enough to finish.
3. **Otherwise** this is the cheapest fuel in range, so **fill the tank** and drive to the cheapest station within range.

The start is treated as a free "station" where the tank is already full. If neither another station nor the destination is within 500 miles, there's no feasible plan and the API says where the gap is.

```
position = 0, fuel = full tank, at = start
loop:
    in_range = stations ahead within 500 miles
    if at a station and some station in in_range is cheaper:
        buy just enough to reach the first cheaper one; go there
    elif destination within 500 miles:
        buy just enough to finish; done
    elif in_range is not empty:
        fill the tank; go to the cheapest station in in_range
    else:
        no feasible plan
```

This looks at the whole route, not one stop at a time. It never picks a cheap station that leaves the car stranded, because only stations reachable with the current fuel or a full tank are considered. It runs in well under a millisecond.

**Proof it's optimal:** the test suite compares it with an exhaustive brute-force search on 150 random routes, and the costs match every time.

**Trade-off:** pure cost optimisation sometimes produces small top-ups. On New York → Los Angeles it makes 15 stops, a few of them for 1–2 gallons, to save cents. That's correct for the brief ("optimise primarily on price"). A per-stop penalty would trade a few cents for fewer stops if that's ever wanted.

### Money

- Prices are stored as exact `Decimal` values with 5 decimal places.
- Gallons per stop are rounded to 3 decimal places.
- Each stop's cost is `gallons × price`, calculated in `Decimal` and rounded half-up to cents.
- `total_cost` is the sum of the rounded stop costs, so the numbers in the response always add up.

---

## External APIs and how calls are kept low

| Need | Service | Why |
|---|---|---|
| Geocoding | **Nominatim** (OpenStreetMap) | Free, no key, and reports country and state, so "is this in the USA?" is checked from real data, not from the text the user typed |
| Routing | **OSRM** (OpenStreetMap) | Free, no key, and **one call** returns road distance, duration and full geometry |

| Situation | External calls |
|---|---|
| New trip | **3**: geocode start, geocode finish, one route |
| Either place seen before | 2 |
| Exact trip seen before | **0**. A repeat New York → Chicago request took 9 ms |
| Per fuel station | **never**: stations are matched locally |

OpenRouteService was the other serious option. It needs the same number of calls but requires an API key, which only adds setup work for whoever runs this.

Every call has a timeout (10 s by default), sends an identifying User-Agent as Nominatim requires, and has its response checked before use. Provider code lives only in the `maps/` package, so swapping providers doesn't touch the business logic.

Caching uses Django's built-in in-memory cache, which needs no Redis.

**Limits:** these are free public servers. Nominatim allows about 1 request per second, and OSRM's demo server is meant for light use. That's fine for a demo. For production you'd self-host them or use a paid tier by changing the URLs in `.env`.

---

## Typical performance

Measured locally:

| Step | Time |
|---|---|
| Geocoding, 2 calls (network) | 0.5–1.6 s |
| Routing, 1 call (network) | 0.6–1.1 s |
| Station matching | 5–80 ms |
| Fuel optimisation | < 1 ms |
| **Whole request, first time** | **≈ 1.3–2.5 s** |
| **Whole request, repeat** | **≈ 10 ms** |

Nearly all the time is spent waiting on the free map services. The local work is negligible.

---

## How the fuel data was prepared

### What's in the file

`data/fuel-prices-for-be-assessment.csv` has 8,151 rows:

```
OPIS Truckstop ID, Truckstop Name, Address, City, State, Rack ID, Retail Price
```

Looking at it closely shaped the whole design:

- **There are no coordinates.** Addresses look like `I-44, EXIT 283 & US-69`, which free geocoders can't resolve reliably.
- **Station IDs repeat.** 678 IDs appear more than once, and most of those list different prices.
- **About 620 rows are Canadian**, and their prices look like Canadian dollars. They're skipped.
- **Coverage is uneven.** It's good along the interstates, but California has only 16 stations, all in the far south-east, and Alaska, Hawaii and DC have none.
- **Smaller issues:** city names padded with spaces, prices with 3 to 8 decimal places, and inconsistent name casing.

### Giving stations a location

Each station is placed at the centre of its **city**. The coordinates were resolved once, offline, with `python manage.py build_city_coordinates`:

1. **US Census Gazetteer files** (free, public domain) resolved 3,664 of the 3,813 station cities.
2. **Nominatim** handled the 149 leftovers. A result was only accepted if Nominatim agreed on the state. That resolved 145 more.
3. **4 cities couldn't be found.** Their 5 stations are kept but left out of route planning.

The result, `data/city_coordinates.csv`, **ships with the project**. You don't need to rebuild it, and the API never geocodes stations.

Matching city names took some care, because the fuel file and the Census spell names differently: `Mc Calla` = `McCalla`, `La Salle` = `LaSalle`, `East Saint Louis` = `East St. Louis`, `Cañon City` = `Canon City`, `Macon` = `Macon-Bibb County`.

### The import

`python manage.py import_fuel_data`:

- checks the required columns and stops with a clear message if the file is missing or malformed
- trims and tidies every field
- skips Canadian rows
- rejects bad rows (missing or non-numeric price, unknown state, missing name or city) with line numbers
- merges duplicate station IDs and **keeps the lowest price**
- updates in place and removes stations no longer in the file, so it's always safe to re-run

---

## Configuration

All settings come from environment variables or a `.env` file. Nothing secret is hard-coded, and **no API keys are needed**.

| Variable | Default | What it does |
|---|---|---|
| `DJANGO_DEBUG` | `false` | Set to `true` for local development |
| `DJANGO_SECRET_KEY` | none | **Required** when debug is off |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names |
| `GEOCODING_API_URL` | `https://nominatim.openstreetmap.org` | Geocoding service |
| `ROUTING_API_URL` | `https://router.project-osrm.org` | Routing service |
| `EXTERNAL_API_USER_AGENT` | `fuel-route-planner/1.0 …` | Identifying User-Agent, required by Nominatim |
| `EXTERNAL_API_TIMEOUT_SECONDS` | `10` | Timeout for every external call |
| `GEOCODE_CACHE_SECONDS` | `86400` | How long geocoding results are cached |
| `ROUTE_CACHE_SECONDS` | `3600` | How long routes are cached |
| `ROUTE_CORRIDOR_MILES` | `10` | Maximum distance of a station from the route |
| `FUEL_DATA_CSV` | `data/fuel-prices-for-be-assessment.csv` | The supplied price file |
| `CITY_COORDINATES_CSV` | `data/city_coordinates.csv` | Pre-built station coordinates |

---

## Project layout

```
config/                     Django settings and root URLs
trips/                      The trip-planning API
  views.py                    Thin view: validate → planner → JSON
  serializers.py              Request validation
  planner.py                  Orchestration: geocode → route → match → optimise → response
  geometry.py                 Route thinning and station-to-route projection (numpy)
  station_index.py            In-memory station arrays, auto-refreshed after imports
  optimizer.py                The fuel-stop algorithm and Decimal cost maths
  exceptions.py               Error types and the JSON error format
  tests/
stations/                   Fuel-station data
  models.py                   FuelStation model
  fuel_data.py                CSV parsing, validation, de-duplication
  city_coordinates.py         City-name matching against Census data
  importer.py                 Saves stations to the database
  management/commands/        import_fuel_data, build_city_coordinates
  tests/
maps/                       External providers, isolated so they're easy to swap
  geocoding.py                Nominatim client
  routing.py                  OSRM client
  http.py                     Shared HTTP helper: timeouts, error handling
  tests/
data/                       Supplied fuel CSV and pre-built city coordinates
postman/                    Postman collection
```

---

## Tests

```bash
python manage.py test
```

There are 82 tests, all passing in well under a second. **No test calls a real external API**: the geocoder and router are replaced with fakes, so results are always the same.

- **API:** valid trip, trailing slash optional, caching, missing start, missing finish, blank fields, invalid JSON, wrong method, unknown place, non-USA place (with suggestions), US territory, same start and finish, routing failure (502), timeout (504), no route, no feasible plan, no data loaded, stations without coordinates
- **Algorithm:** under 500 miles, exactly 500 miles, over 500 miles, multiple stops, choosing the cheaper station, a cheap but unreachable station, a cheap station near the range limit, filling up before expensive stretches, no feasible plan, reaching the destination from the last stop, fuel quantities, **brute-force optimality on 150 random routes**, Decimal cost rounding
- **Geometry:** thinning, distance scaling, distance from route, position along route, end clamping
- **Data:** valid rows, missing prices, invalid rows, duplicates, Canadian rows, missing columns, empty files, city-name matching, idempotent import
- **Map clients:** parsing, malformed responses, timeouts, HTTP errors, "no route" responses

---

## Assumptions

| Topic | Assumption |
|---|---|
| Tank size | 500 miles ÷ 10 MPG = **50 gallons** |
| Starting fuel | The vehicle **starts with a full tank**. Trips up to 500 miles need no stop and cost $0 at the pump |
| "Total money spent" | `total_cost` = **money spent at fuel stops during the trip**. `fuel_used_gallons` shows the total fuel burned, including the starting tank |
| Fuel price | `Retail Price` is USD per gallon. The file doesn't name the fuel type; given the truck-stop brands it's most likely diesel |
| Duplicate stations | Same OPIS ID means the same station; the **lowest** price is kept |
| Canadian stations | Excluded, because trips are USA-only and prices appear to be in CAD |
| Station position | City centre of the station's city, accurate to a few miles |
| Detours | The few miles to reach an off-route station aren't added to fuel use. Each stop's `distance_from_route_miles` shows the offset |
| Ambiguous place names | The geocoder's top result is used. If it's outside the USA, the request is rejected with US suggestions instead of silently picking another country's town |

## Known limitations

- **California and Oregon have very few stations in the supplied data.** Long trips there, e.g. San Diego → Eureka, return `no_feasible_fuel_plan`. Short ones such as Los Angeles → San Francisco (381 miles) still work, because no stop is needed.
- Routes that pass through Canada, e.g. to Alaska, can't use Canadian stations, so they're often infeasible.
- Station locations are city-level, not exact exits.
- Cost-optimal plans can include small top-up stops (see [Choosing the fuel stops](#choosing-the-fuel-stops)).
- The free map services have fair-use limits; see above.

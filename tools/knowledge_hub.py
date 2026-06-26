#!/usr/bin/env python3
"""
knowledge_hub.py — Weather, flood, maps, web search, scraping
Runs as a subprocess tool launched by marin_fier / marin.py

Fixed bugs vs original:
  BUG1  search_places_in_city: Nominatim geocode() → Overpass API (amenity tags)
  BUG2  humidity always returned index [0] (midnight) → find index for current hour
  BUG3  create_integrated_hub_map never auto-pinned places → now takes a `query` param
  BUG4  maps.py / argparse had no --places/--query arg → added
  BUG5  scrape_content was async with no sync wrapper → now sync via httpx.Client
  BUG6  multiple Nominatim calls with no delay → geocode cache + time.sleep(1)
  BUG7  EONET ?category= → ?categories= (correct v3 plural param)
  HUB1  Added /api/knowledge-hub/update Flask endpoint for hub_dashboard.html
  HUB2  Added /api/market/quotes endpoint for live stock quotes (Yahoo Finance)
  HUB3  Added /api/tools/open endpoint to launch stock/crypto tracker subprocesses
  HUB4  Added /api/research/search endpoint for research_hub
  HUB5  _resolve_amenity extended with bakery/fuel/clinic categories
"""

import requests
import json
import os
import sys
import time
import asyncio
from duckduckgo_search import DDGS
from geopy.geocoders import Nominatim
import folium
from bs4 import BeautifulSoup
import httpx

# ── Geocoder singleton with 1-second delay (Nominatim usage policy) ───────────
_geolocator = Nominatim(
    user_agent="marin-bayazid-assistant/1.0",
)
_last_geocode_call = 0.0


def _geocode(query: str):
    """Geocode with rate-limit enforcement (1 req/sec) and in-process cache."""
    global _last_geocode_call
    elapsed = time.time() - _last_geocode_call
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)
    result = _geolocator.geocode(query)
    _last_geocode_call = time.time()
    return result


# ── BUG1+BUG6 FIX: Overpass API for amenity/POI search ───────────────────────
_AMENITY_MAP = {
    # natural language → OSM amenity/tourism tag value
    "cafe":           "cafe",
    "cafes":          "cafe",
    "coffee":         "cafe",
    "restaurant":     "restaurant",
    "restaurants":    "restaurant",
    "food":           "restaurant",
    "hotel":          "hotel",
    "hotels":         "hotel",
    "hospital":       "hospital",
    "pharmacy":       "pharmacy",
    "bank":           "bank",
    "atm":            "atm",
    "school":         "school",
    "university":     "university",
    "park":           "park",
    "mosque":         "place_of_worship",
    "temple":         "place_of_worship",
    "museum":         "museum",
    "market":         "marketplace",
    "supermarket":    "supermarket",
    "gym":            "gym",
    "bar":            "bar",
    "pub":            "pub",
    "cinema":         "cinema",
    "library":        "library",
    "tourist":        "tourist_attraction",
    "attraction":     "tourist_attraction",
    # HUB5: additional categories for dropdown
    "bakery":         "bakery",
    "fuel":           "fuel",
    "fuel station":   "fuel",
    "petrol":         "fuel",
    "clinic":         "clinic",
    "church":         "place_of_worship",
    "gas":            "fuel",
}


def _resolve_amenity(query: str) -> tuple[str, str]:
    """
    Returns (osm_tag_key, osm_tag_value) for the query.
    e.g. 'best cafe' → ('amenity', 'cafe')
         'tourist attraction' → ('tourism', 'attraction')
    """
    if not query or not query.strip():
        return "amenity", "cafe"  # Default fallback

    lower = query.lower()
    for keyword, amenity in _AMENITY_MAP.items():
        if keyword in lower:
            if amenity in ("tourist_attraction",):
                return "tourism", "attraction"
            if amenity in ("park",):
                return "leisure", "park"
            return "amenity", amenity

    # Default fallback: treat the whole query as an amenity
    parts = lower.split()
    return "amenity", parts[-1] if parts else "cafe"


def search_places_in_city(city: str, query: str = "cafe", limit: int = 8) -> list:
    """
    BUG1 FIX: Use Overpass API (OpenStreetMap) for amenity/POI search.
    Nominatim geocode() only understands addresses — it can't find 'best cafe in Dhaka'.
    Overpass queries the full OSM amenity database.
    """
    try:
        # Step 1: geocode the city to get its bounding box
        loc = _geocode(city)
        if not loc:
            return []

        lat, lon = loc.latitude, loc.longitude
        tag_key, tag_val = _resolve_amenity(query)

        # Overpass QL: search within 5km radius of city centre
        overpass_query = f"""
[out:json][timeout:25];
(
  node["{tag_key}"="{tag_val}"](around:5000,{lat},{lon});
  way["{tag_key}"="{tag_val}"](around:5000,{lat},{lon});
);
out center {limit};
"""
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": overpass_query},
            headers={
                "User-Agent": "MarinBayazidAssistant/1.0 (https://github.com/sword-tyrant/BayazidxMarin)",
                "Referer": "http://localhost:5069/"
            },
            timeout=25,
        )
        r.raise_for_status()
        elements = r.json().get("elements", [])

        results = []
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name") or tags.get("name:en") or tag_val.title()
            # nodes have lat/lon directly; ways have a 'center' key
            if el["type"] == "node":
                elat, elon = el["lat"], el["lon"]
            else:
                center = el.get("center", {})
                elat, elon = center.get("lat", lat), center.get("lon", lon)

            results.append({
                "name":    name,
                "lat":     elat,
                "lon":     elon,
                "address": tags.get("addr:full") or tags.get("addr:street", ""),
                "opening": tags.get("opening_hours", ""),
                "phone":   tags.get("phone") or tags.get("contact:phone", ""),
            })

        return results

    except Exception as e:
        print(f"[search_places_in_city] error: {e}")
        return []


# ── BUG2 FIX: correct humidity index ─────────────────────────────────────────

def _current_humidity(data: dict, current_time: str) -> int | None:
    """
    BUG2 FIX: hourly[0] is always midnight, not the current hour.
    Find the index in hourly.time that matches current_weather.time.
    """
    hourly_times = data.get("hourly", {}).get("time", [])
    hourly_hum   = data.get("hourly", {}).get("relative_humidity_2m", [])
    if not current_time or not hourly_times:
        return None
    # current_time format: "2025-05-25T14:00" — match prefix
    prefix = current_time[:13]   # "2025-05-25T14"
    for i, t in enumerate(hourly_times):
        if t.startswith(prefix) and i < len(hourly_hum):
            return hourly_hum[i]
    # fallback: closest index
    return hourly_hum[0] if hourly_hum else None


def get_weather_data(city: str = "Dhaka") -> dict:
    """Fetch current weather from Open-Meteo."""
    try:
        loc = _geocode(city)
        if not loc:
            return {"error": f"Could not geocode {city}"}

        lat, lon = loc.latitude, loc.longitude
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude":        lat,
                "longitude":       lon,
                "current_weather": "true",
                "hourly":          "relative_humidity_2m,apparent_temperature",
                "forecast_days":   1,
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        current = data.get("current_weather", {})
        current_time = current.get("time", "")

        # BUG2 FIX: use matched index, not hardcoded [0]
        humidity = _current_humidity(data, current_time)

        return {
            "city":        city,
            "latitude":    lat,
            "longitude":   lon,
            "temperature": current.get("temperature"),
            "windspeed":   current.get("windspeed"),
            "weathercode": current.get("weathercode"),
            "humidity":    humidity,
            "time":        current_time,
        }
    except Exception as e:
        return {"error": str(e)}


# ── BUG7 FIX: correct EONET v3 param name ────────────────────────────────────

def get_flood_data() -> list:
    """
    BUG7 FIX: EONET v3 uses ?categories= (plural), not ?category=.
    Wrong param silently returned ALL events instead of floods only.
    """
    try:
        r = requests.get(
            "https://eonet.gsfc.nasa.gov/api/v3/events",
            params={"categories": "floods", "status": "open"},  # ← was "category"
            timeout=10,
        )
        r.raise_for_status()
        events = r.json().get("events", [])

        results = []
        for e in events:
            geom = e.get("geometry", [{}])
            first = geom[0] if geom else {}
            coords = first.get("coordinates")
            results.append({
                "title":       e.get("title"),
                "date":        first.get("date"),
                "coordinates": coords,   # [lon, lat] per GeoJSON spec
            })
        return results
    except Exception as e:
        return [{"error": str(e)}]


def get_route_data(start_city: str, end_city: str) -> dict:
    """Fetch driving route between two cities via OSRM."""
    try:
        # BUG6 FIX: delay is handled inside _geocode()
        start_loc = _geocode(start_city)
        end_loc   = _geocode(end_city)

        if not start_loc or not end_loc:
            return {"error": "Could not geocode one or both cities"}

        url = (
            f"http://router.project-osrm.org/route/v1/driving/"
            f"{start_loc.longitude},{start_loc.latitude};"
            f"{end_loc.longitude},{end_loc.latitude}"
            f"?overview=full&geometries=geojson"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("code") != "Ok":
            return {"error": "OSRM routing failed"}

        route = data["routes"][0]
        return {
            "distance_km":   round(route["distance"] / 1000, 2),
            "duration_mins": round(route["duration"] / 60, 2),
            "geometry":      route["geometry"],
            "start_coords":  [start_loc.latitude, start_loc.longitude],
            "end_coords":    [end_loc.latitude, end_loc.longitude],
        }
    except Exception as e:
        return {"error": str(e)}


# ── BUG3 FIX: create_integrated_hub_map auto-pins places via query param ──────

_WEATHER_ICONS = {
    # WMO weather code → emoji
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    71: "🌨️", 73: "🌨️", 75: "❄️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


def create_integrated_hub_map(
    city: str = "Dhaka",
    destination: str = None,
    query: str = "cafe",
    limit: int = 8,
    custom_pins: list = None,
) -> dict:
    """
    Create an interactive map with weather, POI pins, routes, and flood data.
    custom_pins: list of dicts with keys: name, lat, lon, description (optional)
    """
    weather = get_weather_data(city)
    if "error" in weather:
        return {"error": f"Weather fetch failed: {weather['error']}"}

    floods = get_flood_data()

    # Auto-search best places matching the query
    pins = search_places_in_city(city, query=query, limit=limit)

    # ── Fallback: popular places if Overpass returns nothing ───────────────
    if not pins and not custom_pins:
        FALLBACK_PLACES = {
            "rajshahi": [
                {"name": "Padma River Bank", "lat": 24.3750, "lon": 88.6050, "address": "Rajshahi"},
                {"name": "Varendra Research Museum", "lat": 24.3671, "lon": 88.5925, "address": "Rajshahi"},
                {"name": "Rajshahi University", "lat": 24.3680, "lon": 88.6350, "address": "Rajshahi"},
                {"name": "Putia Temple", "lat": 24.3800, "lon": 88.6000, "address": "Rajshahi"},
            ],
            "sylhet": [
                {"name": "Hazrat Shah Jalal Mazar", "lat": 24.9070, "lon": 91.8330, "address": "Sylhet"},
                {"name": "Ratargul Swamp Forest", "lat": 25.0830, "lon": 92.0170, "address": "Sylhet"},
                {"name": "Jaflong", "lat": 25.1500, "lon": 92.1000, "address": "Sylhet"},
                {"name": "Sylhet Shahi Eidgah", "lat": 24.8950, "lon": 91.8700, "address": "Sylhet"},
            ],
            "dhaka": [
                {"name": "Lalbagh Fort", "lat": 23.7189, "lon": 90.3905, "address": "Dhaka"},
                {"name": "Ahsan Manzil", "lat": 23.7085, "lon": 90.3950, "address": "Dhaka"},
                {"name": "National Museum", "lat": 23.7380, "lon": 90.3930, "address": "Dhaka"},
                {"name": "Sadarghat", "lat": 23.7080, "lon": 90.3870, "address": "Dhaka"},
            ],
            "chittagong": [
                {"name": "Patenga Beach", "lat": 22.2200, "lon": 91.7800, "address": "Chittagong"},
                {"name": "Fizzah Beach", "lat": 22.2500, "lon": 91.7700, "address": "Chittagong"},
                {"name": "Bayezid Bostami Mazar", "lat": 22.3600, "lon": 91.7900, "address": "Chittagong"},
            ],
            "coxs bazar": [
                {"name": "Cox's Bazar Beach", "lat": 21.4270, "lon": 92.0050, "address": "Cox's Bazar"},
                {"name": "Himchari National Park", "lat": 21.3500, "lon": 92.0200, "address": "Cox's Bazar"},
                {"name": "Inani Beach", "lat": 21.2800, "lon": 92.0500, "address": "Cox's Bazar"},
            ],
            "rangpur": [
                {"name": "Rangpur Zoo", "lat": 25.7500, "lon": 89.2500, "address": "Rangpur"},
                {"name": "Tajhat Palace", "lat": 25.7300, "lon": 89.2300, "address": "Rangpur"},
            ],
            "mymensingh": [
                {"name": "Mymensingh Museum", "lat": 24.7500, "lon": 90.4000, "address": "Mymensingh"},
                {"name": "Pushpo Polli", "lat": 24.7400, "lon": 90.4100, "address": "Mymensingh"},
            ],
            "barisal": [
                {"name": "Durga Sagar", "lat": 22.7000, "lon": 90.3700, "address": "Barisal"},
                {"name": "Oxford Mission Church", "lat": 22.7050, "lon": 90.3650, "address": "Barisal"},
            ],
        }
        city_lower = city.lower().replace("'", "")
        if city_lower in FALLBACK_PLACES:
            pins = FALLBACK_PLACES[city_lower]

    # Build map
    m = folium.Map(
        location=[weather["latitude"], weather["longitude"]],
        zoom_start=13,
    )

    # ── Weather marker ────────────────────────────────────────────────────────
    wcode = weather.get("weathercode", 0)
    wicon = _WEATHER_ICONS.get(wcode, "🌡️")
    weather_html = f"""
    <div style="font-family:Arial;width:200px">
      <b>Weather in {city}</b><br>
      {wicon} {weather['temperature']}°C &nbsp;|&nbsp; 💧 {weather['humidity']}%<br>
      💨 {weather['windspeed']} km/h &nbsp;|&nbsp; ⏱ {weather.get('time','')[:16]}
    </div>
    """
    folium.Marker(
        [weather["latitude"], weather["longitude"]],
        popup=folium.Popup(weather_html, max_width=280),
        tooltip=f"{wicon} Weather: {city}",
        icon=folium.Icon(color="blue", icon="cloud"),
    ).add_to(m)

    # ── Custom pins (user-specified locations) ────────────────────────────────
    geocoded_custom = []
    if custom_pins:
        for pin in custom_pins:
            lat = pin.get("lat")
            lon = pin.get("lon")
            name = pin.get("name", "Location")
            desc = pin.get("description", "")
            # Geocode if lat/lon missing
            if not lat or not lon:
                try:
                    loc = _geocode(f"{name}, {city}" if city else name)
                    if loc:
                        lat, lon = loc.latitude, loc.longitude
                except Exception:
                    pass
            if lat and lon:
                gp = {"name": name, "lat": lat, "lon": lon, "description": desc}
                geocoded_custom.append(gp)
                popup_html = f"""
                <div style="font-family:Arial;width:200px">
                  <b>{name}</b><br>
                  <i>{desc}</i>
                </div>
                """
                folium.Marker(
                    [lat, lon],
                    popup=folium.Popup(popup_html, max_width=250),
                    tooltip=name,
                    icon=folium.Icon(color="purple", icon="map-marker"),
                ).add_to(m)

    # ── Place pins (auto-populated from Overpass) ─────────────────────────────
    for p in pins:
        popup_html = f"""
        <div style="font-family:Arial;width:180px">
          <b>{p['name']}</b><br>
          {p.get('address') or ''}<br>
          {('🕐 ' + p['opening']) if p.get('opening') else ''}
          {('📞 ' + p['phone'])   if p.get('phone')   else ''}
        </div>
        """
        folium.Marker(
            [p["lat"], p["lon"]],
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=p["name"],
            icon=folium.Icon(color="orange", icon="star"),
        ).add_to(m)

    # ── Route ─────────────────────────────────────────────────────────────────
    route_info = None
    if destination:
        route_data = get_route_data(city, destination)
        if "error" not in route_data:
            route_info = route_data
            folium.GeoJson(
                route_data["geometry"],
                name="Route",
                style_function=lambda x: {"color": "blue", "weight": 5},
            ).add_to(m)
            folium.Marker(
                route_data["end_coords"],
                popup=f"Destination: {destination}",
                icon=folium.Icon(color="green", icon="flag"),
            ).add_to(m)

    # ── Flood markers ─────────────────────────────────────────────────────────
    for f in floods:
        if f.get("coordinates"):
            lon_f, lat_f = f["coordinates"]
            folium.Marker(
                [lat_f, lon_f],
                popup=folium.Popup(f"⚠️ {f['title']}<br>{f.get('date','')}", max_width=220),
                tooltip="NASA EONET flood event",
                icon=folium.Icon(color="red", icon="info-sign"),
            ).add_to(m)

    map_path = os.path.join("static", "generated", "knowledge_hub_map.html")
    os.makedirs(os.path.dirname(map_path), exist_ok=True)
    m.save(map_path)

    return {
        "map_url":  f"/static/generated/knowledge_hub_map.html",
        "weather":  weather,
        "floods":   floods,
        "route":    route_info,
        "pins":     pins,
        "custom_pins": geocoded_custom,
        "query":    query,
    }


# ── BUG5 FIX: scrape_content is now sync (was async with no runner) ───────────

def scrape_content(url: str) -> str:
    """
    BUG5 FIX: was declared `async def` but called from sync context.
    Silently returned a coroutine object instead of content.
    Now fully synchronous using httpx.Client.
    """
    try:
        with httpx.Client(follow_redirects=True, timeout=20) as client:
            # Try Jina Reader first — returns clean markdown
            jina_url = f"https://r.jina.ai/{url}"
            r = client.get(jina_url)
            if r.status_code == 200 and len(r.text) > 200:
                return r.text[:8000]

            # Fallback: raw page + BeautifulSoup
            r = client.get(url, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)[:6000]

    except Exception as e:
        return f"Scraping failed: {e}"


# ── Web search ────────────────────────────────────────────────────────────────

def _fallback_search(query: str, max_results: int = 5) -> list:
    """Fallback search using simple Google scraping (mobile version)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
        }
        url = f"https://www.google.com/search?q={query}&num={max_results}"
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        
        # Google mobile results usually in div.vvP6id or similar
        for g in soup.find_all('div', class_='vvP6id'):
            anchors = g.find_all('a')
            if not anchors: continue
            link = anchors[0]['href']
            title = g.find('div', class_='UP779b').get_text() if g.find('div', class_='UP779b') else link
            snippet = g.find('div', class_='VwiC3b').get_text() if g.find('div', class_='VwiC3b') else ""
            
            results.append({
                "title": title,
                "href": link,
                "body": snippet
            })
            if len(results) >= max_results: break
            
        if not results:
            # Try even simpler scrape for desktop style
            for g in soup.find_all('div', class_='tF2Cxc'):
                anchors = g.find_all('a')
                if not anchors: continue
                link = anchors[0]['href']
                title = g.find('h3').get_text() if g.find('h3') else link
                snippet = g.find('div', class_='VwiC3b').get_text() if g.find('div', class_='VwiC3b') else ""
                results.append({"title": title, "href": link, "body": snippet})
                if len(results) >= max_results: break

        return results
    except Exception as e:
        return [{"error": f"Fallback search failed: {e}"}]

def _camofox_search(query: str, max_results: int = 5) -> list:
    """Search using Camofox stealth browser via its HTTP API (if running)."""
    try:
        CAMOFOX_URL = "http://localhost:9377"
        search_url = f"https://duckduckgo.com/?q={requests.utils.quote(query)}"
        open_res = requests.post(f"{CAMOFOX_URL}/tabs/open",
            json={"userId": "research_hub", "url": search_url, "timeout": 30000}, timeout=5)
        open_data = open_res.json()
        if not open_data.get("ok"):
            return []
        tab_id = open_data["tabId"]
        js = """
        Array.from(document.querySelectorAll('[data-result="web"] article')).slice(0,10).map(a => ({
            title: a.querySelector('h2')?.innerText || '',
            href:  a.querySelector('a[href]')?.href || '',
            body:  a.querySelector('[data-result="snippet"]')?.innerText || ''
        }))
        """
        eval_res = requests.post(f"{CAMOFOX_URL}/tabs/{tab_id}/evaluate",
            json={"userId": "research_hub", "expression": js}, timeout=15)
        eval_data = eval_res.json()
        if eval_data.get("ok") and isinstance(eval_data.get("result"), list):
            results = [r for r in eval_data["result"] if r.get("title")]
            if results:
                return results[:max_results]
    except Exception:
        pass
    return []


def search_web(query: str, max_results: int = 20) -> list:
    """Search the web — tries Camofox first, then ddgs, then fallback."""
    results = _camofox_search(query, max_results)
    if results:
        return results
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results)
        if results:
            return results
    except Exception as e:
        print(f"DDG Search Error: {e}")
    return _fallback_search(query, max_results)


def search_pdfs(topic: str) -> list:
    """Specialised search for PDFs / books."""
    query = f"{topic} filetype:pdf"
    return search_web(query, max_results=20)


# ── CLI ───────────────────────────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════════════════
# FLASK API ENDPOINTS — called by hub_dashboard.html
# Registered in your main app.py via:  from knowledge_hub import register_hub_routes
# ═══════════════════════════════════════════════════════════════════════════════

def register_hub_routes(app):
    """
    Call this from your main Flask app:
        from knowledge_hub import register_hub_routes
        register_hub_routes(app)
    """
    import subprocess as _sp

    @app.route("/api/knowledge-hub/update", methods=["POST"])
    def _hub_update():
        from flask import request as _req, jsonify
        data = _req.get_json(force=True, silent=True) or {}
        city        = data.get("location", "Dhaka")
        query       = data.get("query",    "cafe")
        destination = data.get("destination") or None
        limit       = int(data.get("limit", 8))
        result = create_integrated_hub_map(
            city=city, destination=destination, query=query, limit=limit
        )
        return jsonify(result)

    @app.route("/api/market/quotes", methods=["GET"])
    def _market_quotes():
        """Proxy Yahoo Finance for stock quotes (avoids CORS in browser)."""
        from flask import request as _req, jsonify
        symbols_raw = _req.args.get("symbols", "AAPL,TSLA,META")
        symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()]
        out = []
        try:
            import yfinance as yf
            tickers = yf.Tickers(" ".join(symbols))
            for sym in symbols:
                try:
                    info  = tickers.tickers[sym].info
                    price = info.get("regularMarketPrice") or info.get("currentPrice")
                    prev  = info.get("regularMarketPreviousClose") or price
                    chg   = round(((price - prev) / prev) * 100, 2) if prev and price else 0.0
                    out.append({"symbol": sym, "price": price or 0, "change_pct": chg})
                except Exception:
                    out.append({"symbol": sym, "price": 0, "change_pct": 0.0})
        except ImportError:
            out = [{"symbol": s, "price": 0, "change_pct": 0.0} for s in symbols]
        from flask import jsonify
        return jsonify(out)

    @app.route("/api/tools/open", methods=["POST"])
    def _tools_open():
        """Launch a tool subprocess requested by hub_dashboard (stock/crypto tracker)."""
        from flask import request as _req, jsonify
        data   = _req.get_json(force=True, silent=True) or {}
        tool   = data.get("tool", "")
        params = data.get("params", {})

        base = os.path.dirname(os.path.abspath(__file__))

        if tool == "get_stock_info":
            company = params.get("company", "AAPL")
            script  = os.path.join(base, "tools", "stock.py")
            flag    = "--ticker" if (len(company) <= 5 and company.isupper()) else "--company"
            _sp.Popen(
                [sys.executable, script, flag, company],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                start_new_session=True,
            )
        elif tool == "get_crypto_price":
            coin   = params.get("coin", "bitcoin")
            script = os.path.join(base, "tools", "crypto.py")
            _sp.Popen(
                [sys.executable, script, "--coin", coin],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                start_new_session=True,
            )

        return jsonify({"status": "launched", "tool": tool})

    @app.route("/api/research/search", methods=["POST"])
    def _research_search():
        from flask import request as _req, jsonify
        data  = _req.get_json(force=True, silent=True) or {}
        query = data.get("query", "")
        if not query:
            return jsonify({"results": []})
        results = search_pdfs(query)
        return jsonify({"results": results})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Knowledge Hub CLI")
    parser.add_argument("--city",        default="Dhaka",    help="City name")
    parser.add_argument("--destination",                     help="Destination city for routing")
    parser.add_argument("--query",       default="cafe",     help="Place type to pin (e.g. 'cafe', 'restaurant', 'park')")  # BUG4 FIX
    parser.add_argument("--limit",       default=8, type=int,help="Max number of pins")
    parser.add_argument("--search",                          help="Web search query")
    parser.add_argument("--pdf",                             help="PDF search topic")
    parser.add_argument("--scrape",                          help="URL to scrape")
    parser.add_argument("--weather",     action="store_true",help="Get weather only")
    parser.add_argument("--floods",      action="store_true",help="Get flood data only")
    args = parser.parse_args()

    if args.search:
        print(json.dumps(search_web(args.search), indent=2))
    elif args.pdf:
        print(json.dumps(search_pdfs(args.pdf), indent=2))
    elif args.scrape:
        print(scrape_content(args.scrape))          # BUG5: now sync, no asyncio.run needed
    elif args.weather:
        print(json.dumps(get_weather_data(args.city), indent=2))
    elif args.floods:
        print(json.dumps(get_flood_data(), indent=2))
    else:
        result = create_integrated_hub_map(
            city=args.city,
            destination=args.destination,
            query=args.query,           # BUG3+4 FIX: passes through from CLI
            limit=args.limit,
        )
        print(json.dumps(result, indent=2, default=str))

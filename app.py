import io
import json
import pandas as pd
import streamlit as st

from scrapers import SCRAPERS
from scrapers.dedup import merge_results, filter_relevant
from enrich import enrich_all
from areas import get_areas
from grid import grid_points

st.set_page_config(page_title="Business Data Scraper", page_icon="🔎", layout="wide")
st.title("🔎 Business Data Scraper")
st.caption("Search businesses by keyword + location, export to CSV / Excel.")

SOURCES = ["All Sources", "Google Maps", "Bing Maps", "OpenStreetMap", "Hotfrog", "Yellow Pages"]
MERGE_SOURCES = ["Google Maps", "Bing Maps", "OpenStreetMap", "Hotfrog"]
GRID_SOURCES = {"Google Maps", "Bing Maps"}
MANUAL = "✏️ Type manually..."


@st.cache_data
def load_cities():
    with open("data/cities.json", encoding="utf-8") as f:
        return json.load(f)


@st.cache_data(ttl=3600)
def cached_areas(city: str, country: str):
    return get_areas(city, country)


CITIES = load_cities()
COUNTRIES = sorted(CITIES.keys())

c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
with c1:
    keyword = st.text_input("Keyword / Business type", placeholder="e.g. gym, restaurant, dentist")
with c2:
    country = st.selectbox("Country", COUNTRIES, index=COUNTRIES.index("United Kingdom"))
with c3:
    city_opts = [MANUAL] + CITIES.get(country, [])
    city_sel = st.selectbox("City", city_opts)
with c4:
    source = st.selectbox("Source", SOURCES)

city_for_areas = city_sel if city_sel != MANUAL else ""
c5, c6, c7 = st.columns([2, 1, 2])
with c5:
    city_manual = ""
    if city_sel == MANUAL:
        city_manual = st.text_input("City name")
        city_for_areas = city_manual.strip()
with c6:
    limit = st.slider("Max results", 10, 500, 50, step=10)
with c7:
    enrich = st.checkbox(
        "Fetch emails & social links from each website (slower but richer data)",
        value=True,
    )
    details_all = st.checkbox(
        "📞 Get phone/website for EVERY business (Google Maps detail pages — ~2s each)",
        value=True,
    )
    deep = st.checkbox(
        "🗺️ Deep sweep — search the whole city via grid (10-20x more results, slower)",
        value=False,
    )

areas_sel = []
if city_for_areas:
    try:
        area_opts = cached_areas(city_for_areas, country)
    except Exception:
        area_opts = []
    if not area_opts:
        # don't remember empty/failed lookups — transient API failures
        # would otherwise hide the dropdown for the cache TTL
        cached_areas.clear(city_for_areas, country)
    if area_opts:
        areas_sel = st.multiselect(
            "Areas / Districts (optional — empty = whole city)",
            area_opts,
            help="Select areas to search each one separately for more results",
        )

submitted = st.button("🚀 Scrape", use_container_width=True)

if submitted:
    city = city_manual.strip() if city_sel == MANUAL else city_sel
    if not keyword.strip():
        st.error("Keyword required — e.g. 'gym'")
    elif not city:
        st.error("City required — select from list or type manually")
    else:
        locations = [f"{a} {city}" for a in areas_sel] if areas_sel else [city]

        grid_pts = []
        if deep and not areas_sel:
            with st.spinner("Building city grid..."):
                cells = min(64, max(9, limit // 8))
                grid_pts = grid_points(city, country, max_cells=cells)

        dbar = st.progress(0, text="") if (details_all and "Google Maps" in
                                         ([source] if source != "All Sources" else MERGE_SOURCES)) else None

        def scrape_one(src_name, loc, bar=None):
            scraper = SCRAPERS[src_name]()
            kwargs = {}
            if grid_pts and src_name in GRID_SOURCES:
                cb = (lambda d, t: bar.progress(
                    d / max(t, 1), text=f"{src_name} grid… {d}/{t}")) if bar else None
                kwargs.update(points=grid_pts, progress_cb=cb)
            if src_name == "Google Maps":
                kwargs.update(
                    detail_limit=limit if details_all else 25,
                    detail_cb=(lambda d, t: dbar.progress(
                        d / max(t, 1), text=f"Phone/website… {d}/{t}")) if dbar else None,
                )
            res = scraper.search(keyword.strip(), loc, country, limit, **kwargs)
            failed = getattr(scraper, "cells_failed", 0)
            total = getattr(scraper, "cells_total", 0)
            if total and failed / total > 0.4:
                st.warning(
                    f"{src_name} ({loc}): Google blocked {failed}/{total} searches "
                    "— datacenter IPs get rate-limited. Try OpenStreetMap / Hotfrog "
                    "/ All Sources for fuller coverage."
                )
            return res

        result_lists = []
        for loc in locations:
            if source == "All Sources":
                for src_name in MERGE_SOURCES:
                    try:
                        bar = st.progress(0, text=f"{src_name}…") if grid_pts and src_name in GRID_SOURCES else None
                        with st.spinner(f"Searching {src_name} — {loc}..."):
                            result_lists.append(scrape_one(src_name, loc, bar))
                        if bar:
                            bar.empty()
                    except Exception as e:
                        st.warning(f"{src_name} ({loc}) failed: {e}")
            else:
                try:
                    bar = st.progress(0, text=f"{source}…") if grid_pts and source in GRID_SOURCES else None
                    with st.spinner(f"Searching {source} — {loc}..."):
                        result_lists.append(scrape_one(source, loc, bar))
                    if bar:
                        bar.empty()
                except NotImplementedError as e:
                    st.warning(str(e))
                    st.stop()
                except Exception as e:
                    st.error(f"Scraping failed for {loc}: {e}")
        if dbar:
            dbar.empty()
        results = filter_relevant(merge_results(*result_lists), keyword.strip())[:limit]

        if not results:
            st.warning("No results found. Try a different keyword or source.")
            st.stop()

        if enrich:
            bar = st.progress(0, text="Fetching websites for emails & socials...")
            enrich_all(results, progress_cb=lambda d, t: bar.progress(
                d / max(t, 1), text=f"Fetching websites… {d}/{t}"))
            bar.empty()

        df = pd.DataFrame([b.to_dict() for b in results])
        df = df[["name", "category", "address", "phone", "email", "website",
                 "rating", "reviews", "social_media", "source", "maps_url",
                 "keyword", "city", "country"]]
        df.columns = ["Name", "Category", "Address", "Phone", "Email", "Website",
                      "Rating", "Reviews", "Social Media", "Source",
                      "Listing URL", "Keyword", "City", "Country"]
        st.session_state["df"] = df

if "df" in st.session_state:
    df = st.session_state["df"]

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Businesses", len(df))
    m2.metric("With Website", int(df["Website"].astype(bool).sum()))
    m3.metric("With Phone", int(df["Phone"].astype(bool).sum()))
    m4.metric("With Email", int(df["Email"].astype(bool).sum()))
    m5.metric("Avg Rating", f"{df['Rating'].dropna().mean():.1f} ★"
              if df["Rating"].notna().any() else "—")
    st.divider()

    st.dataframe(
        df,
        use_container_width=True,
        height=480,
        column_config={
            "Website": st.column_config.LinkColumn("Website", display_text="Visit"),
            "Listing URL": st.column_config.LinkColumn("Listing URL", display_text="Open"),
            "Rating": st.column_config.NumberColumn("Rating", format="%.1f ★"),
            "Name": st.column_config.TextColumn("Name", width="medium"),
        },
    )

    d1, d2 = st.columns(2)
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    d1.download_button("⬇️ Download CSV", csv_bytes, "businesses.csv", "text/csv")

    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    d2.download_button("⬇️ Download Excel", buf.getvalue(), "businesses.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

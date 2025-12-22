import streamlit as st
import pandas as pd
import base64, os, requests, subprocess, time, random
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote_plus
from PIL import Image
from playwright.sync_api import sync_playwright
from openai import OpenAI

# --- 1. INITIALIZATION ---
def get_watchlist():
    if "items" not in st.session_state:
        st.session_state["items"] = []
    return st.session_state["items"]

if "next_start" not in st.session_state:
    st.session_state["next_start"] = 1

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

def install_playwright_browsers():
    if not st.session_state.get("browser_installed", False):
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception: pass

# --- 2. API CLIENTS & SEARCH ---
SAPI_KEY = st.secrets.get("SCRAPERAPI_KEY") 
client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY"))

def get_store_name(url):
    try: return urlparse(url).netloc.replace("www.", "")
    except: return "Store"

def google_search_paginated(query, start_index=1, worldwide=False, blacklist=[]):
    api_key = st.secrets.get("GOOGLE_API_KEY")
    cx = st.secrets.get("GOOGLE_CX")
    if not api_key or not cx: return []
    all_links = []
    base_url = f"https://www.googleapis.com/customsearch/v1?key={api_key}&cx={cx}&q={query}&start={start_index}"
    if not worldwide: base_url += "&cr=countryAU"
    try:
        response = requests.get(base_url, timeout=10)
        items = response.json().get("items", [])
        for item in items:
            link = item['link']
            domain = get_store_name(link)
            if not any(b.strip().lower() in domain.lower() for b in blacklist if b.strip()):
                all_links.append(link)
    except: pass
    return all_links

# --- 3. DEEP SCAN LOGIC ---
def analyze_with_vision(image_path, product_name):
    try:
        with Image.open(image_path) as img:
            img.thumbnail((800, 800)) 
            temp_path = f"v_{os.getpid()}.jpg"
            img.save(temp_path, "JPEG", quality=60)
        with open(temp_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [{"type": "text", "text": f"Price for {product_name}? Numeric only."}, 
                      {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}]}],
            max_tokens=50
        )
        if os.path.exists(temp_path): os.remove(temp_path)
        return response.choices[0].message.content.strip()
    except: return "AI Error"

def run_browser_watch(url, product_name):
    proxy_url = f"http://api.scraperapi.com?api_key={SAPI_KEY}&url={quote_plus(url)}&render=true&country_code=au"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(proxy_url, timeout=95000, wait_until="networkidle")
            time.sleep(5) 
            path = f"snap_{os.getpid()}.png"
            page.screenshot(path=path)
            price = analyze_with_vision(path, product_name)
            
            with Image.open(path) as img:
                thumb_path = f"t_{os.getpid()}.png"
                img.crop((img.size[0]/4, 50, 3*img.size[0]/4, 450)).save(thumb_path)
            
            with open(thumb_path, "rb") as f:
                img_b64 = f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
            
            for f in [path, thumb_path]: 
                if os.path.exists(f): os.remove(f)
            return price, img_b64
        except: return "Timeout", None
        finally: browser.close()

# --- 4. UI SETUP ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")
if not st.session_state.get("browser_installed"): install_playwright_browsers()

st.title("🛒 AI Price Watcher")

with st.sidebar:
    st.header("Search Settings")
    with st.form("search_form"):
        bulk_input = st.text_input("Product Search")
        exclude_domains = st.text_input("Exclude Domains")
        is_worldwide = st.checkbox("Worldwide Search")
        st.divider()
        m_sku = st.text_input("Manual Name")
        m_url = st.text_input("Manual Target URL")
        submit_button = st.form_submit_button("Search & Add to List")

    if submit_button:
        watchlist = get_watchlist()
        if m_sku and m_url:
            watchlist.append({"sku": m_sku, "url": m_url, "price": "Pending", "last_updated": "Never", "img_url": None})
        if bulk_input:
            st.session_state["last_query"] = bulk_input
            blacklist = [b.strip() for b in exclude_domains.split(",") if b.strip()]
            for page_start in [1, 11]:
                links = google_search_paginated(bulk_input, start_index=page_start, worldwide=is_worldwide, blacklist=blacklist)
                for l in links:
                    if not any(item['url'] == l for item in watchlist):
                        watchlist.append({"sku": bulk_input, "url": l, "price": "Pending", "last_updated": "Never", "img_url": None})
            st.session_state["next_start"] = 21
        st.session_state["items"] = watchlist
        st.rerun()

    if "last_query" in st.session_state and len(st.session_state.get("items", [])) > 0:
        if st.button("🔍 Load 20 More Stores", use_container_width=True):
            query = st.session_state["last_query"]
            current_start = st.session_state["next_start"]
            with st.spinner("Fetching more..."):
                for page_start in [current_start, current_start + 10]:
                    links = google_search_paginated(query, start_index=page_start, worldwide=is_worldwide)
                    for l in links:
                        if not any(item['url'] == l for item in st.session_state["items"]):
                            st.session_state["items"].append({"sku": query, "url": l, "price": "Pending", "last_updated": "Never", "img_url": None})
            st.session_state["next_start"] += 20
            st.rerun()

    if st.button("🗑️ Clear All Records", use_container_width=True):
        st.session_state["items"] = []
        st.session_state.pop("last_query", None)
        st.rerun()

# --- 5. RESULTS TABLE ---
watchlist = get_watchlist()
if watchlist:
    df = pd.DataFrame(watchlist)
    df.insert(0, "Seq", range(1, len(df) + 1))
    
    st.metric("Total Stores", len(df))
    
    selection_event = st.dataframe(
        df[["Seq", "img_url", "sku", "price", "last_updated", "url"]],
        use_container_width=True, hide_index=True, on_select="rerun", selection_mode="multi-row",
        column_config={
            "Seq": st.column_config.NumberColumn("Seq", width=30),
            "img_url": st.column_config.ImageColumn("Product", width="small"),
            "url": st.column_config.LinkColumn("Store Link")
        }
    )
    
    selected_indices = selection_event.selection.rows

    # --- RESTORED DEEP SCAN ACTION ---
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("🚀 Run Deep Scan on Selected", use_container_width=True):
            if selected_indices:
                status = st.empty()
                progress = st.progress(0)
                for i, idx in enumerate(selected_indices):
                    item = st.session_state["items"][idx]
                    status.info(f"Scanning {i+1}/{len(selected_indices)}: {get_store_name(item['url'])}")
                    p, img = run_browser_watch(item['url'], item['sku'])
                    aedt = (datetime.utcnow() + timedelta(hours=11)).strftime("%H:%M")
                    st.session_state["items"][idx].update({"price": p, "img_url": img, "last_updated": aedt})
                    progress.progress((i + 1) / len(selected_indices))
                st.rerun()
    with c2:
        if selected_indices:
            csv = df.iloc[selected_indices].to_csv(index=False).encode('utf-8')
            st.download_button("📥 Export CSV", data=csv, file_name="prices.csv", use_container_width=True)
    with c3:
        if st.button("❌ Remove Selected", use_container_width=True):
            st.session_state["items"] = [item for j, item in enumerate(st.session_state["items"]) if j not in selected_indices]
            st.rerun()
else:
    st.info("Watchlist empty. Search in sidebar.")

import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import time
import random
from datetime import datetime
from PIL import Image
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. SESSION & BROWSER ---
def get_watchlist():
    if "items" not in st.session_state or st.session_state["items"] is None:
        st.session_state["items"] = []
    return st.session_state["items"]

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

def install_playwright_browsers():
    if not st.session_state.get("browser_installed", False):
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception as e:
            st.error(f"Browser installation failed: {e}")

# --- 2. API CLIENTS ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")
client = OpenAI(api_key=OPENAI_KEY)

# --- 3. CORE LOGIC ---
def google_search_deep(query, worldwide=False, num_pages=1):
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        st.error("Google API Keys missing!")
        return []
    all_links = []
    for i in range(num_pages):
        start_index = (i * 10) + 1
        base_url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}&start={start_index}"
        if not worldwide: 
            base_url += "&cr=countryAU"
        try:
            response = requests.get(base_url, timeout=10)
            items = response.json().get("items", [])
            all_links.extend([item['link'] for item in items if "facebook" not in item['link']])
        except: 
            break
    return list(dict.fromkeys(all_links))

def analyze_with_vision(image_path, product_name):
    try:
        with Image.open(image_path) as img:
            img.thumbnail((1000, 1000)) 
            compressed_path = "small_" + image_path
            img.save(compressed_path, "JPEG", quality=70)
        
        with open(compressed_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extract the current price for {product_name} from this screenshot. Return ONLY the numeric price. If unavailable, return 'N/A'."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        if os.path.exists(compressed_path): os.remove(compressed_path)
        return response.choices[0].message.content.strip()
    except Exception as e:
        if "429" in str(e): return "Rate Limited"
        return "AI Error"

def run_browser_watch(url, product_name):
    """Enhanced version to bypass Timeouts and Bot Blocks."""
    with sync_playwright() as p:
        # Using a more standard browser launch
        browser = p.chromium.launch(headless=True)
        # Randomizing the User-Agent to look like a real Windows Chrome user
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        try:
            stealth(page)
            # Use 'load' instead of 'networkidle' to prevent hanging on tracker scripts
            page.goto(url, wait_until="load", timeout=60000)
            
            # Simulate a human scroll to trigger lazy-loaded prices
            page.mouse.wheel(0, 500)
            time.sleep(random.uniform(2, 4))
            
            img_path = f"snap_{os.getpid()}.png"
            # Full page screenshot increases chances of catching the price
            page.screenshot(path=img_path, full_page=True)
            
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except Exception as e:
            return "Timeout/Block"
        finally:
            browser.close()

# --- 4. UI LAYOUT ---
st.set_page_config(page_title="Price Watch AI", layout="wide")
if not st.session_state.get("browser_installed"):
    install_playwright_browsers()

st.title("🛒 AI Price Watcher (Anti-Block Mode)")

with st.sidebar:
    st.header("Search Parameters")
    sku_input = st.text_input("Product Name / SKU", key="sku_entry")
    is_worldwide = st.checkbox("Search Worldwide?", value=False)
    depth = st.slider("Pages to search", 1, 3, 1)
    
    if st.button("Find Resellers"):
        if sku_input:
            with st.spinner("Finding stores..."):
                links = google_search_deep(sku_input, is_worldwide, depth)
                watchlist = get_watchlist()
                for l in links:
                    if not any(item['url'] == l for item in watchlist):
                        watchlist.append({
                            "sku": sku_input, 
                            "url": l, 
                            "price": "Pending", 
                            "last_updated": "Never"
                        })
                st.session_state["items"] = watchlist
                st.rerun()

    if st.button("🗑️ Clear All"):
        st.session_state["items"] = []
        st.rerun()

# --- 5. RESULTS ---
watchlist = get_watchlist()
if watchlist:
    st.subheader(f"Watchlist ({len(watchlist)} sellers)")
    df = pd.DataFrame(watchlist)
    display_cols = [c for c in ["sku", "price", "last_updated", "url"] if c in df.columns]
    st.dataframe(df[display_cols], use_container_width=True)
    
    if st.button("🚀 Start Scanning Prices"):
        status_box = st.empty()
        bar = st.progress(0)
        
        for i, item in enumerate(watchlist):
            status_box.info(f"Scanning {i+1}/{len(watchlist)}: {item['url'][:50]}...")
            found_price = run_browser_watch(item['url'], item['sku'])
            
            st.session_state["items"][i]["price"] = found_price
            st.session_state["items"][i]["last_updated"] = datetime.now().strftime("%H:%M")
            bar.progress((i + 1) / len(watchlist))
            
            if i < len(watchlist) - 1:
                status_box.warning("API Cooldown: Waiting 8s...")
                time.sleep(8)
        
        status_box.success("✅ Scan Complete!")
        st.rerun()
else:
    st.info("Sidebar: Search for a product to begin.")

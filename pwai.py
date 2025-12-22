import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
import sys
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. ROBUST SESSION INITIALIZATION ---
def get_watchlist():
    if "items" not in st.session_state or st.session_state["items"] is None:
        st.session_state["items"] = []
    return st.session_state["items"]

if "browser_installed" not in st.session_state:
    st.session_state["browser_installed"] = False

# --- 2. CLOUD INSTALLER ---
def install_playwright_browsers():
    if not st.session_state.get("browser_installed", False):
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            st.session_state["browser_installed"] = True
        except Exception as e:
            st.error(f"Browser installation failed: {e}")

# --- 3. API CLIENTS ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
GOOGLE_API_KEY = st.secrets.get("GOOGLE_API_KEY")
GOOGLE_CX = st.secrets.get("GOOGLE_CX")
client = OpenAI(api_key=OPENAI_KEY)

# --- 4. CORE FUNCTIONS ---
def google_search_api(query):
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return []
    url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    try:
        response = requests.get(url, timeout=10)
        items = response.json().get("items", [])
        return [item['link'] for item in items[:3]]
    except:
        return []

def analyze_with_vision(image_path, product_name):
    try:
        with open(image_path, "rb") as f:
            base64_img = base64.b64encode(f.read()).decode('utf-8')
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Find the price for {product_name}. Return ONLY the number (e.g. 150.00). If not found, return 'N/A'."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

def run_browser_watch(url, product_name):
    """Refreshed version to fix Stealth TypeError."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # 1. Create the context
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # 2. Apply stealth to the context (New 2025 standard)
        # If stealth(page) failed, stealth(context) or using it correctly on page is needed.
        page = context.new_page()
        
        try:
            # Re-attempting stealth on the page with proper error handling
            try:
                stealth(page)
            except Exception:
                pass # Fallback if stealth library version is mismatched
                
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            # Internal Search Fallback
            search_box = page.locator('input[type="search"], input[name="q"]').first
            if search_box.is_visible(timeout=5000):
                search_box.fill(product_name)
                search_box.press("Enter")
                page.wait_for_timeout(4000)
            
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path, full_page=False)
            price = analyze_with_vision(img_path, product_name)
            
            if os.path.exists(img_path):
                os.remove(img_path)
            return price
        except Exception as e:
            return f"Scan Failed: {str(e)}"
        finally:
            browser.close()

# --- 5. UI LAYOUT ---
st.set_page_config(page_title="Price Watcher v2.3", layout="wide")

if not st.session_state.get("browser_installed"):
    install_playwright_browsers()

st.title("🛒 AI Price Comparison Tool")

with st.sidebar:
    st.header("Add New Product")
    sku_val = st.text_input("SKU / Keywords", key="sku_input")
    url_val = st.text_input("Store URL (Optional)", key="url_input")
    
    if st.button("Add to Watchlist"):
        if sku_val:
            items = get_watchlist()
            with st.spinner("Fetching links..."):
                found_links = [url_val] if url_val else google_search_api(sku_val)
                if found_links:
                    for link in found_links:
                        items.append({"sku": sku_val, "url": link})
                    st.session_state["items"] = items
                    st.rerun()
                else:
                    st.error("No links found.")
        else:
            st.warning("Enter a SKU.")

    if st.button("🗑️ Clear List"):
        st.session_state["items"] = []
        st.rerun()

# --- 6. DISPLAY & ANALYSIS ---
watchlist = get_watchlist()

if len(watchlist) > 0:
    st.subheader("Your Watchlist")
    
    if st.button("🚀 Run Price Comparison Analysis"):
        results = []
        progress = st.progress(0)
        
        for i, item in enumerate(watchlist):
            with st.status(f"Scanning {item.get('sku')}...") as status:
                # FIX: Access dictionary keys safely
                p_url = item.get('url')
                p_sku = item.get('sku')
                
                price = run_browser_watch(p_url, p_sku)
                results.append({
                    "Product": p_sku,
                    "Price": price,
                    "Source": p_url
                })
                progress.progress((i + 1) / len(watchlist))
                status.update(label=f"Done: {p_sku}", state="complete")
        
        st.divider()
        st.subheader("Results Table")
        st.dataframe(pd.DataFrame(results), use_container_width=True)
    else:
        st.table(pd.DataFrame(watchlist))
else:
    st.info("Sidebar: Add a product to begin.")

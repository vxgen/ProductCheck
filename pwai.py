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
    """Helper to ensure we always have a valid list, never None."""
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
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0")
        page = context.new_page()
        stealth(page) 
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            search_box = page.locator('input[type="search"], input[name="q"]').first
            if search_box.is_visible():
                search_box.fill(product_name)
                search_box.press("Enter")
                page.wait_for_timeout(4000)
            img_path = f"snap_{os.getpid()}.png"
            page.screenshot(path=img_path)
            price = analyze_with_vision(img_path, product_name)
            if os.path.exists(img_path): os.remove(img_path)
            return price
        except:
            return "Scan Failed"
        finally:
            browser.close()

# --- 5. UI LAYOUT ---
st.set_page_config(page_title="Price Watcher v2.2", layout="wide")

# Run browser install once per session
if not st.session_state.get("browser_installed"):
    install_playwright_browsers()

st.title("🛒 AI Price Comparison Tool")

# Sidebar Logic
with st.sidebar:
    st.header("Add New Product")
    sku_val = st.text_input("SKU / Keywords", key="sku_input_field")
    url_val = st.text_input("Store URL (Optional)", key="url_input_field")
    
    if st.button("Add to Watchlist"):
        if sku_val:
            items = get_watchlist() # Ensure list exists
            with st.spinner("Fetching links..."):
                found_links = [url_val] if url_val else google_search_api(sku_val)
                if found_links:
                    for link in found_links:
                        items.append({"sku": sku_val, "url": link})
                    st.session_state["items"] = items # Re-save to state
                    st.rerun()
                else:
                    st.error("No links found.")
        else:
            st.warning("Enter a SKU.")

    if st.button("🗑️ Clear List"):
        st.session_state["items"] = []
        st.rerun()

# --- 6. DISPLAY & ANALYSIS ---
watchlist = get_watchlist() # Always use the getter

if len(watchlist) > 0:
    st.subheader("Your Watchlist")
    
    if st.button("🚀 Run Price Comparison Analysis"):
        results = []
        progress = st.progress(0)
        
        for i, item in enumerate(watchlist):
            with st.status(f"Scanning {item.get('sku')}...") as status:
                price = run_browser_watch(item.get('url'), item.get('sku'))
                results.append({
                    "Product": item.get('sku'),
                    "Price": price,
                    "Source": item.get('url')
                })
                progress.progress((i + 1) / len(watchlist))
                status.update(label="Complete!", state="complete")
        
        st.divider()
        st.subheader("Results Table")
        st.dataframe(pd.DataFrame(results), use_container_width=True)
    else:
        # Simple table display of the current list
        st.table(pd.DataFrame(watchlist))
else:
    st.info("Sidebar: Add a product to begin.")

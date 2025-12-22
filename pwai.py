import streamlit as st
import pandas as pd
import base64
import os
import requests
import subprocess
from datetime import datetime
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth
from openai import OpenAI

# --- 1. ROBUST SESSION INITIALIZATION ---
def get_watchlist():
    if "items" not in st.session_state or st.session_state["items"] is None:
        st.session_state["items"] = []
    
    # Ensure every item has 'price' and 'last_updated' keys
    for item in st.session_state["items"]:
        if "price" not in item:
            item["price"] = "Pending"
        if "last_updated" not in item:
            item["last_updated"] = "Never"
            
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
def google_search_api(query, worldwide=False):
    if not GOOGLE_API_KEY or not GOOGLE_CX:
        return []
    
    base_url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_CX}&q={query}"
    if not worldwide:
        base_url += "&cr=countryAU"
    
    try:
        response = requests.get(base_url, timeout=10)
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
                    {"type": "text", "text": f"Find the price for {product_name}. Return ONLY the number. If not found, return 'N/A'."},
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
        try:
            try:
                stealth(page)
            except:
                pass
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
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
st.set_page_config(page_title="AU Price Watcher", layout="wide")
if not st.session_state.get("browser_installed"):
    install_playwright_browsers()

st.title("🛒 AI Price Watcher (AU Priority)")

with st.sidebar:
    st.header("Search Settings")
    sku_val = st.text_input("SKU / Keywords", key="sku_input")
    is_worldwide = st.checkbox("Search Worldwide?", value=False)
    
    if st.button("Add to Watchlist"):
        if sku_val:
            items = get_watchlist()
            with st.spinner(f"Searching..."):
                found_links = google_search_api(sku_val, worldwide=is_worldwide)
                
                if found_links:
                    for link in found_links:
                        items.append({
                            "sku": sku_val, 
                            "url": link, 
                            "price": "Pending", 
                            "last_updated": "Never"
                        })
                    st.session_state["items"] = items
                    st.rerun()
                else:
                    if not is_worldwide:
                        st.warning("No AU links found.")
                        if st.button("Retry Search Worldwide?"):
                            # This button appears if AU search fails
                            st.session_state["worldwide_retry"] = True
                    else:
                        st.error("No links found anywhere.")
        else:
            st.warning("Enter a SKU.")

    if st.button("🗑️ Clear List"):
        st.session_state["items"] = []
        st.rerun()

# --- 6. DISPLAY & ANALYSIS ---
watchlist = get_watchlist()

if len(watchlist) > 0:
    st.subheader("Your Watchlist")
    df_preview = pd.DataFrame(watchlist)
    
    # Display table with Timestamp
    cols = [c for c in ["sku", "price", "last_updated", "url"] if c in df_preview.columns]
    st.table(df_preview[cols])
    
    if st.button("🚀 Start Scanning Prices"):
        progress = st.progress(0)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        for i, item in enumerate(watchlist):
            with st.status(f"Scanning {item.get('sku')}...") as status:
                price = run_browser_watch(item.get('url'), item.get('sku'))
                
                # Update data and timestamp
                st.session_state["items"][i]["price"] = price
                st.session_state["items"][i]["last_updated"] = timestamp
                
                progress.progress((i + 1) / len(watchlist))
                status.update(label=f"Done: {item.get('sku')}", state="complete")
        
        st.success(f"Updated at {timestamp}")
        st.rerun()
else:
    st.info("Sidebar: Add a product to begin.")

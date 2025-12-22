import streamlit as st
import pandas as pd
import base64
import os
import re
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
from openai import OpenAI

# Initialize OpenAI Client
# Ensure you have your OPENAI_API_KEY set in your environment variables
client = OpenAI(api_key=st.secrets.get("OPENAI_API_KEY") or "your-key-here")

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def analyze_price_with_vision(screenshot_path, product_name):
    """Requirement #5: Use Vision LLM to extract price from screenshot."""
    base64_image = encode_image(screenshot_path)
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Find the current sale price for '{product_name}' in this image. Return only the price (e.g., $99.99). If not found, return 'N/A'."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ],
            }
        ],
        max_tokens=50
    )
    return response.choices[0].message.content

def get_screenshot_and_price(url, product_name=None, search_mode=False):
    """Requirement #5 & #6: Browser automation with Vision Fallback."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()
        stealth_sync(page)
        
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
            
            # Requirement #6: Site-specific search if blocked or incorrect page
            if search_mode and product_name:
                # Try to find common search selectors
                search_selectors = ['input[name="q"]', 'input[type="search"]', 'input[placeholder*="Search"]']
                for selector in search_selectors:
                    if page.locator(selector).count() > 0:
                        page.fill(selector, product_name)
                        page.press(selector, "Enter")
                        page.wait_for_load_state("networkidle")
                        break

            screenshot_path = f"capture_{os.getpid()}.png"
            page.screenshot(path=screenshot_path, full_page=False)
            
            # Use Vision Analysis
            price = analyze_price_with_vision(screenshot_path, product_name)
            
            if os.path.exists(screenshot_path):
                os.remove(screenshot_path)
                
            return price, page.url
        except Exception as e:
            return f"Error: {str(e)}", url
        finally:
            browser.close()

# --- STREAMLIT DASHBOARD ---
st.set_page_config(page_title="AI Price Watcher", layout="wide")
st.title("👁️ AI Vision Price Watcher")



with st.sidebar:
    st.header("Add Product")
    sku = st.text_input("SKU / Keywords")
    target_url = st.text_input("Store URL (Optional)")
    if st.button("Add to Watchlist"):
        if "watchlist" not in st.session_state:
            st.session_state.watchlist = []
        # If no URL, we'd normally call a search function here
        st.session_state.watchlist.append({"name": sku, "url": target_url})

if "watchlist" in st.session_state:
    if st.button("🚀 Run Price Comparison"):
        results = []
        for item in st.session_state.watchlist:
            with st.spinner(f"Analyzing {item['name']}..."):
                price, final_url = get_screenshot_and_price(item['url'], item['name'], search_mode=True)
                results.append({"Product": item['name'], "Price": price, "URL": final_url})
        
        # Requirement #4: Comparison Table
        st.table(pd.DataFrame(results))
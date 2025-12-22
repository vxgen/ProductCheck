import streamlit as st
import pandas as pd
import gspread
import hashlib
import os, base64, requests, subprocess, time, random
from google.oauth2 import service_account
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote_plus
from PIL import Image
from playwright.sync_api import sync_playwright
from openai import OpenAI

# --- 1. USER AUTHENTICATION LOGIC ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    # Credentials must be added to Streamlit Secrets
    creds = service_account.Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
    return gspread.authorize(creds)

def load_user_db():
    try:
        client = get_gspread_client()
        # Using your specific spreadsheet name
        sheet = client.open("usersforpw").worksheet("users")
        df = pd.DataFrame(sheet.get_all_records())
        return sheet, df
    except Exception as e:
        st.error(f"Database Error: {e}")
        return None, pd.DataFrame()

def check_login(username, password):
    _, df = load_user_db()
    if df.empty: return False, "Database connection failed."
    
    user_row = df[df['username'] == username]
    if not user_row.empty:
        stored_pw = user_row.iloc[0]['password']
        # Check if Admin has set is_active to TRUE
        is_active = str(user_row.iloc[0]['is_active']).strip().upper() == "TRUE"
        
        if stored_pw == hash_password(password):
            if is_active:
                return True, "Success"
            else:
                return False, "Account pending manual approval by Admin."
    return False, "Invalid username or password."

def register_user(username, password):
    sheet, df = load_user_db()
    if username in df['username'].values:
        return False, "Username already exists."
    
    # Defaults is_active to FALSE for your manual approval
    sheet.append_row([username, hash_password(password), "FALSE"])
    return True, "Registered! Please wait for Admin approval."

# --- 2. SESSION STATE & LOGIN UI ---
st.set_page_config(page_title="Price Watch Pro", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not st.session_state["logged_in"]:
    st.title("🔒 Access Restricted")
    tab1, tab2 = st.tabs(["Login", "Request Access"])
    
    with tab1:
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                success, msg = check_login(u, p)
                if success:
                    st.session_state["logged_in"] = True
                    st.session_state["user"] = u
                    st.rerun()
                else:
                    st.error(msg)
                    
    with tab2:
        with st.form("register"):
            new_u = st.text_input("Choose Username")
            new_p = st.text_input("Choose Password", type="password")
            if st.form_submit_button("Register", use_container_width=True):
                if new_u and new_p:
                    ok, m = register_user(new_u, new_p)
                    if ok: st.success(m)
                    else: st.error(m)
    st.stop() # Prevents tool from loading until login is successful

# --- 3. MAIN APP (ONLY LOADS IF LOGGED IN) ---
st.sidebar.success(f"User: {st.session_state['user']}")
if st.sidebar.button("Logout"):
    st.session_state["logged_in"] = False
    st.rerun()

# ... (Paste the rest of the Price Watcher code from v8.3 here) ...

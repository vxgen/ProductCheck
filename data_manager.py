import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime
import time
import json 

# --- CONNECT (CACHED) ---
@st.cache_resource
def get_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_sheet():
    client = get_client()
    url = "https://docs.google.com/spreadsheets/d/1KG8qWTYLa6GEWByYIg2vz3bHrGdW3gvqD_detwhyj7k/edit"
    return client.open_by_url(url)

# --- READ FUNCTIONS ---

@st.cache_data(ttl=60)
def get_users():
    try:
        ws = get_sheet().worksheet("users")
        return pd.DataFrame(ws.get_all_records())
    except:
        return pd.DataFrame(columns=["username", "password", "email", "status", "role"])

@st.cache_data(ttl=60)
def get_categories():
    try:
        ws = get_sheet().worksheet("categories")
        records = ws.get_all_records()
        if not records: return []
        return [r['category_name'] for r in records if 'category_name' in r and r['category_name']]
    except:
        return []

@st.cache_data(ttl=60)
def get_all_products_df():
    sh = get_sheet()
    cats = get_categories()
    all_dfs = []
    for cat in cats:
        try:
            ws = sh.worksheet(cat)
            data = ws.get_all_values()
            if data and len(data) > 1:
                cat_df = pd.DataFrame(data[1:], columns=data[0])
                cat_df['category'] = cat 
                all_dfs.append(cat_df)
        except: continue
    return pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

@st.cache_data(ttl=10)
def get_quotes():
    try:
        ws = get_sheet().worksheet("quotes")
        records = ws.get_all_records()
        return pd.DataFrame(records) if records else pd.DataFrame()
    except:
        return pd.DataFrame()

# --- WRITE FUNCTIONS ---

def log_action(user, action, details):
    try:
        ws = get_sheet().worksheet("logs")
        ws.append_row([str(datetime.now()), user, action, details])
    except: pass 

def ensure_category_sheet_exists(category_name):
    sh = get_sheet()
    try: return sh.worksheet(category_name)
    except: return sh.add_worksheet(title=category_name, rows=1000, cols=26)

def add_category(name, user):
    try: ws = get_sheet().worksheet("categories")
    except:
        sh = get_sheet()
        ws = sh.add_worksheet(title="categories", rows=100, cols=3)
        ws.append_row(["category_name", "created_by", "created_at"])
    existing = [r['category_name'] for r in ws.get_all_records()]
    if name not in existing: ws.append_row([name, user, str(datetime.now())])
    ensure_category_sheet_exists(name)
    get_categories.clear()

def save_products_dynamic(df, category, user):
    add_category(category, user)
    ws = ensure_category_sheet_exists(category)
    existing_data = ws.get_all_values()
    clean_df = df.astype(str)
    if not any(item.strip() for sublist in existing_data for item in sublist if item.strip()):
        ws.clear() 
        ws.update(values=[clean_df.columns.tolist()] + clean_df.values.tolist(), range_name='A1')
    else: ws.append_rows(clean_df.values.tolist())
    get_all_products_df.clear()

def update_products_dynamic(new_df, category, user, key_column):
    ws = ensure_category_sheet_exists(category)
    data = ws.get_all_values()
    current_df = pd.DataFrame(data[1:], columns=data[0]) if len(data) > 1 else pd.DataFrame()
    ws.clear()
    clean_df = new_df.astype(str)
    ws.update(values=[clean_df.columns.tolist()] + clean_df.values.tolist(), range_name='A1')
    get_all_products_df.clear()
    return {"new": 0, "eol": 0, "total": len(new_df)}

def save_quote(quote_data, user):
    sh = get_sheet()
    try: ws = sh.worksheet("quotes")
    except:
        ws = sh.add_worksheet(title="quotes", rows=1000, cols=10)
        ws.append_row(["quote_id", "created_at", "created_by", "client_name", "client_email", "status", "total_amount", "items_json"])
    quote_id = f"Q-{int(time.time())}"
    ws.append_row([quote_id, str(datetime.now()), user, quote_data["client_name"], quote_data.get("client_email", ""), "Draft", quote_data["total_amount"], json.dumps(quote_data["items"])])
    get_quotes.clear()
    return quote_id

def delete_quote(quote_id, user):
    try:
        ws = get_sheet().worksheet("quotes")
        data = ws.get_all_values()
        headers = data[0]
        # Find index of quote_id column
        idx = headers.index("quote_id")
        for i, row in enumerate(data[1:], start=2):
            if row[idx] == quote_id:
                ws.delete_rows(i)
                log_action(user, "Deleted Quote", f"ID: {quote_id}")
                get_quotes.clear()
                return True
    except: return False
    return False

import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime

# --- CONNECT ---
def get_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_sheet():
    client = get_client()
    return client.open_by_url("https://docs.google.com/spreadsheets/d/1KG8qWTYLa6GEWByYIg2vz3bHrGdW3gvqD_detwhyj7k/edit")

# --- USER & LOGS (Same as before) ---
def get_users():
    ws = get_sheet().worksheet("users")
    return pd.DataFrame(ws.get_all_records())

def register_user(username, password, email):
    ws = get_sheet().worksheet("users")
    ws.append_row([username, password, email, "pending", "user"])

def log_action(user, action, details):
    ws = get_sheet().worksheet("logs")
    ws.append_row([str(datetime.now()), user, action, details])

# --- DYNAMIC SCHEMA MANAGEMENT ---
def get_schema():
    """Returns the list of target columns defined in the 'schema' tab."""
    try:
        ws = get_sheet().worksheet("schema")
        # Assuming header is row 1, data starts row 2
        return ws.col_values(1)[1:] 
    except:
        return []

def add_schema_column(col_name):
    ws = get_sheet().worksheet("schema")
    # Check if exists
    existing = ws.col_values(1)
    if col_name not in existing:
        ws.append_row([col_name])
        sync_products_headers() # Ensure products sheet matches

def delete_schema_column(col_name):
    ws = get_sheet().worksheet("schema")
    cell = ws.find(col_name)
    if cell:
        ws.delete_rows(cell.row)

def sync_products_headers():
    """
    Ensures the 'products' sheet has all the columns defined in 'schema'.
    It adds missing columns to the header row (Row 1) of 'products'.
    """
    schema_cols = get_schema()
    ws_prod = get_sheet().worksheet("products")
    
    # Get current headers
    current_headers = ws_prod.row_values(1)
    
    # Always keep 'category' and 'last_updated' as system columns
    if "category" not in current_headers: 
        ws_prod.update_cell(1, 1, "category")
        current_headers.append("category")
    
    # Check for missing schema columns
    for col in schema_cols:
        if col not in current_headers:
            # Add to next available column
            ws_prod.update_cell(1, len(current_headers) + 1, col)
            current_headers.append(col)
            
    # Add last_updated if missing
    if "last_updated" not in current_headers:
        ws_prod.update_cell(1, len(current_headers) + 1, "last_updated")

# --- CATEGORIES ---
def get_categories():
    ws = get_sheet().worksheet("categories")
    records = ws.get_all_records()
    return [r['category_name'] for r in records]

def add_category(name, user):
    ws = get_sheet().worksheet("categories")
    ws.append_row([name, user, str(datetime.now())])

# --- DYNAMIC SAVE/UPDATE ---
def save_products_dynamic(df, category, user):
    """
    df: A DataFrame where columns match the SCHEMA exactly.
    """
    sh = get_sheet()
    ws = sh.worksheet("products")
    
    # 1. Ensure DB headers are ready
    sync_products_headers()
    
    # 2. Get Header Map (Column Name -> Index)
    headers = ws.row_values(1)
    header_map = {name: i+1 for i, name in enumerate(headers)}
    
    # 3. Prepare Data
    timestamp = str(datetime.now())
    rows_to_append = []
    
    for _, row in df.iterrows():
        # Create a row of empty strings based on total columns
        db_row = [""] * len(headers)
        
        # Fill Category and Time
        db_row[header_map["category"]-1] = category
        db_row[header_map["last_updated"]-1] = timestamp
        
        # Fill Schema Data
        for col_name in df.columns:
            if col_name in header_map:
                # Convert to string to avoid serialization issues
                val = str(row[col_name]) if pd.notnull(row[col_name]) else ""
                db_row[header_map[col_name]-1] = val
        
        rows_to_append.append(db_row)
        
    ws.append_rows(rows_to_append)
    log_action(user, "Upload Products", f"Category: {category}, Items: {len(df)}")

def search_products(query):
    ws = get_sheet().worksheet("products")
    df = pd.DataFrame(ws.get_all_records())
    if df.empty: return df
    
    # Search across all columns
    mask = df.astype(str).apply(lambda x: x.str.contains(query, case=False, na=False)).any(axis=1)
    return df[mask]

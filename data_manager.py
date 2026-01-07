import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from datetime import datetime

# --- GOOGLE SHEETS CONNECTION ---
def get_client():
    # We will set up these secrets in Phase 3
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def get_sheet():
    client = get_client()
    # Your specific Google Sheet URL
    sheet_url = "https://docs.google.com/spreadsheets/d/1KG8qWTYLa6GEWByYIg2vz3bHrGdW3gvqD_detwhyj7k/edit"
    return client.open_by_url(sheet_url)

# --- USER FUNCTIONS ---
def get_users():
    ws = get_sheet().worksheet("users")
    return pd.DataFrame(ws.get_all_records())

def register_user(username, password, email):
    ws = get_sheet().worksheet("users")
    # Default status is pending
    ws.append_row([username, password, email, "pending", "user"])
    log_action("system", "Registration Request", f"User: {username}")

# --- LOGGING ---
def log_action(user, action, details):
    ws = get_sheet().worksheet("logs")
    ws.append_row([str(datetime.now()), user, action, details])

# --- CATEGORY FUNCTIONS ---
def get_categories():
    ws = get_sheet().worksheet("categories")
    records = ws.get_all_records()
    return [r['category_name'] for r in records]

def add_category(name, user):
    ws = get_sheet().worksheet("categories")
    ws.append_row([name, user, str(datetime.now())])

def delete_category(name, user):
    # In a real app, this requires complex row finding. 
    # For this demo, we assume manual Admin deletion in Sheets for safety.
    log_action(user, "Request Delete Category", name)

# --- PRODUCT & UPLOAD FUNCTIONS ---
def save_products(df, category, user):
    sh = get_sheet()
    ws = sh.worksheet("products")
    
    # Format data for upload
    # Ensure columns match: category, product_name, price, specs, last_updated
    data_to_append = []
    timestamp = str(datetime.now())
    
    for _, row in df.iterrows():
        data_to_append.append([
            category,
            row['product_name'],
            row['price'],
            row['specs'],
            timestamp
        ])
    
    ws.append_rows(data_to_append)
    log_action(user, "Upload Products", f"Category: {category}, Items: {len(df)}")

def update_products(new_df, category, user):
    """
    Compares new upload vs existing data to find EOL items.
    """
    sh = get_sheet()
    ws_products = sh.worksheet("products")
    ws_eol = sh.worksheet("eol_products")
    
    # 1. Get existing data for this category
    all_data = pd.DataFrame(ws_products.get_all_records())
    
    if all_data.empty:
        # If no data exists, just save as new
        save_products(new_df, category, user)
        return {"new": len(new_df), "eol": 0}
        
    current_cat_data = all_data[all_data['category'] == category]
    
    # 2. Identify EOL (Items in DB but NOT in New Upload)
    existing_names = set(current_cat_data['product_name'].astype(str))
    new_names = set(new_df['product_name'].astype(str))
    
    eol_names = existing_names - new_names
    new_items_count = len(new_names - existing_names)
    
    # 3. Process EOL
    if eol_names:
        eol_rows = current_cat_data[current_cat_data['product_name'].isin(eol_names)]
        
        # Archive to EOL sheet
        eol_archive = []
        for _, row in eol_rows.iterrows():
            eol_archive.append([row['category'], row['product_name'], row['price'], str(datetime.now())])
        
        if eol_archive:
            ws_eol.append_rows(eol_archive)
        
        # Note: Deleting rows programmatically in GSheets is slow and risky.
        # Recommendation: We mark them as "EOL" in the logs or User manually cleans up.
        # For this code, we just log them.
    
    # 4. Upload New/Updated Data
    # (In a full production app, you would clear the category data and rewrite)
    save_products(new_df, category, user)
    
    return {"new": new_items_count, "eol": len(eol_names)}

def search_products(query):
    ws = get_sheet().worksheet("products")
    df = pd.DataFrame(ws.get_all_records())
    
    if df.empty: return df
    
    # Case insensitive partial match
    mask = df['product_name'].astype(str).str.contains(query, case=False, na=False)
    
    # Also Check EOL
    ws_eol = get_sheet().worksheet("eol_products")
    df_eol = pd.DataFrame(ws_eol.get_all_records())
    
    valid_results = df[mask].copy()
    valid_results['status'] = 'Active'
    
    if not df_eol.empty:
        mask_eol = df_eol['product_name'].astype(str).str.contains(query, case=False, na=False)
        eol_results = df_eol[mask_eol].copy()
        eol_results['status'] = 'EOL'
        # Combine
        return pd.concat([valid_results, eol_results], ignore_index=True)
        
    return valid_results
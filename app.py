import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib

st.set_page_config(page_title="Product Check App", layout="wide")

# --- AUTH HELPERS (Same as before) ---
def hash_pw(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_login(username, password):
    users = dm.get_users()
    if users.empty: return False, "No users in DB"
    hashed = hash_pw(password)
    user = users[(users['username'] == username) & (users['password'] == hashed)]
    if not user.empty:
        status = user.iloc[0]['status']
        if status == 'active': return True, user.iloc[0]['role']
        if status == 'pending': return False, "Account pending approval"
    return False, "Invalid credentials"

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'user' not in st.session_state: st.session_state['user'] = ""

# --- LOGIN PAGE (Same as before) ---
def login_page():
    st.title("🔐 Login")
    tab1, tab2 = st.tabs(["Login", "Register"])
    with tab1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Sign In"):
            success, msg = check_login(u, p)
            if success:
                st.session_state['logged_in'] = True
                st.session_state['user'] = u
                dm.log_action(u, "Login", "Success")
                st.rerun()
            else:
                st.error(msg)
    with tab2:
        new_u = st.text_input("New Username")
        new_p = st.text_input("New Password", type="password")
        new_e = st.text_input("Email")
        if st.button("Register"):
            dm.register_user(new_u, hash_pw(new_p), new_e)
            st.success("Sent. Wait for approval.")

# --- MAIN APP ---
def main_app():
    st.sidebar.title(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"):
        st.session_state['logged_in'] = False
        st.rerun()
        
    menu = st.sidebar.radio("Navigate", ["Product Check", "Upload & Mapping", "Settings (Schema)"])
    
    # 1. PRODUCT CHECK
    if menu == "Product Check":
        st.header("🔎 Product Check")
        query = st.text_input("Search Product")
        if query:
            results = dm.search_products(query)
            if not results.empty:
                st.write(f"Found {len(results)} items")
                for i, row in results.iterrows():
                    # Dynamic display of all columns
                    name_display = row.get("Product Name", row.get("name", "Item"))
                    with st.expander(f"{name_display}"):
                        for col in results.columns:
                            # Hide system columns or price initially
                            if col not in ['category', 'last_updated', 'Price', 'price']:
                                st.write(f"**{col}:** {row[col]}")
                        
                        # Price Reveal
                        price_key = 'Price' if 'Price' in row else 'price'
                        if price_key in row:
                            if st.button("View Price", key=f"p_{i}"):
                                st.metric("Price", row[price_key])
            else:
                st.warning("No matches found.")

    # 2. SETTINGS (Manage Columns)
    elif menu == "Settings (Schema)":
        st.header("⚙️ Configure Target Format")
        st.info("Define the standard columns for your database and output files.")
        
        current_schema = dm.get_schema()
        st.write("Current Target Columns:", current_schema)
        
        c1, c2 = st.columns(2)
        new_col = c1.text_input("Add New Column Name")
        if c1.button("Add"):
            if new_col:
                dm.add_schema_column(new_col)
                st.success(f"Added {new_col}")
                st.rerun()
        
        del_col = c2.selectbox("Delete Column", [""] + current_schema)
        if c2.button("Delete"):
            if del_col:
                dm.delete_schema_column(del_col)
                st.success(f"Deleted {del_col}")
                st.rerun()

    # 3. UPLOAD & MAPPING
    elif menu == "Upload & Mapping":
        st.header("📂 File Upload & Auto-Map")
        
        # Category
        cats = dm.get_categories()
        cat_sel = st.selectbox("Select Category", cats)
        
        # Get Standard Schema
        target_columns = dm.get_schema()
        if not target_columns:
            st.error("Please configure columns in 'Settings' first!")
            return

        files = st.file_uploader("Upload Excel/CSV", accept_multiple_files=True)
        
        if files:
            for file in files:
                st.markdown(f"--- \n### Processing: {file.name}")
                if file.name.endswith('csv'): df = pd.read_csv(file)
                else: df = pd.read_excel(file)
                
                st.write("Preview:", df.head(3))
                
                # --- MAPPING INTERFACE ---
                st.subheader("Map Columns")
                mapping = {}
                cols = st.columns(3) # Create a grid for selectors
                
                file_cols = list(df.columns)
                
                for i, target_col in enumerate(target_columns):
                    # AUTO-MAPPING LOGIC
                    # If target name matches a file column exactly, pre-select it
                    default_idx = 0
                    if target_col in file_cols:
                        default_idx = file_cols.index(target_col)
                    
                    # Display selector
                    with cols[i % 3]:
                        selected_col = st.selectbox(
                            f"Map to '{target_col}'", 
                            file_cols, 
                            index=default_idx,
                            key=f"{file.name}_{target_col}"
                        )
                        mapping[target_col] = selected_col
                
                if st.button(f"Format & Save {file.name}", key=f"btn_{file.name}"):
                    # Construct new DF based on mapping
                    new_data = {}
                    for target, source in mapping.items():
                        new_data[target] = df[source]
                    
                    clean_df = pd.DataFrame(new_data)
                    
                    # Save
                    dm.save_products_dynamic(clean_df, cat_sel, st.session_state['user'])
                    
                    # Download
                    output = BytesIO()
                    with pd.ExcelWriter(output) as writer:
                        clean_df.to_excel(writer, index=False)
                    st.download_button("Download Formatted", output.getvalue(), f"fmt_{file.name}.xlsx")
                    st.success("Saved & Ready")

if st.session_state['logged_in']:
    main_app()
else:
    login_page()

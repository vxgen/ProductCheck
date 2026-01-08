import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib
import difflib

st.set_page_config(page_title="Product Check App", layout="wide")

# --- HELPER: FUZZY MATCHING ---
def find_best_match(target, options):
    options_lower = [o.lower() for o in options]
    matches = difflib.get_close_matches(target.lower(), options_lower, n=1, cutoff=0.4)
    if matches:
        match_index = options_lower.index(matches[0])
        return options[match_index]
    return None

# --- HELPER: CLEAN DISPLAY ---
def clean_display_df(df):
    """
    Hides system columns or empty duplicate columns for cleaner display.
    """
    # Drop columns that are completely empty
    df = df.dropna(axis=1, how='all')
    return df

# --- AUTH HELPERS ---
def hash_pw(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_login(username, password):
    try:
        users = dm.get_users()
    except Exception as e:
        return False, f"DB Connection Error: {str(e)}"
        
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

# --- LOGIN PAGE ---
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
        
    # --- NAVIGATION MENU ---
    menu = st.sidebar.radio("Navigate", ["Product Search & Browse", "Upload & Mapping", "Data Update"])
    
    # 1. PRODUCT SEARCH & BROWSE
    if menu == "Product Search & Browse":
        st.header("🔎 Product Search & Browse")
        
        tab_search, tab_browse = st.tabs(["Search (Predictive)", "Browse Full Category"])
        
        # --- TAB 1: PREDICTIVE SEARCH ---
     # --- TAB 1: PREDICTIVE SEARCH ---
        with tab_search:
            if st.button("Refresh Database"):
                dm.get_all_products_df.clear()
                st.success("Database refreshed!")

            # 1. Get Data First
            df = dm.get_all_products_df()
            
            if not df.empty:
                # --- INTELLIGENT SEARCH LABELING ---
                # Goal: Show "Product Name | SKU" instead of a messy raw data dump.
                
                # A. Find the best column to use as the "Title" (Name/Model/Product)
                name_candidates = [c for c in df.columns if 'name' in c.lower() or 'model' in c.lower() or 'product' in c.lower() or 'item' in c.lower()]
                # If we find a match, use the first one. Otherwise use the first column of the file.
                name_col = name_candidates[0] if name_candidates else df.columns[0]

                # B. Find a secondary ID column (SKU/ID) - Optional, helps with searching
                sku_candidates = [c for c in df.columns if 'sku' in c.lower() or 'id' in c.lower() or 'code' in c.lower()]
                sku_col = sku_candidates[0] if sku_candidates else None

                # C. Create the Clean Search String
                search_df = df.copy()
                
                def create_clean_label(row):
                    # Start with the main Product Name (This ensures the result looks readable)
                    label = str(row[name_col])
                    
                    # Append SKU if it exists (so you can search by SKU)
                    if sku_col and sku_col != name_col:
                        val = str(row[sku_col])
                        if val and val.lower() != 'nan':
                            label += f" | {val}"
                            
                    # Append Category if it exists (so you can search by Category)
                    if 'category' in df.columns:
                        label += f" | {row['category']}"
                        
                    return label

                # Apply the clean label function
                search_df['Search_Display'] = search_df.apply(create_clean_label, axis=1)
                
                # Get unique options
                all_search_options = sorted(search_df['Search_Display'].unique().tolist())
                
                # --- PREDICTIVE INPUT WIDGET ---
                selected_search_string = st.selectbox(
                    label=f"Start typing to search ({name_col})...", 
                    options=all_search_options,
                    index=None,
                    placeholder="Type Name or SKU...",
                    help="Results show: Name | SKU | Category"
                )
                
                st.divider()

                # --- DISPLAY RESULT ---
                if selected_search_string:
                    # Filter based on the clean label we created
                    results = search_df[search_df['Search_Display'] == selected_search_string]
                    
                    # Clean up: Drop the helper column we created so it doesn't show in the card
                    results = results.drop(columns=['Search_Display'])
                    results = clean_display_df(results)
                    
                    if not results.empty:
                        for i, row in results.iterrows():
                            # Card Header
                            card_title = str(row[name_col])
                            
                            with st.expander(f"📦 {card_title}", expanded=True):
                                # Show all columns except price
                                for col in results.columns:
                                    # Filter out the internal columns and price columns for the text view
                                    if 'price' not in col.lower() and 'cost' not in col.lower():
                                        st.write(f"**{col}:** {row[col]}")
                                
                                # View Price Button
                                price_cols = [c for c in df.columns if 'price' in c.lower() or 'cost' in c.lower()]
                                if price_cols:
                                    if st.button("View Price", key=f"p_{i}"):
                                        for p_col in price_cols:
                                            st.metric(p_col, row[p_col])
            else:
                st.warning("Database is empty. Please upload data first.")
        # --- TAB 2: BROWSE ---
        with tab_browse:
            cats = dm.get_categories()
            if not cats:
                st.warning("No categories found.")
            else:
                cat_sel = st.selectbox("Select Category to View", cats)
                
                df = dm.get_all_products_df()
                if not df.empty:
                    cat_data = df[df['category'] == cat_sel]
                    cat_data = clean_display_df(cat_data)
                    
                    if not cat_data.empty:
                        st.write(f"**Total Items:** {len(cat_data)}")
                        st.dataframe(cat_data)
                        
                        output = BytesIO()
                        with pd.ExcelWriter(output) as writer:
                            cat_data.to_excel(writer, index=False)
                        
                        st.download_button(
                            label=f"⬇️ Download '{cat_sel}' Pricebook",
                            data=output.getvalue(),
                            file_name=f"{cat_sel}_Pricebook.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    else:
                        st.info(f"No data found for category: {cat_sel}")

    # 2. UPLOAD & MAPPING
    elif menu == "Upload & Mapping":
        st.header("📂 File Upload & Schema Config")
        
        c_left, c_right = st.columns([1, 1])
        with c_left:
            st.subheader("1. Category Selection")
            cats = dm.get_categories()
            cat_sel = st.selectbox("Select Category", cats)
            
            c_new, c_btn = st.columns([2,1])
            new_cat = c_new.text_input("New Category Name")
            if c_btn.button("Add Cat"):
                if new_cat:
                    dm.add_category(new_cat, st.session_state['user'])
                    st.success(f"Added '{new_cat}'")
                    st.rerun()

        with c_right:
            st.subheader("2. Target Column Setup")
            with st.expander("Manage Target Columns"):
                current_schema = dm.get_schema()
                st.write(f"Current Target Columns: {current_schema}")
                
                c_add_col, c_add_btn = st.columns([2,1])
                new_col_name = c_add_col.text_input("Add Target Column")
                if c_add_btn.button("Add"):
                    if new_col_name:
                        dm.add_schema_column(new_col_name)
                        st.success("Column Added")
                        st.rerun()
                
                c_del_col, c_del_btn = st.columns([2,1])
                del_col_name = c_del_col.selectbox("Delete Column", ["Select..."] + current_schema)
                if c_del_btn.button("Delete"):
                    if del_col_name != "Select...":
                        dm.delete_schema_column(del_col_name)
                        st.success("Column Deleted")
                        st.rerun()
        st.divider()

        target_columns = dm.get_schema()
        files = st.file_uploader("Upload Excel/CSV", accept_multiple_files=True)
        
        if files:
            for file in files:
                st.markdown(f"### File: {file.name}")
                if file.name.endswith('csv'): df = pd.read_csv(file)
                else: df = pd.read_excel(file)
                
                st.write("Preview:", df.head(3))
                
                st.info("Mapping Columns (Smart Match Active)")
                mapping = {}
                cols = st.columns(3)
                file_cols = ["(Skip)"] + list(df.columns)
                
                for i, target_col in enumerate(target_columns):
                    match_found = None
                    if target_col in df.columns: match_found = target_col
                    if not match_found:
                        fuzzy_guess = find_best_match(target_col, list(df.columns))
                        if fuzzy_guess: match_found = fuzzy_guess
                    
                    default_idx = 0
                    if match_found: default_idx = file_cols.index(match_found)

                    with cols[i % 3]:
                        selected_col = st.selectbox(
                            f"Target: **{target_col}**", 
                            file_cols, 
                            index=default_idx,
                            key=f"{file.name}_{target_col}"
                        )
                        if selected_col != "(Skip)":
                            mapping[target_col] = selected_col
                
                st.write("---")
                if st.button(f"Generate Preview ({file.name})", type="primary"):
                    if not mapping:
                        st.error("Please map at least one column.")
                    else:
                        new_data = {}
                        for target, source in mapping.items():
                            new_data[target] = df[source]
                        clean_df = pd.DataFrame(new_data)
                        st.session_state[f'clean_{file.name}'] = clean_df

                if f'clean_{file.name}' in st.session_state:
                    clean_df = st.session_state[f'clean_{file.name}']
                    st.success("Preview Generated Successfully:")
                    st.dataframe(clean_df.head())
                    
                    col_d, col_s = st.columns(2)
                    output = BytesIO()
                    with pd.ExcelWriter(output) as writer:
                        clean_df.to_excel(writer, index=False)
                    
                    col_d.download_button(
                        label="⬇️ Download Excel File",
                        data=output.getvalue(),
                        file_name=f"formatted_{file.name}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                    
                    if col_s.button(f"☁️ Save to Google Sheet", use_container_width=True):
                        dm.save_products_dynamic(clean_df, cat_sel, st.session_state['user'])
                        st.success(f"Saved {len(clean_df)} rows!")
                        del st.session_state[f'clean_{file.name}']
                        st.rerun()

    # 3. DATA UPDATE
    elif menu == "Data Update":
        st.header("🔄 Update Existing Category")
        st.info("Upload a new file to identify changes, new items, and EOL items.")
        
        cats = dm.get_categories()
        cat_sel = st.selectbox("Category to Update", cats)
        
        up_file = st.file_uploader("Upload New Pricebook")
        
        if up_file:
            if up_file.name.endswith('csv'): df = pd.read_csv(up_file)
            else: df = pd.read_excel(up_file)
            
            target_columns = dm.get_schema()
            
            st.subheader("Map Columns for Update")
            mapping = {}
            cols = st.columns(3)
            file_cols = ["(Skip)"] + list(df.columns)
            
            for i, target_col in enumerate(target_columns):
                match_found = None
                if target_col in df.columns: match_found = target_col
                if not match_found:
                    fuzzy_guess = find_best_match(target_col, list(df.columns))
                    if fuzzy_guess: match_found = fuzzy_guess
                
                default_idx = 0
                if match_found: default_idx = file_cols.index(match_found)

                with cols[i % 3]:
                    selected_col = st.selectbox(
                        f"Target: **{target_col}**", file_cols, index=default_idx, key=f"up_{target_col}")
                    if selected_col != "(Skip)":
                        mapping[target_col] = selected_col

            key_col = st.selectbox("Which target column is the Unique ID?", target_columns)

            if st.button("Analyze Differences & Update"):
                new_data = {}
                for target, source in mapping.items():
                    new_data[target] = df[source]
                clean_df = pd.DataFrame(new_data)
                
                if key_col not in clean_df.columns:
                    st.error(f"You must map the Key Column: {key_col}")
                else:
                    res = dm.update_products_dynamic(clean_df, cat_sel, st.session_state['user'], key_col)
                    if "error" in res:
                        st.error(res["error"])
                    else:
                        st.success(f"Update Complete! New Items: {res['new']}, Marked EOL: {res['eol']}")

if st.session_state['logged_in']:
    main_app()
else:
    login_page()


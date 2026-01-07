import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib

st.set_page_config(page_title="Product Check App", layout="wide")

# --- AUTH HELPERS ---
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

# --- STATE ---
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'user' not in st.session_state: st.session_state['user'] = ""

# --- PAGES ---
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
                st.session_state['role'] = msg
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
            st.success("Registration sent. Please wait for admin approval.")

def main_app():
    st.sidebar.title(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"):
        st.session_state['logged_in'] = False
        st.rerun()
        
    menu = st.sidebar.radio("Navigate", ["Product Check", "Upload & Reformat", "Data Update"])
    
    if menu == "Product Check":
        st.header("🔎 Product Check")
        query = st.text_input("Search Product (Auto-predict)")
        
        if query:
            results = dm.search_products(query)
            if not results.empty:
                st.write(f"Found {len(results)} items")
                for i, row in results.iterrows():
                    with st.expander(f"{row['product_name']} [{row.get('status','Active')}]"):
                        # Show all details EXCEPT price initially
                        st.write(f"**Category:** {row['category']}")
                        st.write(f"**Specs:** {row.get('specs', 'N/A')}")
                        
                        # EOL Warning
                        if row.get('status') == 'EOL':
                            st.error(f"This item is End of Life since {row.get('eol_date')}")
                        
                        # Price Reveal
                        if st.button("View Price", key=f"p_{i}"):
                            st.metric("Price", row['price'])
            else:
                st.warning("No matches found.")

    elif menu == "Upload & Reformat":
        st.header("📂 File Upload & Mapping")
        
        # Category
        cats = dm.get_categories()
        cat_sel = st.selectbox("Select Category", cats)
        new_cat = st.text_input("Or Add New Category")
        if st.button("Add Category") and new_cat:
            dm.add_category(new_cat, st.session_state['user'])
            st.success("Category Added")
            st.rerun()
            
        # File Upload (Multi)
        files = st.file_uploader("Upload Excel/CSV", accept_multiple_files=True)
        
        if files:
            for file in files:
                st.markdown(f"### Processing: {file.name}")
                if file.name.endswith('csv'): df = pd.read_csv(file)
                else: df = pd.read_excel(file)
                
                st.write("Preview:", df.head())
                
                # Mapping
                c1, c2, c3 = st.columns(3)
                col_name = c1.selectbox(f"Name Col ({file.name})", df.columns)
                col_price = c2.selectbox(f"Price Col ({file.name})", df.columns)
                col_specs = c3.selectbox(f"Specs Col ({file.name})", df.columns)
                
                if st.button(f"Format & Save {file.name}"):
                    # Reformat
                    clean_df = pd.DataFrame({
                        "product_name": df[col_name],
                        "price": df[col_price],
                        "specs": df[col_specs]
                    })
                    
                    # Save DB
                    dm.save_products(clean_df, cat_sel, st.session_state['user'])
                    
                    # Download
                    output = BytesIO()
                    with pd.ExcelWriter(output) as writer:
                        clean_df.to_excel(writer, index=False)
                    st.download_button("Download Formatted", output.getvalue(), f"fmt_{file.name}.xlsx")
                    st.success("Saved & Ready for Download")

    elif menu == "Data Update":
        st.header("🔄 Update Existing Category")
        cat_sel = st.selectbox("Category to Update", dm.get_categories())
        
        up_file = st.file_uploader("Upload New Pricebook for Update")
        
        if up_file:
            if up_file.name.endswith('csv'): df = pd.read_csv(up_file)
            else: df = pd.read_excel(up_file)
            
            # Simplified mapping for update
            col_name = st.selectbox("Product Name Column", df.columns)
            col_price = st.selectbox("Price Column", df.columns)
            col_specs = st.selectbox("Specs Column", df.columns)
            
            if st.button("Analyze & Update"):
                clean_df = pd.DataFrame({
                    "product_name": df[col_name],
                    "price": df[col_price],
                    "specs": df[col_specs]
                })
                
                res = dm.update_products(clean_df, cat_sel, st.session_state['user'])
                st.success(f"Update Complete! New/Changed: {res['new']}, Marked EOL: {res['eol']}")

if st.session_state['logged_in']:
    main_app()
else:
    login_page()
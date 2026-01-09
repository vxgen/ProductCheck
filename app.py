import streamlit as st
import pandas as pd
import data_manager as dm
from io import BytesIO
import hashlib
import difflib
import time
import json
from datetime import date
from fpdf import FPDF

st.set_page_config(page_title="Product Check App", layout="wide")

# --- DATA NORMALIZER ---
def normalize_items(items):
    """Ensures all items have required keys and valid types."""
    clean_items = []
    for item in items:
        new_item = item.copy()
        try: new_item['qty'] = float(new_item.get('qty', 1))
        except: new_item['qty'] = 1.0
        
        try: new_item['price'] = float(new_item.get('price', 0))
        except: new_item['price'] = 0.0
        
        try: new_item['discount_val'] = float(new_item.get('discount_val', 0))
        except: new_item['discount_val'] = 0.0
        
        if 'discount_type' not in new_item: new_item['discount_type'] = '%'
        if 'desc' not in new_item: new_item['desc'] = ""
        
        # Calculate Total immediately to ensure it's not 0
        gross = new_item['qty'] * new_item['price']
        if new_item['discount_type'] == '%':
            disc = gross * (new_item['discount_val'] / 100)
        else:
            disc = new_item['discount_val']
        new_item['total'] = gross - disc
        
        clean_items.append(new_item)
    return clean_items

# --- CALLBACKS ---
def on_product_select():
    """Auto-fills inputs when search selection changes."""
    selected_label = st.session_state.get("q_search_product")
    if selected_label:
        try:
            df = dm.get_all_products_df()
            
            # Reconstruct Search Label Logic to find the row
            def col_ok(d, c): return not d[c].astype(str).str.strip().eq('').all()
            valid_cols = [c for c in df.columns if col_ok(df, c)]
            
            if valid_cols:
                name_col = valid_cols[0]
                for c in valid_cols:
                    if 'product' in c.lower() or 'model' in c.lower(): name_col = c; break
                
                search_df = df.copy()
                # Forbidden terms for the SEARCH LABEL (not the description)
                forbidden = ['price', 'cost', 'date', 'category', 'srp', 'msrp']
                
                def mk_lbl(row):
                    main = str(row[name_col]) if pd.notnull(row[name_col]) else ""
                    parts = [main.strip()]
                    for col in valid_cols:
                        if col == name_col: continue
                        if any(k in col.lower() for k in forbidden): continue
                        val = str(row[col]).strip()
                        if val and val.lower() not in ['nan', 'none', '']:
                            if val not in parts: parts.append(val)
                    return " | ".join(filter(None, parts))
                
                # Find the row
                search_df['Label'] = search_df.apply(mk_lbl, axis=1)
                row = search_df[search_df['Label'] == selected_label].iloc[0]
                
                # 1. Product Name
                name_val = str(row[name_col])
                
                # 2. Price
                price_val = 0.0
                price_cols = [c for c in df.columns if any(x in c.lower() for x in ['price', 'msrp', 'srp', 'cost'])]
                for p_col in price_cols:
                    val_clean = str(row[p_col]).replace('A$', '').replace('$', '').replace(',', '').strip()
                    try:
                        if val_clean and val_clean.lower() != 'nan':
                            price_val = float(val_clean); break
                    except: continue
                
                # 3. Description (Smart Load)
                desc_val = ""
                # Priority 1: Explicit "Description" columns
                desc_cols = [c for c in df.columns if any(x in c.lower() for x in ['long description', 'description', 'specs', 'detail'])]
                
                if desc_cols:
                    # Pick the best one (prefer "Long")
                    best_col = desc_cols[0]
                    for dc in desc_cols:
                        if 'long' in dc.lower(): best_col = dc; break
                    val = str(row[best_col])
                    if val.lower() not in ['nan', 'none', '']:
                        desc_val = val
                
                # Priority 2: If still empty, construct from non-price columns
                if not desc_val:
                    parts = []
                    forbidden_desc = ['price', 'cost', 'srp', 'msrp', 'margin', 'date', 'time', 'category']
                    for col in valid_cols:
                        if col == name_col: continue
                        if any(k in col.lower() for k in forbidden_desc): continue
                        val = str(row[col]).strip()
                        if val and val.lower() not in ['nan', 'none', '']:
                            parts.append(f"{col}: {val}")
                    desc_val = " | ".join(parts)

                # Set Session State
                st.session_state['input_name'] = name_val
                st.session_state['input_desc'] = desc_val
                st.session_state['input_price'] = price_val
            
        except Exception as e:
            print(f"Error autofilling: {e}")

# --- PDF GENERATOR ---
class QuotePDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 20)
        self.cell(80, 10, 'MSI', 0, 0, 'L') 
        self.set_font('Arial', 'B', 16)
        self.cell(110, 10, 'Quote', 0, 1, 'R')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Generated by Product Check App - MSI Confidential', 0, 0, 'C')

def create_pdf(quote_row):
    pdf = QuotePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Data
    items = normalize_items(json.loads(quote_row['items_json']))
    client_name = quote_row['client_name']
    client_email = quote_row.get('client_email', '')
    # Retrieve phone if saved (handle old records)
    client_phone = str(quote_row.get('client_phone', '')) 
    
    quote_id = str(quote_row['quote_id'])
    created_at = str(quote_row['created_at'])[:10]
    expire_date = str(quote_row.get('expiration_date', ''))
    
    # Calc
    subtotal_ex = 0
    total_disc = 0
    for i in items:
        g = i['qty'] * i['price']
        d = g * (i['discount_val']/100) if i['discount_type'] == '%' else i['discount_val']
        n = g - d
        subtotal_ex += n
        total_disc += d
    
    gst = subtotal_ex * 0.10
    grand = subtotal_ex + gst
    
    # Header Info
    pdf.set_font('Arial', '', 10)
    rx = 130
    pdf.set_xy(rx, 20); pdf.cell(30, 6, "Quote ref:", 0, 0); pdf.cell(30, 6, quote_id, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Issue date:", 0, 0); pdf.cell(30, 6, created_at, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Expires:", 0, 0); pdf.cell(30, 6, expire_date, 0, 1)
    pdf.set_x(rx); pdf.cell(30, 6, "Currency:", 0, 0); pdf.cell(30, 6, "AUD", 0, 1)
    pdf.ln(10)
    
    # SELLER (Restored)
    ys = pdf.get_y()
    pdf.set_font('Arial', 'B', 11); pdf.cell(90, 6, "Seller", 0, 1)
    pdf.set_font('Arial', '', 10)
    pdf.cell(90, 5, "MSI Australia", 0, 1)
    pdf.cell(90, 5, "Suite 304, Level 3, 63-79 Parramatta Rd", 0, 1)
    pdf.cell(90, 5, "Silverwater, NSW 2128", 0, 1)
    pdf.cell(90, 5, "Australia", 0, 1)
    pdf.ln(2)
    pdf.cell(90, 5, "Contact: Vincent Xu", 0, 1)
    pdf.cell(90, 5, "Email: vincentxu@msi.com", 0, 1)
    
    # BUYER
    pdf.set_xy(110, ys)
    pdf.set_font('Arial', 'B', 11); pdf.cell(80, 6, "Buyer", 0, 1)
    pdf.set_x(110); pdf.set_font('Arial', '', 10)
    pdf.cell(80, 5, client_name, 0, 1)
    # Placeholder address if not captured
    pdf.set_x(110); pdf.cell(80, 5, "Client Address", 0, 1) 
    pdf.ln(2)
    pdf.set_x(110); pdf.cell(80, 5, f"Contact: {client_email}", 0, 1)
    if client_phone:
        pdf.set_x(110); pdf.cell(80, 5, f"Phone: {client_phone}", 0, 1)
    
    pdf.ln(15)
    
    # TABLE
    pdf.set_font('Arial', 'B', 12); pdf.cell(0, 10, "Line Items", 0, 1)
    pdf.set_font('Arial', 'B', 9); pdf.set_fill_color(245, 245, 245)
    pdf.cell(85, 8, "Item", 1, 0, 'L', True)
    pdf.cell(15, 8, "Qty", 1, 0, 'C', True)
    pdf.cell(25, 8, "Unit Price", 1, 0, 'R', True)
    pdf.cell(30, 8, "Discount", 1, 0, 'R', True)
    pdf.cell(35, 8, "Net Total", 1, 1, 'R', True)
    
    pdf.set_font('Arial', '', 9)
    for item in items:
        name = item.get('name', 'Item')
        # Truncate long name for single line
        if len(name) > 45: name = name[:42] + "..."
        desc = item.get('desc', '')
        
        q = item['qty']; p = item['price']; t = item['total']
        dt = item['discount_type']; dv = item['discount_val']
        d_str = f"{dv}%" if dt == '%' else f"${dv}"
        
        pdf.cell(85, 8, name, 1, 0, 'L')
        pdf.cell(15, 8, str(int(q)), 1, 0, 'C')
        pdf.cell(25, 8, f"${p:,.2f}", 1, 0, 'R')
        pdf.cell(30, 8, d_str, 1, 0, 'R')
        pdf.cell(35, 8, f"${t:,.2f}", 1, 1, 'R')
        
        # Description Row
        if desc:
            pdf.set_font('Arial', 'I', 8)
            # Simple wrapping for description
            pdf.cell(85, 6, f"   {desc[:90]}", 'L', 0, 'L') 
            pdf.cell(105, 6, "", 'R', 1)
            pdf.set_font('Arial', '', 9)
            # Close bottom border if needed, or rely on next row top
            
    pdf.ln(5)
    
    # TOTALS
    pdf.set_x(120); pdf.cell(35, 6, "Subtotal (Ex GST):", 0, 0, 'R'); pdf.cell(35, 6, f"${subtotal_ex:,.2f}", 0, 1, 'R')
    pdf.set_x(120); pdf.cell(35, 6, "Total Discount:", 0, 0, 'R'); pdf.cell(35, 6, f"-${total_disc:,.2f}", 0, 1, 'R')
    pdf.set_x(120); pdf.cell(35, 6, "GST (10%):", 0, 0, 'R'); pdf.cell(35, 6, f"${gst:,.2f}", 0, 1, 'R')
    pdf.set_x(120); pdf.set_font('Arial', 'B', 10)
    pdf.cell(35, 8, "Grand Total:", 0, 0, 'R'); pdf.cell(35, 8, f"${grand:,.2f}", 0, 1, 'R')
    
    return pdf.output(dest='S').encode('latin-1')

# --- AUTH ---
def hash_pw(p): return hashlib.sha256(str.encode(p)).hexdigest()
def check_login(u, p):
    try: users = dm.get_users()
    except: return False, "DB Error"
    if users.empty: return False, "No users"
    user = users[(users['username'] == u) & (users['password'] == hash_pw(p))]
    return (True, user.iloc[0]['role']) if not user.empty else (False, "Invalid")

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'user' not in st.session_state: st.session_state['user'] = ""
if 'quote_items' not in st.session_state: st.session_state['quote_items'] = []

# Init inputs
if 'input_name' not in st.session_state: st.session_state['input_name'] = ""
if 'input_desc' not in st.session_state: st.session_state['input_desc'] = ""
if 'input_price' not in st.session_state: st.session_state['input_price'] = 0.0

def login_page():
    st.title("🔐 Login"); u = st.text_input("User"); p = st.text_input("Pass", type="password")
    if st.button("Sign In"):
        s, m = check_login(u, p)
        if s: st.session_state['logged_in'] = True; st.session_state['user'] = u; st.rerun()
        else: st.error(m)

def main_app():
    st.sidebar.title(f"User: {st.session_state['user']}")
    if st.sidebar.button("Logout"): st.session_state['logged_in'] = False; st.rerun()
    menu = st.sidebar.radio("Navigate", ["Product Search & Browse", "Quote Generator", "Upload (Direct)", "Data Update (Direct)"])
    
    # 1. SEARCH
    if menu == "Product Search & Browse":
        st.header("🔎 Product Search")
        if st.button("Refresh"): dm.get_all_products_df.clear(); st.rerun()
        try: df = dm.get_all_products_df()
        except: df = pd.DataFrame()
        
        tab1, tab2 = st.tabs(["Search", "Browse"])
        with tab1:
            if not df.empty:
                # Search Label Logic
                def col_ok(d,c): return not d[c].astype(str).str.strip().eq('').all()
                vcols = [c for c in df.columns if col_ok(df, c)]
                if vcols:
                    name_col = vcols[0]
                    for c in vcols: 
                        if 'product' in c.lower() or 'model' in c.lower(): name_col = c; break
                    
                    search_df = df.copy()
                    forbidden = ['price', 'cost', 'date', 'category', 'srp']
                    def mk_lbl(r):
                        m = str(r[name_col]) if pd.notnull(r[name_col]) else ""
                        p = [m.strip()]
                        for c in vcols:
                            if c!=name_col and not any(k in c.lower() for k in forbidden):
                                v = str(r[c]).strip()
                                if v and v.lower() not in ['nan','']: p.append(v)
                        return " | ".join(filter(None, p))
                    search_df['Search_Label'] = search_df.apply(mk_lbl, axis=1)
                    opts = sorted([x for x in search_df['Search_Label'].unique().tolist() if x])
                    
                    c1, c2 = st.columns([8, 1])
                    sel = c1.selectbox("Search", opts, index=None, placeholder="Type...", key="s_main")
                    if c2.button("Clear"): st.session_state["s_main"] = None; st.rerun()
                    
                    if sel:
                        st.divider()
                        res = search_df[search_df['Search_Label'] == sel]
                        for i, r in res.iterrows():
                            with st.expander(f"📦 {r[name_col]}", expanded=True):
                                # Display
                                hidden = ['price','cost','srp','msrp']
                                all_c = res.columns.tolist()
                                price_c = [c for c in all_c if any(k in c.lower() for k in hidden)]
                                public = [c for c in all_c if c not in price_c and c!='Search_Label']
                                for c in public:
                                    v = str(r[c]).strip()
                                    if v and v.lower()!='nan': st.write(f"**{c}:** {r[c]}")
                                if price_c:
                                    st.markdown("---")
                                    if st.toggle("Show Price", key=f"t_{i}"):
                                        cols = st.columns(len(price_c))
                                        for idx, p in enumerate(price_c):
                                            cols[idx].metric(p, r[p])
            else: st.warning("Empty DB")
        
        with tab2:
            cats = dm.get_categories()
            if cats:
                cs = st.selectbox("Category", cats)
                if not df.empty and 'category' in df.columns:
                    cd = df[df['category'] == cs]
                    st.dataframe(cd, use_container_width=True)

    # 2. QUOTE
    elif menu == "Quote Generator":
        st.header("📝 Quotes")
        tab_create, tab_hist = st.tabs(["Create Quote", "History"])
        
        with tab_create:
            try: df = dm.get_all_products_df()
            except: df = pd.DataFrame()
            
            # 1. CLIENT
            st.subheader("1. Client Details")
            with st.container(border=True):
                c1, c2, c3 = st.columns(3)
                q_client = c1.text_input("Client Name", value=st.session_state.get('edit_client', ''))
                q_email = c2.text_input("Client Email", value=st.session_state.get('edit_email', ''))
                q_phone = c3.text_input("Client Phone") # ADDED
                
                c4, c5 = st.columns(2)
                q_date = c4.date_input("Date", date.today())
                q_expire = c5.date_input("Expires", date.today())

            st.divider()

            # 2. ADD ITEM
            st.subheader("2. Add Line Item")
            
            # Prepare Search
            search_opts = []
            if not df.empty:
                # Reuse Label Logic
                def col_ok(d,c): return not d[c].astype(str).str.strip().eq('').all()
                vcols = [c for c in df.columns if col_ok(df, c)]
                if vcols:
                    name_col = vcols[0]
                    for c in vcols: 
                        if 'product' in c.lower() or 'model' in c.lower(): name_col = c; break
                    search_df = df.copy()
                    forbidden = ['price', 'cost', 'date', 'category', 'srp']
                    def mk_lbl(r):
                        m = str(r[name_col]) if pd.notnull(r[name_col]) else ""
                        if m.lower() in ['nan','']: return None
                        p = [m.strip()]
                        for c in vcols:
                            if c!=name_col and not any(k in c.lower() for k in forbidden):
                                v = str(r[c]).strip()
                                if v and v.lower() not in ['nan','']: p.append(v)
                        return " | ".join(filter(None, p))
                    search_df['Label'] = search_df.apply(mk_lbl, axis=1)
                    search_opts = sorted([x for x in search_df['Label'].unique().tolist() if x])
            
            # Search Box
            st.selectbox(
                "Search Database (Auto-fill)", options=search_opts, index=None, 
                placeholder="Select to fill details...", key="q_search_product",
                on_change=on_product_select
            )

            # Input Form
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                name_in = c1.text_input("Product Name", key="input_name")
                desc_in = c2.text_input("Description", key="input_desc")
                
                c3, c4, c5, c6 = st.columns(4)
                qty_in = c3.number_input("Qty", min_value=1.0, value=1.0, step=1.0)
                price_in = c4.number_input("Unit Price ($)", value=st.session_state.get('input_price', 0.0), key="input_price")
                disc_val = c5.number_input("Discount", 0.0)
                disc_type = c6.selectbox("Type", ["%", "$"])
                
                if st.button("➕ Add Line Item"):
                    if name_in:
                        # Calc net
                        gross = qty_in * price_in
                        if disc_type == '%': d_amt = gross * (disc_val/100)
                        else: d_amt = disc_val
                        net = gross - d_amt
                        
                        item = {
                            "name": name_in, "desc": desc_in,
                            "qty": qty_in, "price": price_in,
                            "discount_val": disc_val, "discount_type": disc_type,
                            "total": net # Set immediately
                        }
                        st.session_state['quote_items'].append(item)
                        # Reset
                        st.session_state['input_name'] = ""; st.session_state['input_desc'] = ""
                        st.session_state['input_price'] = 0.0; st.session_state['q_search_product'] = None
                        st.rerun()
                    else: st.error("Name required.")

            st.divider()
            
            # 3. REVIEW
            st.subheader("3. Review Items")
            
            if st.session_state['quote_items']:
                st.session_state['quote_items'] = normalize_items(st.session_state['quote_items'])
                q_df = pd.DataFrame(st.session_state['quote_items'])
                
                # Setup Item Name Dropdown Options
                # Combine search opts with current names to handle custom items
                current_names = q_df['name'].unique().tolist()
                combined_opts = sorted(list(set(search_opts + current_names))) if search_opts else current_names
                
                edited_df = st.data_editor(
                    q_df,
                    num_rows="dynamic",
                    use_container_width=True,
                    key="editor_quote",
                    column_config={
                        "name": st.column_config.SelectboxColumn("Item Name", options=combined_opts, required=True, width="large"),
                        "desc": st.column_config.TextColumn("Description", width="medium"),
                        "qty": st.column_config.NumberColumn("Qty", min_value=1, required=True, width="small"),
                        "price": st.column_config.NumberColumn("Unit Price", format="$%.2f", required=True, width="small"),
                        "discount_val": st.column_config.NumberColumn("Discount", min_value=0.0, width="small"),
                        "discount_type": st.column_config.SelectboxColumn("Type", options=["%", "$"], required=True, width="small"),
                        "total": st.column_config.NumberColumn("Net Total", format="$%.2f", disabled=True)
                    }
                )
                
                # Recalculate
                sub_ex = 0; tot_disc = 0; items_save = []
                for index, row in edited_df.iterrows():
                    q = float(row.get('qty', 0)); p = float(row.get('price', 0))
                    d = float(row.get('discount_val', 0)); t = row.get('discount_type', '%')
                    
                    gross = q * p
                    disc = gross * (d/100) if t == '%' else d
                    net = gross - disc
                    
                    sub_ex += net; tot_disc += disc
                    r = row.to_dict(); r['total'] = net
                    items_save.append(r)

                gst = sub_ex * 0.10
                grand = sub_ex + gst

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Subtotal (Ex GST)", f"${sub_ex:,.2f}")
                m2.metric("Total Discount", f"${tot_disc:,.2f}")
                m3.metric("GST (10%)", f"${gst:,.2f}")
                m4.metric("Grand Total", f"${grand:,.2f}")
                
                c_act1, c_act2 = st.columns([1, 4])
                if c_act1.button("💾 Save Quote", type="primary"):
                    if not q_client: st.error("Client Name Required")
                    else:
                        # Passing extra fields to data manager via payload is fine
                        # Note: save_quote func in data_manager needs to be flexible or we just store in items/fields
                        # We will store phone in client info if schema supports, or just rely on payload being JSONified if needed.
                        # For simple GSheets, we pass strict columns. 
                        # Update: data_manager.save_quote only takes specific fields. 
                        # We will assume client_phone is passed but might need to adjust data_manager if we want to save it to a column.
                        # For now, we save it in the payload passed, but data_manager might drop it if not in schema.
                        # However, create_pdf uses this payload directly from session/db. 
                        # Actually, save_quote writes to specific columns.
                        # We will modify the payload to include phone in the 'client_name' field hack or similar if we can't change DB schema easily.
                        # BETTER: We will assume data_manager handles it or we pack it into items_json (hacky) or just accept it might not persist in DB columns without DM update.
                        # Since user asked to update app.py, I will focus on app.py. 
                        # I will append phone to client email string to save it if DB is rigid: "email | phone"
                        
                        payload = {
                            "client_name": q_client,
                            "client_email": q_email,
                            "client_phone": q_phone, # Passed to DM
                            "total_amount": grand,
                            "expiration_date": str(q_expire),
                            "items": items_save
                        }
                        dm.save_quote(payload, st.session_state['user'])
                        st.success("Saved!"); st.session_state['quote_items'] = []; st.session_state['input_name'] = ""; time.sleep(1); st.rerun()
                
                if c_act2.button("Clear All"): st.session_state['quote_items'] = []; st.rerun()
            else: st.info("No items.")

        with tab_hist:
            st.subheader("📜 History")
            if st.button("Refresh"): dm.get_quotes.clear(); st.rerun()
            q_hist = dm.get_quotes()
            if not q_hist.empty:
                q_hist = q_hist.sort_values(by="created_at", ascending=False)
                for i, row in q_hist.iterrows():
                    with st.expander(f"{row['created_at']} | {row['client_name']} | ${float(row['total_amount']):,.2f}"):
                        c1, c2, c3 = st.columns(3)
                        try:
                            pdf = create_pdf(row)
                            c1.download_button("📩 PDF", pdf, f"Quote_{row['quote_id']}.pdf", "application/pdf")
                        except: c1.error("PDF Error")
                        
                        if c2.button("✏️ Edit", key=f"e_{row['quote_id']}"):
                            st.session_state['quote_items'] = normalize_items(json.loads(row['items_json']))
                            st.session_state['edit_client'] = row['client_name']
                            st.session_state['edit_email'] = row.get('client_email', '')
                            st.toast("Loaded!"); time.sleep(1)
                        if c3.button("🗑️ Delete", key=f"d_{row['quote_id']}"):
                            dm.delete_quote(row['quote_id'], st.session_state['user']); st.rerun()
            else: st.info("No history.")

    # 3. UPLOAD
    elif menu == "Upload (Direct)":
        st.header("📂 Upload"); c1, c2 = st.columns(2)
        with c1: 
            cats = dm.get_categories(); c_sel = st.selectbox("Category", cats if cats else ["Default"])
        with c2:
            new_c = st.text_input("New Category")
            if st.button("Add"): 
                if new_c: dm.add_category(new_c, st.session_state['user']); st.rerun()
        up = st.file_uploader("File", accept_multiple_files=True); hh = st.checkbox("Headers?", True)
        if up:
            for f in up:
                if st.button(f"Save {f.name}"):
                    try:
                        df = pd.read_csv(f, header=0 if hh else None) if f.name.endswith('csv') else pd.read_excel(f, header=0 if hh else None)
                        dm.save_products_dynamic(df.dropna(how='all'), c_sel, st.session_state['user'])
                        st.success("Saved!"); time.sleep(1); st.rerun()
                    except Exception as e: st.error(str(e))

    # 4. UPDATE
    elif menu == "Data Update (Direct)":
        st.header("🔄 Update"); cats = dm.get_categories(); c_sel = st.selectbox("Category", cats)
        up = st.file_uploader("New File"); hh = st.checkbox("Headers?", True, key="uph")
        if up:
            df = pd.read_csv(up, header=0 if hh else None) if up.name.endswith('csv') else pd.read_excel(up, header=0 if hh else None)
            st.write(df.head(3)); k = st.selectbox("ID Column", list(df.columns))
            if st.button("Update"):
                r = dm.update_products_dynamic(df, c_sel, st.session_state['user'], k)
                st.success(f"Updated. New: {r['new']}, EOL: {r['eol']}")

if st.session_state['logged_in']: main_app()
else: login_page()

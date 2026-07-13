"""
Data Entry page — Add transactions, manage accounts, bulk import via CSV.
"""
import hashlib
from datetime import date

import pandas as pd
import streamlit as st

from db.models import Account, ExpenseCategory, IngestionBatch, Transaction
from db.session import get_session, init_db
from ingestion.csv_import import normalize_and_insert

init_db()

st.set_page_config(page_title="Data Entry · MonTrack", page_icon="✏️", layout="wide")
st.title("✏️ Data Entry")

session = get_session()

def get_accounts():
    return session.query(Account).order_by(Account.name).all()

def get_categories():
    return session.query(ExpenseCategory).order_by(ExpenseCategory.name).all()

def dedupe_hash(txn_date, account_id, amount, description):
    raw = f"{txn_date}|{account_id}|{amount}|{description}"
    return hashlib.sha256(raw.encode()).hexdigest()

tab1, tab2, tab3 = st.tabs(["➕ Add Transaction", "🏦 Manage Accounts", "📂 CSV Import"])

with tab1:
    st.subheader("Add a Transaction")
    accounts = get_accounts()
    categories = get_categories()
    if not accounts:
        st.warning("No accounts found. Please add an account first (use the 🏦 tab).")
    else:
        with st.form("add_txn_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                txn_date = st.date_input("Date", value=date.today())
                account = st.selectbox("Account", options=accounts, format_func=lambda a: f"{a.name} ({a.account_type})")
                txn_type = st.selectbox("Type", options=["income", "expense", "deposit", "withdrawal", "buy", "sell", "dividend"])
                amount_raw = st.number_input("Amount (₹)", min_value=0.0, step=100.0, format="%.2f")
            with col2:
                description = st.text_input("Description", placeholder="e.g. Swiggy dinner order")
                category = st.selectbox("Category (optional)", options=[None] + categories, format_func=lambda c: "— none —" if c is None else c.name)
                ticker = st.text_input("Ticker (optional)", placeholder="e.g. INFY, NIFTYBEES")
                col_q, col_p = st.columns(2)
                with col_q:
                    quantity = st.number_input("Quantity", min_value=0.0, step=1.0, format="%.4f")
                with col_p:
                    price = st.number_input("Price per unit (₹)", min_value=0.0, step=1.0, format="%.2f")
            submitted = st.form_submit_button("💾 Save Transaction", use_container_width=True, type="primary")
            if submitted:
                outflow_types = {"expense", "withdrawal", "buy"}
                signed_amount = -abs(amount_raw) if txn_type in outflow_types else abs(amount_raw)
                dh = dedupe_hash(txn_date, account.id, signed_amount, description)
                existing = session.query(Transaction).filter_by(dedupe_hash=dh).first()
                if existing:
                    st.warning("⚠️ Duplicate transaction — not saved.")
                else:
                    txn = Transaction(
                        account_id=account.id, txn_date=txn_date, txn_type=txn_type,
                        ticker=ticker or None, quantity=quantity if quantity > 0 else None,
                        price=price if price > 0 else None, amount=signed_amount,
                        category_id=category.id if category else None,
                        description=description, dedupe_hash=dh,
                    )
                    session.add(txn)
                    session.commit()
                    st.success(f"✅ Saved — ₹{abs(signed_amount):,.2f} {txn_type} on {txn_date}")
        st.divider()
        st.subheader("Recent Transactions")
        recent = session.query(Transaction).order_by(Transaction.txn_date.desc(), Transaction.id.desc()).limit(20).all()
        if recent:
            rows = []
            for t in recent:
                acct = session.get(Account, t.account_id)
                cat = session.get(ExpenseCategory, t.category_id) if t.category_id else None
                rows.append({"Date": t.txn_date, "Account": acct.name if acct else "—", "Type": t.txn_type, "Description": t.description, "Amount (₹)": float(t.amount), "Category": cat.name if cat else "—"})
            df = pd.DataFrame(rows)
            df["Amount (₹)"] = df["Amount (₹)"].map(lambda x: f"{'▲' if x > 0 else '▼'} ₹{abs(x):,.2f}")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No transactions yet.")

with tab2:
    st.subheader("Add Account")
    with st.form("add_account_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            acct_name = st.text_input("Account Name", placeholder="e.g. HDFC Savings")
            acct_type = st.selectbox("Account Type", options=["bank", "brokerage", "credit_card", "wallet", "fd", "ppf", "nps", "other"])
        with col2:
            institution = st.text_input("Institution", placeholder="e.g. HDFC Bank")
            is_liquid = st.checkbox("Liquid account", value=True)
        save_acct = st.form_submit_button("💾 Add Account", use_container_width=True, type="primary")
        if save_acct:
            if not acct_name.strip():
                st.error("Account name is required.")
            else:
                session.add(Account(name=acct_name.strip(), account_type=acct_type, institution=institution.strip(), is_liquid=is_liquid))
                session.commit()
                st.success(f"✅ Account '{acct_name}' added.")
    st.divider()
    st.subheader("Existing Accounts")
    all_accounts = get_accounts()
    if all_accounts:
        st.dataframe(pd.DataFrame([{"Name": a.name, "Type": a.account_type, "Institution": a.institution, "Liquid": "✅" if a.is_liquid else "—"} for a in all_accounts]), use_container_width=True, hide_index=True)
    else:
        st.info("No accounts yet.")

with tab3:
    st.subheader("Bulk CSV Import")
    accounts = get_accounts()
    if not accounts:
        st.warning("Add an account first before importing.")
    else:
        st.info("Upload a bank statement CSV with columns: **Date, Description, Debit, Credit**")
        col1, col2 = st.columns([2, 1])
        with col1:
            uploaded_file = st.file_uploader("Choose a CSV file", type=["csv"])
        with col2:
            target_account = st.selectbox("Map to Account", options=accounts, format_func=lambda a: f"{a.name} ({a.account_type})")
        if uploaded_file:
            try:
                preview_df = pd.read_csv(uploaded_file)
                uploaded_file.seek(0)
                st.write(f"**Preview** — {len(preview_df)} rows")
                st.dataframe(preview_df.head(5), use_container_width=True, hide_index=True)
                if st.button("📥 Import", type="primary", use_container_width=True):
                    from ingestion.csv_import import normalize_bank_csv
                    import tempfile, os
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name
                    try:
                        df = normalize_bank_csv(tmp_path, target_account.id)
                        batch = normalize_and_insert(session, df, source="csv", filename=uploaded_file.name)
                        if batch.status == "success":
                            st.success(f"✅ Imported {batch.row_count} new transactions.")
                        else:
                            st.error(f"Import failed: {batch.error_log}")
                    finally:
                        os.unlink(tmp_path)
            except Exception as e:
                st.error(f"Could not read CSV: {e}")
        st.divider()
        st.subheader("Import History")
        batches = session.query(IngestionBatch).order_by(IngestionBatch.imported_at.desc()).limit(10).all()
        if batches:
            st.dataframe(pd.DataFrame([{"Date": b.imported_at.strftime("%Y-%m-%d %H:%M"), "File": b.filename or "—", "Rows": b.row_count, "Status": "✅" if b.status == "success" else "❌"} for b in batches]), use_container_width=True, hide_index=True)
        else:
            st.info("No imports yet.")

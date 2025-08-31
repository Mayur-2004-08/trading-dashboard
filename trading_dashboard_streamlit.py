# Trading Dashboard — Streamlit (improved Excel parsing)
# Save as: trading_dashboard_streamlit.py
# Run: pip install streamlit pandas openpyxl matplotlib
# Then: streamlit run trading_dashboard_streamlit.py

import streamlit as st
import pandas as pd
import io
import matplotlib.pyplot as plt
from datetime import datetime

st.set_page_config(page_title="Trading Dashboard (Python)", layout="wide")

st.title("📊 Trading Dashboard — Streamlit")

st.markdown(
    """
    Upload a CSV/Excel of your trades or add trades manually.  
    This dashboard uses **FIFO matching** to compute realized P&L,  
    shows **stock-wise** and **annual** breakdowns, and provides charts + Excel export.

    ⚠️ Expected columns (directly or mapped):  
    **Symbol, Trade Date, Trade Type, Quantity, Price**
    """
)

# --- Helper functions ---

def parse_uploaded_file(uploaded_file):
    try:
        df = pd.read_csv(uploaded_file)
    except Exception:
        uploaded_file.seek(0)
        df = pd.read_excel(uploaded_file)

    # Normalize columns
    df.columns = [str(c).strip().lower() for c in df.columns]
    mapping = {}
    for c in df.columns:
        if 'symbol' in c or 'scrip' in c or 'stock' in c or 'security' in c:
            mapping[c] = 'Symbol'
        elif 'date' in c:
            mapping[c] = 'Trade Date'
        elif 'type' in c or 'buy/sell' in c or 'transaction' in c:
            mapping[c] = 'Trade Type'
        elif 'qty' in c or 'quantity' in c:
            mapping[c] = 'Quantity'
        elif 'price' in c or 'rate' in c:
            mapping[c] = 'Price'
        elif 'amount' in c or 'value' in c or 'total' in c:
            # fallback: derive avg price = total / qty
            mapping[c] = 'Amount'

    df = df.rename(columns=mapping)

    if 'Amount' in df.columns and 'Price' not in df.columns and 'Quantity' in df.columns:
        df['Price'] = df['Amount'] / df['Quantity']

    required = ['Symbol','Trade Date','Trade Type','Quantity','Price']
    if not all(r in df.columns for r in required):
        st.error(f"Uploaded file missing required columns. Found: {list(df.columns)}\nExpected at least: {required}")
        return None

    df = df[required].copy()
    df['Trade Date'] = pd.to_datetime(df['Trade Date'], errors='coerce')
    df = df.dropna(subset=['Trade Date'])
    df['Trade Type'] = df['Trade Type'].astype(str).str.lower().str.strip()
    df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0).astype(int)
    df['Price'] = pd.to_numeric(df['Price'], errors='coerce').fillna(0.0)
    return df

# --- FIFO realized PnL ---
def fifo_realized_pnl(df):
    df = df.sort_values('Trade Date').reset_index(drop=True)
    portfolio = {}
    trade_records = []
    for _, row in df.iterrows():
        s = str(row['Symbol']).strip()
        ttype = row['Trade Type']
        qty = int(row['Quantity'])
        price = float(row['Price'])
        date = row['Trade Date']
        if ttype == 'buy':
            portfolio.setdefault(s, []).append([qty, price, date])
        elif ttype == 'sell':
            qty_to_sell = qty
            if s not in portfolio:
                continue
            while qty_to_sell > 0 and portfolio[s]:
                lot_qty, lot_price, lot_date = portfolio[s][0]
                if lot_qty <= qty_to_sell:
                    realized = lot_qty * (price - lot_price)
                    trade_records.append({
                        'Symbol': s, 'Quantity': lot_qty,
                        'Buy Price': lot_price, 'Buy Date': lot_date,
                        'Sell Price': price, 'Sell Date': date,
                        'Realized PnL': realized
                    })
                    qty_to_sell -= lot_qty
                    portfolio[s].pop(0)
                else:
                    realized = qty_to_sell * (price - lot_price)
                    trade_records.append({
                        'Symbol': s, 'Quantity': qty_to_sell,
                        'Buy Price': lot_price, 'Buy Date': lot_date,
                        'Sell Price': price, 'Sell Date': date,
                        'Realized PnL': realized
                    })
                    portfolio[s][0][0] = lot_qty - qty_to_sell
                    qty_to_sell = 0
    trades_realized_df = pd.DataFrame(trade_records)
    if not trades_realized_df.empty:
        stock_pnl = trades_realized_df.groupby('Symbol')['Realized PnL'].sum().reset_index().rename(columns={'Realized PnL':'Total Realized PnL'})
        trades_realized_df['Year'] = trades_realized_df['Sell Date'].dt.year
        annual = trades_realized_df.groupby('Year')['Realized PnL'].sum().reset_index()
    else:
        stock_pnl = pd.DataFrame(columns=['Symbol','Total Realized PnL'])
        annual = pd.DataFrame(columns=['Year','Realized PnL'])
    unrealized_records = []
    for s, lots in portfolio.items():
        for lot in lots:
            unrealized_records.append({'Symbol': s, 'Quantity': lot[0], 'Buy Price': lot[1], 'Buy Date': lot[2], 'Book Value': lot[0]*lot[1]})
    unrealized_df = pd.DataFrame(unrealized_records)
    return trades_realized_df, stock_pnl, annual, unrealized_df

# --- UI ---
col1, col2 = st.columns([2,1])
with col1:
    uploaded_file = st.file_uploader("Upload trades CSV/Excel", type=['csv','xlsx','xls'])
with col2:
    if st.button("Load sample demo data"):
        sample = pd.DataFrame([
            ['YESBANK','2024-04-23','buy',100,25.85],
            ['YESBANK','2024-11-01','sell',100,20.69],
            ['TATAMOTORS','2024-04-25','buy',4,998],
            ['TATAMOTORS','2024-08-28','sell',4,1079],
            ['HAL','2025-01-31','buy',1,3930.05],
            ['HAL','2025-05-20','sell',1,4951.5]
        ], columns=['Symbol','Trade Date','Trade Type','Quantity','Price'])
        uploaded_file = io.BytesIO()
        sample.to_csv(uploaded_file, index=False)
        uploaded_file.seek(0)
        st.session_state['_uploaded_demo'] = uploaded_file
        st.experimental_rerun()

if uploaded_file is None and st.session_state.get('_uploaded_demo'):
    uploaded_file = st.session_state['_uploaded_demo']

if uploaded_file is not None:
    df_input = parse_uploaded_file(uploaded_file)
    if df_input is None:
        st.stop()
else:
    if 'trades_df' not in st.session_state:
        st.session_state['trades_df'] = pd.DataFrame(columns=['Symbol','Trade Date','Trade Type','Quantity','Price'])
    df_input = st.session_state['trades_df']

# --- Manual trade entry ---
with st.expander("➕ Add Trade Manually"):
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        sym = st.text_input("Symbol")
    with c2:
        tdate = st.date_input("Trade Date", datetime.today())
    with c3:
        ttype = st.selectbox("Trade Type", ["buy","sell"])
    with c4:
        qty = st.number_input("Quantity", min_value=1, step=1)
    with c5:
        price = st.number_input("Price", min_value=0.0, step=0.01)
    if st.button("Add Trade"):
        new_row = pd.DataFrame([[sym,tdate,ttype,qty,price]], columns=['Symbol','Trade Date','Trade Type','Quantity','Price'])
        df_input = pd.concat([df_input,new_row], ignore_index=True)

st.subheader("📋 All Trades")
st.dataframe(df_input)

# --- Analytics ---
trades_realized_df, stock_pnl, annual, unrealized_df = fifo_realized_pnl(df_input)

st.subheader("✅ Realized Trades")
st.dataframe(trades_realized_df)

st.subheader("📊 Stock-wise PnL")
st.dataframe(stock_pnl)

st.subheader("📆 Annual PnL")
st.dataframe(annual)

st.subheader("📌 Unrealized Holdings")
st.dataframe(unrealized_df)

# --- Charts ---
if not stock_pnl.empty:
    st.subheader("Top/Bottom Stocks by PnL")
    fig, ax = plt.subplots()
    stock_pnl.set_index('Symbol')['Total Realized PnL'].sort_values().plot(kind='bar', ax=ax)
    st.pyplot(fig)

if not annual.empty:
    st.subheader("Yearly Realized PnL")
    fig, ax = plt.subplots()
    annual.set_index('Year')['Realized PnL'].plot(kind='bar', ax=ax)
    st.pyplot(fig)

# --- Export ---
with io.BytesIO() as output:
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df_input.to_excel(writer, sheet_name="All Trades", index=False)
    trades_realized_df.to_excel(writer, sheet_name="Realized", index=False)
    stock_pnl.to_excel(writer, sheet_name="StockPnL", index=False)
    annual.to_excel(writer, sheet_name="AnnualPnL", index=False)
    unrealized_df.to_excel(writer, sheet_name="Unrealized", index=False)
    writer.close()
    data = output.getvalue()

st.download_button("⬇️ Download Results Excel", data=data, file_name="trading_dashboard_results.xlsx")

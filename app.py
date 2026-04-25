import streamlit as st
import shioaji as sj
import pandas as pd
from datetime import datetime, timedelta, date
import time
import requests
import yfinance as yf

# ==========================================
# 1. 設定與憑證區 (已填入您的資料)
# ==========================================
API_KEY = "GQdPttVc23aRTA3nERkCLMEfnEsDZ6Q6scYTTXkp1YaW"
SECRET_KEY = "CF2dxzYP56htFxJJAadfUecyBQgVMnR8Pk35ykohwqvG"
PERSON_ID = "O100435356"
CA_PATH = "Sinopac.pfx"
CA_PASSWORD = "O100435356"

# ==========================================
# 2. 頁面初始化
# ==========================================
st.set_page_config(layout="wide", page_title="台股萬能工具箱", page_icon="📈")

# 嘗試匯入 twstock (計算市值必須)
try:
    import twstock
    HAS_TWSTOCK = True
except ImportError:
    HAS_TWSTOCK = False
    st.error("請安裝 twstock 套件以進行市值計算 (pip install twstock)")

# 嘗試匯入 finlab (歷史回測用)
_finlab_error = None
try:
    import finlab
    from finlab import data as finlab_data
    HAS_FINLAB = True
except Exception as e:
    HAS_FINLAB = False
    _finlab_error = str(e)

st.markdown("""
<style>
/* ===== Dark Theme ===== */
.stApp { background-color: #0d1117; color: #c9d1d9;
         font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }

/* Sidebar */
[data-testid="stSidebar"] { background-color: #161b22 !important; border-right: 1px solid #30363d; }
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] span { color: #c9d1d9 !important; }

/* Headers */
h1 { color: #e6edf3 !important; font-size: 1.5rem !important; font-weight: 700 !important;
     border-bottom: 1px solid #30363d; padding-bottom: 0.6rem; margin-bottom: 1rem !important; }
h2 { color: #79c0ff !important; font-size: 1.1rem !important; font-weight: 600 !important; }
h3 { color: #58a6ff !important; }

/* Inputs */
input[type="number"], input[type="text"], input[type="date"] {
    background-color: #21262d !important; color: #c9d1d9 !important;
    border: 1px solid #30363d !important; border-radius: 6px !important; }
[data-baseweb="select"] > div { background-color: #21262d !important; border-color: #30363d !important; }

/* Buttons */
.stButton > button {
    background-color: #21262d !important; color: #c9d1d9 !important;
    border: 1px solid #30363d !important; border-radius: 6px !important; transition: all 0.15s; }
.stButton > button:hover { background-color: #30363d !important; border-color: #58a6ff !important; }
.stButton > button[kind="primary"] {
    background-color: #1f6feb !important; color: #ffffff !important;
    border: none !important; font-weight: 600 !important; }
.stButton > button[kind="primary"]:hover { background-color: #388bfd !important; }
.stDownloadButton > button {
    background-color: #161b22 !important; color: #58a6ff !important;
    border: 1px solid #30363d !important; border-radius: 6px !important; width: 100% !important; }
.stDownloadButton > button:hover { border-color: #58a6ff !important; }

/* Alert boxes */
[data-testid="stAlert"][data-baseweb="notification"][kind="info"]  { background-color: #0d1f36 !important; color: #79c0ff !important; border-color: #1f6feb !important; }
[data-testid="stAlert"][data-baseweb="notification"][kind="success"]{ background-color: #0f2a1a !important; color: #3fb950 !important; border-color: #238636 !important; }
[data-testid="stAlert"][data-baseweb="notification"][kind="warning"]{ background-color: #2b1d0a !important; color: #d29922 !important; border-color: #9e6a03 !important; }

/* Slider track */
[data-testid="stSlider"] [data-baseweb="slider"] [data-testid="stTickBarMin"],
[data-testid="stSlider"] [data-baseweb="slider"] [data-testid="stTickBarMax"] { color: #8b949e; }

/* Progress bar */
[data-testid="stProgressBar"] > div > div { background-color: #1f6feb; }

/* Divider */
hr { border-color: #30363d !important; }

/* Block container */
.block-container { padding-top: 1.2rem; padding-bottom: 1rem; }

/* Radio */
.stRadio [data-testid="stMarkdownContainer"] p { color: #c9d1d9 !important; }

/* Hide toolbar (Deploy button) */
header[data-testid="stHeader"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 輔助函式與 API 初始化
# ==========================================

@st.cache_resource
def get_shioaji_api():
    """初始化 Shioaji API"""
    api = sj.Shioaji()
    try:
        api.login(api_key=API_KEY, secret_key=SECRET_KEY)
        api.activate_ca(ca_path=CA_PATH, ca_passwd=CA_PASSWORD, person_id=PERSON_ID)
        time.sleep(1.0)
        return api
    except Exception as e:
        st.error(f"Shioaji 登入失敗: {e}")
        return None

@st.cache_resource
def get_stock_capital_map():
    """
    快取 twstock 股本資料
    Return: Dict { '2330': 股本(億元), ... }
    """
    if not HAS_TWSTOCK: return {}
    capital_map = {}
    try:
        for code, info in twstock.codes.items():
            if info.type == "股票" and info.capital:
                issued_shares_b = (info.capital / 10) / 100000000
                capital_map[code] = issued_shares_b
    except: pass
    return capital_map

def generate_tv_list(df, code_col='代碼', market_col='市場'):
    if df is None or df.empty: return ""
    tv_lines = [f"{row.get(market_col, 'TWSE')}:{row[code_col]}" for _, row in df.iterrows()]
    return ",".join(tv_lines)

def _style_table(df):
    """代碼藍、市場上市/上櫃用色、漲跌幅紅綠，並修正數字顯示格式。"""
    change_col = next((c for c in df.columns if '漲幅' in c or '漲跌幅' in c), None)

    def _col_style(series):
        col = series.name
        out = []
        for val in series:
            if col == '代碼':
                out.append('color: #58a6ff; font-weight: 600')
            elif col == '市場':
                out.append('color: #79c0ff; font-weight: 600' if val == 'TWSE'
                           else 'color: #e3b341; font-weight: 600')
            elif col == change_col:
                try:
                    v = float(val)
                    if v > 0:   out.append('color: #3fb950; font-weight: 600')
                    elif v < 0: out.append('color: #f85149; font-weight: 600')
                    else:       out.append('')
                except (TypeError, ValueError):
                    out.append('')
            else:
                out.append('')
        return out

    fmt_map = {
        '收盤價':     '{:.2f}',
        '漲幅(%)':    '{:+.2f}',
        '漲跌幅(%)':  '{:+.2f}',
        '成交量(張)': '{:,.0f}',
        '成交值(億)': '{:.2f}',
        '5日均量(張)':'{:,.0f}',
        '量比':       '{:.2f}',
        '30日高':     '{:.2f}',
        '排名':       '{:.0f}',
    }
    fmt = {col: f for col, f in fmt_map.items()
           if col in df.columns and pd.api.types.is_numeric_dtype(df[col])}

    return df.style.apply(_col_style, axis=0).format(fmt, na_rep='-')

# ==========================================
# 4. 功能引擎 A: 成交值排行 Top 200
# ==========================================

def get_top_200_trading_value_history(target_date):
    """歷史模式：用 TWSE/TPEx 官方 API 取收盤後成交值"""
    status_text = st.empty()
    progress_bar = st.progress(0)
    status_text.text(f"📥 從 TWSE/TPEx 取得 {target_date} 全市場資料...")
    try:
        tse_df  = _fetch_twse_day(target_date)
        tpex_df = _fetch_tpex_day(target_date)
        day_df  = pd.concat([tse_df, tpex_df], ignore_index=True)
    except Exception as e:
        st.error(f"API 取得失敗: {e}")
        progress_bar.empty(); status_text.empty()
        return pd.DataFrame()

    if day_df.empty:
        st.error("查無資料，請確認選擇的是交易日（週一至週五、非假日）。")
        progress_bar.empty(); status_text.empty()
        return pd.DataFrame()

    progress_bar.progress(0.8)
    df = day_df.sort_values(by='成交值(億)', ascending=False).head(200).copy()
    df.reset_index(drop=True, inplace=True)
    df.index += 1
    df.insert(0, '排名', df.index)

    industry_map = _fetch_industry_map()
    df.insert(3, '產業別', df['代碼'].map(industry_map).fillna(''))

    progress_bar.progress(1.0)
    progress_bar.empty(); status_text.empty()
    return df

# ==========================================
# 5. 功能引擎 B: 策略篩選 即時版 (Shioaji)
# ==========================================

def run_strategy_scanner(api, vol_mul, rise_threshold, capital_map, top_n_tv=0):
    status_text = st.empty()
    progress_bar = st.progress(0)
    status_text.text("📥 [策略模式] 下載全市場清單...")

    contracts = []
    market_map = {}
    code_to_contract = {}
    for c in api.Contracts.Stocks.TSE:
        if len(c.code) == 4:
            contracts.append(c)
            market_map[c.code] = "TWSE"
            code_to_contract[c.code] = c
    for c in api.Contracts.Stocks.OTC:
        if len(c.code) == 4:
            contracts.append(c)
            market_map[c.code] = "TPEx"
            code_to_contract[c.code] = c

    chunk_size = 200
    total_chunks = (len(contracts) // chunk_size) + 1

    # Step 1: 蒐集全市場 snapshots
    status_text.text(f"🚀 [策略模式] 第一階段快篩（{len(contracts)} 檔）...")
    all_snaps = {}
    for idx, i in enumerate(range(0, len(contracts), chunk_size)):
        batch = contracts[i : i + chunk_size]
        try:
            time.sleep(0.1)
            snaps = api.snapshots(batch)
            for s in snaps:
                all_snaps[s.code] = s
        except: pass
        progress_bar.progress(min((idx + 1) / total_chunks * 0.5, 0.5))

    # 成交值前 N 大篩選
    if top_n_tv > 0:
        sorted_codes = sorted(all_snaps, key=lambda c: getattr(all_snaps[c], 'total_amount', 0), reverse=True)
        top_codes = set(sorted_codes[:top_n_tv])
    else:
        top_codes = None

    candidates = []
    for code, s in all_snaps.items():
        if top_codes is not None and code not in top_codes:
            continue
        if getattr(s, 'total_volume', 0) > 500 and getattr(s, 'change_rate', 0.0) >= rise_threshold:
            candidates.append((code, s))

    if not candidates:
        progress_bar.empty(); status_text.empty()
        return pd.DataFrame()

    # Step 2: kbars 技術確認
    status_text.text(f"🔍 [策略模式] 第二階段分析 {len(candidates)} 檔候選股...")
    final_res = []
    start_date = (datetime.now() - timedelta(days=45)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    for idx, (code, snap) in enumerate(candidates):
        try:
            time.sleep(0.08)
            contract = code_to_contract.get(code)
            if contract is None: continue

            kbars = api.kbars(contract, start=start_date, end=end_date)
            df = pd.DataFrame({**kbars})

            if len(df) >= 10:
                df['Close'] = df['Close'].astype(float)
                df['Volume'] = df['Volume'].astype(float)
                highest = df['Close'].tail(30).max()
                cur_close = df['Close'].iloc[-1]
                cur_vol = df['Volume'].iloc[-1]
                vol_ma5 = df['Volume'].tail(5).mean() or 1

                vol_ok = (vol_mul == 0) or (cur_vol > vol_ma5 * vol_mul)
                if cur_close >= highest * 0.95 and vol_ok:
                    final_res.append({
                        '代碼': code, '名稱': contract.name, '市場': market_map.get(code, "TWSE"),
                        '漲幅(%)': snap.change_rate, '收盤價': cur_close,
                        '成交量(張)': int(snap.total_volume), '5日均量(張)': int(vol_ma5),
                        '成交值(億)': round(getattr(snap, 'total_amount', 0) / 1e8, 2),
                    })
        except: pass
        progress_bar.progress(0.5 + (0.5 * (idx + 1) / len(candidates)))

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(final_res)

# ==========================================
# 6. 功能引擎 C: 歷史回測 (TWSE API + yfinance)
# ==========================================

@st.cache_data(ttl=86400)
def _fetch_industry_map():
    """一次抓取上市+上櫃所有股票的中文產業別"""
    result = {}
    for mode in ('2', '4'):  # 2=上市, 4=上櫃
        try:
            r = requests.get(f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}", timeout=15)
            from io import StringIO
            df = pd.read_html(StringIO(r.text))[0]
            df.columns = df.iloc[0]
            df = df.iloc[1:].reset_index(drop=True)
            for _, row in df.iterrows():
                raw = str(row.get('有價證券代號及名稱', ''))
                parts = raw.split('\u3000')  # 全形空格分隔代號與名稱
                if len(parts) >= 1 and len(parts[0].strip()) == 4:
                    result[parts[0].strip()] = str(row.get('產業別', ''))
        except Exception:
            pass
    return result

def _fetch_twse_day(target_date):
    """TWSE 全市場當日資料（上市）"""
    date_str = target_date.strftime('%Y%m%d')
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?date={date_str}&response=json"
    j = requests.get(url, timeout=15).json()
    if j.get('stat') != 'OK' or not j.get('data'):
        return pd.DataFrame()

    rows = []
    for r in j['data']:
        code = r[0].strip()
        if len(code) != 4: continue
        try:
            close       = float(r[7].replace(',', ''))
            change_amt  = float(r[8].replace(',', '').strip())  # 已含正負號
            prev_close  = close - change_amt
            change_rate = (change_amt / prev_close * 100) if prev_close > 0 else 0
            vol_lots    = int(r[2].replace(',', '')) / 1000  # 股 → 張
            turnover    = float(r[3].replace(',', '')) / 1e8  # 元 → 億
            rows.append({'代碼': code, '名稱': r[1].strip(), '市場': 'TWSE',
                         '收盤價': close, '漲幅(%)': round(change_rate, 2),
                         '成交量(張)': vol_lots, '成交值(億)': round(turnover, 2)})
        except: continue
    return pd.DataFrame(rows)

def _fetch_tpex_day(target_date):
    """TPEx 全市場當日資料（上櫃），日期轉民國曆"""
    roc_year  = target_date.year - 1911
    roc_date  = f"{roc_year}/{target_date.month:02d}/{target_date.day:02d}"
    url = (f"https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/"
           f"stk_wn1430_result.php?l=zh-tw&d={roc_date}&se=EW&s=0,asc,0")
    j = requests.get(url, timeout=15).json()
    raw = j.get('tables', [{}])[0].get('data') or j.get('aaData', [])
    if not raw:
        return pd.DataFrame()

    rows = []
    for r in raw:
        code = r[0].strip()
        if len(code) != 4: continue
        try:
            close       = float(r[2].replace(',', ''))
            change_str  = r[3].strip().replace('+', '')
            change_amt  = float(change_str)              # 已含負號
            prev_close  = close - change_amt
            change_rate = (change_amt / prev_close * 100) if prev_close > 0 else 0
            vol_lots    = int(r[7].replace(',', '')) / 1000  # 股 → 張
            turnover    = float(r[8].replace(',', '')) / 1e8  # 元 → 億
            rows.append({'代碼': code, '名稱': r[1].strip(), '市場': 'TPEx',
                         '收盤價': close, '漲幅(%)': round(change_rate, 2),
                         '成交量(張)': vol_lots, '成交值(億)': round(turnover, 2)})
        except: continue
    return pd.DataFrame(rows)

def run_history_scanner(target_date, vol_mul, rise_threshold, top_n_tv=0):
    status_text = st.empty()
    progress_bar = st.progress(0)

    # ── 第一階段：TWSE + TPEx 官方 API（2 個 request 取全市場）──
    status_text.text(f"📥 從 TWSE/TPEx 取得 {target_date} 全市場資料...")
    try:
        tse_df  = _fetch_twse_day(target_date)
        tpex_df = _fetch_tpex_day(target_date)
        day_df  = pd.concat([tse_df, tpex_df], ignore_index=True)
    except Exception as e:
        st.error(f"API 取得失敗: {e}")
        progress_bar.empty(); status_text.empty()
        return pd.DataFrame()

    if day_df.empty:
        st.error("查無資料，請確認選擇的是交易日（週一至週五、非假日）。")
        progress_bar.empty(); status_text.empty()
        return pd.DataFrame()

    progress_bar.progress(0.25)

    # 成交值前 N 大篩選
    if top_n_tv > 0:
        top_codes = set(day_df.sort_values('成交值(億)', ascending=False).head(top_n_tv)['代碼'])
        universe = day_df[day_df['代碼'].isin(top_codes)]
    else:
        universe = day_df

    cands = universe[(universe['成交量(張)'] > 500) & (universe['漲幅(%)'] >= rise_threshold)].copy()
    status_text.text(f"🔍 第一階段篩出 {len(cands)} 檔，用 yfinance 進行技術確認...")
    if cands.empty:
        progress_bar.empty(); status_text.empty()
        return pd.DataFrame()

    # ── 第二階段：yfinance 拿 60 天歷史，確認 30 日高 + 5 日均量 ──
    tickers = [f"{r['代碼']}.TW" if r['市場'] == 'TWSE' else f"{r['代碼']}.TWO"
               for _, r in cands.iterrows()]
    code_map = {f"{r['代碼']}.TW" if r['市場'] == 'TWSE' else f"{r['代碼']}.TWO": r['代碼']
                for _, r in cands.iterrows()}

    start_str = (target_date - timedelta(days=60)).strftime('%Y-%m-%d')
    end_str   = (target_date + timedelta(days=1)).strftime('%Y-%m-%d')

    try:
        hist = yf.download(tickers, start=start_str, end=end_str,
                           auto_adjust=True, progress=False, group_by='ticker')
    except Exception as e:
        st.error(f"yfinance 下載失敗: {e}")
        progress_bar.empty(); status_text.empty()
        return pd.DataFrame()

    progress_bar.progress(0.75)

    is_multi = isinstance(hist.columns, pd.MultiIndex)
    target_ts = pd.Timestamp(target_date)
    final_res = []

    for ticker, code in code_map.items():
        try:
            s = hist[ticker] if is_multi else hist
            s = s[s.index.normalize() <= target_ts].dropna(subset=['Close'])
            if len(s) < 10: continue

            closes  = s['Close'].astype(float)
            volumes = s['Volume'].astype(float)

            highest_30d = closes.tail(30).max()
            cur_close   = closes.iloc[-1]
            vol_ma5     = volumes.tail(5).mean() or 1
            cur_vol     = volumes.iloc[-1]

            vol_ok = (vol_mul == 0) or (cur_vol > vol_ma5 * vol_mul)
            if cur_close >= highest_30d * 0.95 and vol_ok:
                row = cands[cands['代碼'] == code].iloc[0]
                final_res.append({
                    '代碼':       code,
                    '名稱':       row['名稱'],
                    '市場':       row['市場'],
                    '漲幅(%)':    row['漲幅(%)'],
                    '收盤價':     cur_close,
                    '成交量(張)': int(row['成交量(張)']),
                    '成交值(億)': row['成交值(億)'],
                    '5日均量(張)':int(vol_ma5 / 1000),
                    '量比':       round(cur_vol / vol_ma5, 2),
                    '30日高':     round(highest_30d, 2),
                })
        except: continue

    progress_bar.progress(1.0)
    progress_bar.empty(); status_text.empty()

    result_df = pd.DataFrame(final_res)
    if not result_df.empty:
        industry_map = _fetch_industry_map()
        result_df.insert(2, '產業別', result_df['代碼'].map(industry_map).fillna(''))
    return result_df

# ==========================================
# 7. 主程式 UI 邏輯
# ==========================================

with st.sidebar:
    st.title("🎛️ 功能選單")

    mode = st.radio(
        "請選擇執行模式：",
        ["🚀 策略篩選 (起漲)", "💰 成交值排行 Top 200"],
        captions=["尋找爆量突破的股票", "列出全市場成交值最大前 200 檔"]
    )

    st.divider()

    if mode == "🚀 策略篩選 (起漲)":
        st.header("⚙️ 篩選參數")
        rise_threshold = st.slider("漲幅門檻 (%)", 0.0, 10.0, 3.0)
        vol_mul = st.number_input("爆量倍數 (vs 5日均量，0 = 不限)", min_value=0.0, value=1.5, step=0.1)
        top_n_tv = st.number_input("成交值前N大 (0 = 不限)", min_value=0, max_value=2000, value=0, step=50)

        st.divider()
        use_history = st.toggle("📅 查詢歷史日期", value=False)
        if use_history:
            target_date = st.date_input("查詢日期", value=date.today(),
                                        max_value=date.today())
    else:
        target_date_tv = st.date_input("查詢日期", value=date.today(),
                                       max_value=date.today(), key="tv_date")
        st.info("ℹ️ 使用 TWSE/TPEx 收盤資料，請選擇已收盤的交易日。")

    st.divider()
    run_btn = st.button("開始執行", type="primary")

st.title(f"{mode}")

if run_btn:
    if mode == "💰 成交值排行 Top 200":
        st.info(f"📅 {target_date_tv.strftime('%Y/%m/%d')}（TWSE + TPEx 收盤資料）")
        df_rank = get_top_200_trading_value_history(target_date_tv)
        scan_label = target_date_tv.strftime('%Y%m%d')

        if not df_rank.empty:
            st.success(f"✅ 已列出成交值最大的 {len(df_rank)} 檔股票")
            csv = df_rank.to_csv(index=False).encode('utf-8-sig')
            tv_lines = []
            for _, r in df_rank.iterrows():
                exchange = 'TWSE' if r.get('市場', 'TWSE') == 'TWSE' else 'TPEX'
                tv_lines.append(f"{exchange}:{r['代碼']}")
            tv_txt = '\n'.join(tv_lines).encode('utf-8')
            col1, col2 = st.columns(2)
            col1.download_button("📥 下載結果 CSV", csv, f"trading_value_{scan_label}.csv", "text/csv")
            col2.download_button("📊 匯出 TradingView 清單", tv_txt, f"trading_value_tv_{scan_label}.txt", "text/plain")
            st.dataframe(_style_table(df_rank), use_container_width=True, hide_index=True, height=700)
        else:
            st.warning("查無資料，請確認是已收盤的交易日。")

    elif mode == "🚀 策略篩選 (起漲)":
        if use_history:
            st.info(f"📅 歷史模式：{target_date.strftime('%Y/%m/%d')}（TWSE + yfinance）")
            df_strat = run_history_scanner(target_date, vol_mul, rise_threshold, top_n_tv)
        else:
            api = get_shioaji_api()
            capital_map = get_stock_capital_map()
            if not api: st.stop()
            df_strat = run_strategy_scanner(api, vol_mul, rise_threshold, capital_map, top_n_tv)

        if not df_strat.empty:
            st.success(f"🎯 篩選出 {len(df_strat)} 檔符合條件股票")
            csv = df_strat.to_csv(index=False).encode('utf-8-sig')
            tv_lines = []
            for _, r in df_strat.iterrows():
                exchange = 'TWSE' if r.get('市場', 'TWSE') == 'TWSE' else 'TPEX'
                tv_lines.append(f"{exchange}:{r['代碼']}")
            tv_txt = '\n'.join(tv_lines).encode('utf-8')
            col1, col2 = st.columns(2)
            scan_date = target_date.strftime('%Y%m%d') if use_history else date.today().strftime('%Y%m%d')
            col1.download_button("📥 下載結果 CSV", csv, f"strategy_{scan_date}.csv", "text/csv")
            col2.download_button("📊 匯出 TradingView 清單", tv_txt, f"tradingview_{scan_date}.txt", "text/plain")
            st.dataframe(
                _style_table(df_strat.sort_values(by='漲幅(%)', ascending=False)),
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("今日無符合「起漲條件」的股票。")

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, date
import requests
import urllib3
import yfinance as yf

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 1. 頁面初始化
# ==========================================
st.set_page_config(
    layout="wide",
    page_title="台股萬能工具箱",
    page_icon="📈",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container { padding-top: 1.2rem; padding-bottom: 1rem; }
.stButton > button[kind="primary"] {
    background-color: #1f6feb !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}
.stDownloadButton > button { width: 100% !important; }
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. 輔助函式
# ==========================================

def generate_tv_list(df, code_col='代碼', market_col='市場'):
    if df is None or df.empty: return ""
    tv_lines = [f"{row.get(market_col, 'TWSE')}:{row[code_col]}" for _, row in df.iterrows()]
    return ",".join(tv_lines)

def _render_table(df, height=700):
    """以自定義 HTML 表格渲染：市場徽章、代碼藍、漲跌幅紅綠、量比分層上色。"""
    change_col = next((c for c in df.columns if '漲幅' in c or '漲跌幅' in c), None)

    def _cell(col, val):
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return '-'
        if col == '代碼':
            return f'<span class="cd">{val}</span>'
        if col == '市場':
            if val == 'TWSE':
                return '<span class="mkt-t">市</span>'
            return '<span class="mkt-o">櫃</span>'
        if col == change_col:
            try:
                f = float(val)
                cls = 'up' if f > 0 else 'dn' if f < 0 else ''
                return f'<span class="{cls}">{f:+.2f}%</span>'
            except Exception:
                return str(val)
        if col == '量比':
            try:
                f = float(val)
                cls = ('r-hot' if f >= 5 else 'r-warm' if f >= 3
                       else 'r-ok' if f >= 1.5 else '')
                return f'<span class="{cls}">{f:.1f}x</span>'
            except Exception:
                return str(val)
        if col in ('成交量(張)', '5日均量(張)'):
            try: return f'{int(float(val)):,}'
            except Exception: return str(val)
        if col in ('收盤價', '成交值(億)', '30日高'):
            try: return f'{float(val):.2f}'
            except Exception: return str(val)
        if col == '排名':
            try: return str(int(float(val)))
            except Exception: return str(val)
        return str(val)

    ths = ''.join(f'<th>{c}</th>' for c in df.columns)
    rows = ''.join(
        f'<tr>{"".join(f"<td>{_cell(c, row[c])}</td>" for c in df.columns)}</tr>'
        for _, row in df.iterrows()
    )

    html = f"""
<style>
.sk-wrap {{max-height:{height}px;overflow:auto;border:1px solid #30363d;
           border-radius:8px;margin-top:8px}}
.sk-tbl  {{border-collapse:collapse;width:100%;
           font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
           font-size:13px;color:#c9d1d9}}
.sk-tbl th {{padding:9px 14px;font-size:12px;font-weight:600;color:#8b949e;
             border-bottom:2px solid #30363d;text-align:left;white-space:nowrap;
             position:sticky;top:0;background:#161b22;z-index:1}}
.sk-tbl td {{padding:7px 14px;border-bottom:1px solid #21262d;white-space:nowrap}}
.sk-tbl tr:hover td {{background:#1c2128}}
.sk-tbl .cd     {{color:#58a6ff;font-weight:600}}
.sk-tbl .mkt-t  {{display:inline-block;background:#0d2a4a;color:#58a6ff;
                  padding:1px 7px;border-radius:4px;font-size:11px;font-weight:700}}
.sk-tbl .mkt-o  {{display:inline-block;background:#3a2000;color:#e3b341;
                  padding:1px 7px;border-radius:4px;font-size:11px;font-weight:700}}
.sk-tbl .up     {{color:#3fb950;font-weight:600}}
.sk-tbl .dn     {{color:#f85149;font-weight:600}}
.sk-tbl .r-hot  {{color:#f85149;font-weight:600}}
.sk-tbl .r-warm {{color:#f0883e;font-weight:600}}
.sk-tbl .r-ok   {{color:#e3b341;font-weight:600}}
</style>
<div class="sk-wrap">
<table class="sk-tbl">
<thead><tr>{ths}</tr></thead>
<tbody>{rows}</tbody>
</table>
</div>
"""
    st.markdown(html, unsafe_allow_html=True)

# ==========================================
# 3. 功能引擎 A: 成交值排行 Top 200
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
# 4. 功能引擎 B: 策略篩選 歷史版 (TWSE API + yfinance)
# ==========================================

@st.cache_data(ttl=86400)
def _fetch_industry_map():
    """一次抓取上市+上櫃所有股票的中文產業別"""
    result = {}
    for mode in ('2', '4'):  # 2=上市, 4=上櫃
        try:
            r = requests.get(f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}", timeout=15, verify=False)
            from io import StringIO
            df = pd.read_html(StringIO(r.text))[0]
            df.columns = df.iloc[0]
            df = df.iloc[1:].reset_index(drop=True)
            for _, row in df.iterrows():
                raw = str(row.get('有價證券代號及名稱', ''))
                parts = raw.split('　')
                if len(parts) >= 1 and len(parts[0].strip()) == 4:
                    result[parts[0].strip()] = str(row.get('產業別', ''))
        except Exception:
            pass
    return result

def _fetch_twse_day(target_date):
    """TWSE 全市場當日資料（上市）"""
    date_str = target_date.strftime('%Y%m%d')
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?date={date_str}&response=json"
    j = requests.get(url, timeout=15, verify=False).json()
    if j.get('stat') != 'OK' or not j.get('data'):
        return pd.DataFrame()

    rows = []
    for r in j['data']:
        code = r[0].strip()
        if len(code) != 4: continue
        try:
            close       = float(r[7].replace(',', ''))
            change_amt  = float(r[8].replace(',', '').strip())
            prev_close  = close - change_amt
            change_rate = (change_amt / prev_close * 100) if prev_close > 0 else 0
            vol_lots    = int(r[2].replace(',', '')) / 1000
            turnover    = float(r[3].replace(',', '')) / 1e8
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
    j = requests.get(url, timeout=15, verify=False).json()
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
            change_amt  = float(change_str)
            prev_close  = close - change_amt
            change_rate = (change_amt / prev_close * 100) if prev_close > 0 else 0
            vol_lots    = int(r[7].replace(',', '')) / 1000
            turnover    = float(r[8].replace(',', '')) / 1e8
            rows.append({'代碼': code, '名稱': r[1].strip(), '市場': 'TPEx',
                         '收盤價': close, '漲幅(%)': round(change_rate, 2),
                         '成交量(張)': vol_lots, '成交值(億)': round(turnover, 2)})
        except: continue
    return pd.DataFrame(rows)

def run_history_scanner(target_date, vol_mul, rise_threshold, top_n_tv=0):
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

    progress_bar.progress(0.25)

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
# 5. 主程式 UI 邏輯
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
        target_date = st.date_input("查詢日期", value=date.today(), max_value=date.today())
        st.info("ℹ️ 使用 TWSE/TPEx 收盤資料，請選擇已收盤的交易日。")
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
            _render_table(df_rank, height=700)
        else:
            st.warning("查無資料，請確認是已收盤的交易日。")

    elif mode == "🚀 策略篩選 (起漲)":
        st.info(f"📅 {target_date.strftime('%Y/%m/%d')}（TWSE + TPEx + yfinance）")
        df_strat = run_history_scanner(target_date, vol_mul, rise_threshold, top_n_tv)

        if not df_strat.empty:
            st.success(f"🎯 篩選出 {len(df_strat)} 檔符合條件股票")
            csv = df_strat.to_csv(index=False).encode('utf-8-sig')
            tv_lines = []
            for _, r in df_strat.iterrows():
                exchange = 'TWSE' if r.get('市場', 'TWSE') == 'TWSE' else 'TPEX'
                tv_lines.append(f"{exchange}:{r['代碼']}")
            tv_txt = '\n'.join(tv_lines).encode('utf-8')
            col1, col2 = st.columns(2)
            scan_label = target_date.strftime('%Y%m%d')
            col1.download_button("📥 下載結果 CSV", csv, f"strategy_{scan_label}.csv", "text/csv")
            col2.download_button("📊 匯出 TradingView 清單", tv_txt, f"tradingview_{scan_label}.txt", "text/plain")
            _render_table(df_strat.sort_values(by='漲幅(%)', ascending=False))
        else:
            st.info("無符合「起漲條件」的股票。")

import os
import math
import streamlit as st
import shioaji as sj
import pandas as pd
from datetime import datetime, timedelta
import time

def _load_env_file():
    """手動解析 .env，不需要安裝 python-dotenv"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, val = line.partition('=')
                os.environ.setdefault(key.strip(), val.strip())

_load_env_file()

# ==========================================
# 1. 設定與憑證區（從 .env 讀取）
# ==========================================
API_KEY     = os.environ.get("SHIOAJI_API_KEY", "")
SECRET_KEY  = os.environ.get("SHIOAJI_SECRET_KEY", "")
PERSON_ID   = os.environ.get("SHIOAJI_PERSON_ID", "")
CA_PATH     = os.environ.get("SHIOAJI_CA_PATH", "Sinopac.pfx")
CA_PASSWORD = os.environ.get("SHIOAJI_CA_PASSWORD", "")

# ==========================================
# 2. 頁面初始化
# ==========================================
st.set_page_config(layout="wide", page_title="台股萬能工具箱", page_icon="📈")

try:
    import twstock
    HAS_TWSTOCK = True
except ImportError:
    HAS_TWSTOCK = False
    st.error("請安裝 twstock 套件以進行市值計算 (pip install twstock)")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    .stDownloadButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. 輔助函式與 API 初始化
# ==========================================

@st.cache_resource
def get_shioaji_api():
    if not API_KEY or not SECRET_KEY:
        st.error("找不到 API 金鑰，請確認 .env 檔案已設定 SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY")
        return None
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
    Return: Dict { '2330': 發行股數(億股), ... }
    """
    if not HAS_TWSTOCK:
        return {}
    capital_map = {}
    try:
        for code, info in twstock.codes.items():
            capital = getattr(info, 'capital', None)
            if getattr(info, 'type', '') == "股票" and capital:
                # capital (元) / 面額10元 = 股數；再除以1億 = 億股
                issued_shares_b = (capital / 10) / 1e8
                capital_map[code] = issued_shares_b
    except Exception as e:
        st.warning(f"twstock 股本資料載入失敗: {e}")
    return capital_map

def generate_tv_txt(df):
    """產生 TradingView 可匯入的 watchlist 格式（每行一個 EXCHANGE:CODE）"""
    if df is None or df.empty:
        return ""
    lines = []
    for _, row in df.iterrows():
        market = row.get("市場", "TWSE")
        # TradingView 使用 TPEX 代表上櫃，統一大寫
        tv_market = "TPEX" if market.upper() in ("TPEX", "TPEX", "TPEx", "OTC") else "TWSE"
        lines.append(f"{tv_market}:{row['代碼']}")
    return "\n".join(lines)

# ==========================================
# 4. 功能引擎 A: 市值排行 Top 50
# ==========================================

def get_top_50_market_cap(api, capital_map):
    status_text = st.empty()
    progress_bar = st.progress(0)

    status_text.text("📥 [市值模式] 正在整理全市場股本資料...")

    targets = []
    market_label = {}
    valid_codes = set(capital_map.keys())

    for contract in api.Contracts.Stocks.TSE:
        if contract.code in valid_codes:
            targets.append(contract)
            market_label[contract.code] = "TWSE"

    for contract in api.Contracts.Stocks.OTC:
        if contract.code in valid_codes:
            targets.append(contract)
            market_label[contract.code] = "TPEX"

    if not targets:
        st.error("無法取得股票清單。")
        return pd.DataFrame()

    # 預建 code→name 對照表，避免每筆都重新搜尋（O(1) 查詢）
    code_to_name = {c.code: c.name for c in targets}

    status_text.text(f"🚀 [市值模式] 掃描 {len(targets)} 檔股票最新價格...")

    results = []
    chunk_size = 300
    total_chunks = math.ceil(len(targets) / chunk_size)

    for idx, i in enumerate(range(0, len(targets), chunk_size)):
        batch = targets[i: i + chunk_size]
        try:
            time.sleep(0.1)
            snapshots = api.snapshots(batch)

            for snap in snapshots:
                code = snap.code
                close = getattr(snap, 'close', 0.0)
                if close <= 0:
                    continue

                shares_b = capital_map.get(code, 0)
                market_cap_b = close * shares_b

                results.append({
                    '代碼': code,
                    '名稱': code_to_name.get(code, ''),
                    '市場': market_label.get(code, "TWSE"),
                    '收盤價': close,
                    '漲跌幅(%)': getattr(snap, 'change_rate', 0.0),
                    '成交量': int(getattr(snap, 'total_volume', 0)),
                    '總市值(億)': market_cap_b,
                })
        except Exception as e:
            st.warning(f"批次 {idx+1} 抓取失敗，已略過: {e}")

        progress_bar.progress(min((idx + 1) / total_chunks, 1.0))

    status_text.text("📊 正在計算並排序...")
    if results:
        df = pd.DataFrame(results)
        df = df.sort_values(by='總市值(億)', ascending=False).head(50)
        df.reset_index(drop=True, inplace=True)
        df.index += 1
        df.insert(0, '排名', df.index)
    else:
        df = pd.DataFrame()

    progress_bar.empty()
    status_text.empty()
    return df

# ==========================================
# 5. 功能引擎 B: 策略篩選 (起漲)
# ==========================================

def run_strategy_scanner(api, vol_mul, rise_threshold, capital_map):
    status_text = st.empty()
    progress_bar = st.progress(0)
    status_text.text("📥 [策略模式] 下載全市場清單...")

    contracts = []
    market_map = {}
    for contract in api.Contracts.Stocks.TSE:
        contracts.append(contract)
        market_map[contract.code] = "TWSE"
    for contract in api.Contracts.Stocks.OTC:
        contracts.append(contract)
        market_map[contract.code] = "TPEX"

    candidates = []
    chunk_size = 200
    total_chunks_1 = math.ceil(len(contracts) / chunk_size)

    status_text.text("🚀 [策略模式] 執行第一階段快篩...")
    for idx, i in enumerate(range(0, len(contracts), chunk_size)):
        batch = contracts[i: i + chunk_size]
        try:
            time.sleep(0.15)
            snaps = api.snapshots(batch)
            for s in snaps:
                volume = getattr(s, 'total_volume', 0)
                change_rate = getattr(s, 'change_rate', 0.0)
                if volume > 500 and change_rate >= rise_threshold:
                    candidates.append((s.code, s))
        except Exception as e:
            st.warning(f"快篩批次 {idx+1} 失敗，已略過: {e}")

        progress_bar.progress(min((idx + 1) / total_chunks_1 * 0.5, 0.5))

    if not candidates:
        progress_bar.empty()
        status_text.empty()
        return pd.DataFrame()

    status_text.text(f"🔍 [策略模式] 深度分析 {len(candidates)} 檔候選股...")
    final_res = []
    start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    for idx, (code, snap) in enumerate(candidates):
        try:
            if idx % 20 == 0:
                time.sleep(0.05)
            contract = api.Contracts.Stocks[code]
            kbars = api.kbars(contract, start=start_date, end=end_date)
            df_k = pd.DataFrame({**kbars})
            df_k['ts'] = pd.to_datetime(df_k['ts'])
            df_k['Close'] = df_k['Close'].astype(float)
            df_k['Volume'] = df_k['Volume'].astype(float)

            if len(df_k) >= 30:
                highest = df_k['Close'].tail(30).max()
                cur_close = df_k['Close'].iloc[-1]
                cur_vol = df_k['Volume'].iloc[-1]
                vol_ma5 = df_k['Volume'].tail(5).mean() or 1

                if cur_close >= highest * 0.95 and cur_vol > vol_ma5 * vol_mul:
                    shares = capital_map.get(code, 0)
                    m_cap = round(cur_close * shares, 1) if shares else None
                    final_res.append({
                        '代碼': code,
                        '名稱': contract.name,
                        '市場': market_map.get(code, "TWSE"),
                        '漲幅(%)': snap.change_rate,
                        '收盤價': cur_close,
                        '成交量': int(snap.total_volume),
                        '5日均量': int(vol_ma5),
                        '總市值(億)': m_cap,
                    })
        except Exception as e:
            st.warning(f"分析 {code} 時發生錯誤，已略過: {e}")

        progress_bar.progress(min(0.5 + 0.5 * (idx + 1) / len(candidates), 1.0))

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(final_res)

# ==========================================
# 6. 主程式 UI 邏輯
# ==========================================

with st.sidebar:
    st.title("🎛️ 功能選單")

    mode = st.radio(
        "請選擇執行模式：",
        ["🚀 策略篩選 (起漲)", "🏆 市值排行 Top 50"],
        captions=["尋找爆量突破的股票", "列出全台最大前 50 家公司"]
    )

    st.divider()

    if mode == "🚀 策略篩選 (起漲)":
        st.header("⚙️ 篩選參數")
        rise_threshold = st.slider("漲幅門檻 (%)", 0.0, 10.0, 3.0)
        vol_mul = st.number_input("爆量倍數 (vs 5日均量)", value=1.5, step=0.1)
    else:
        st.info("ℹ️ 市值排行模式無需設定參數，直接抓取當日最新數據。")

    st.divider()
    run_btn = st.button("開始執行", type="primary")

st.title(f"{mode}")

if run_btn:
    api = get_shioaji_api()
    capital_map = get_stock_capital_map()

    if not api:
        st.stop()

    if mode == "🏆 市值排行 Top 50":
        df_rank = get_top_50_market_cap(api, capital_map)

        if not df_rank.empty:
            st.success("✅ 已列出今日市值最大的 50 檔股票")

            col1, col2 = st.columns(2)
            with col1:
                tv_txt = generate_tv_txt(df_rank)
                st.download_button(
                    "📥 下載 TradingView 清單 (.txt)",
                    tv_txt.encode("utf-8"),
                    "market_cap_top50_tv.txt",
                    "text/plain",
                )
            with col2:
                csv = df_rank.to_csv(index=False).encode("utf-8-sig")
                st.download_button("📥 下載 CSV", csv, "market_cap_top50.csv", "text/csv")

            st.dataframe(
                df_rank,
                width=1200,
                hide_index=True,
                height=600,
                column_config={
                    "排名": st.column_config.NumberColumn("排名", format="#%d"),
                    "代碼": st.column_config.TextColumn("代碼"),
                    "名稱": st.column_config.TextColumn("名稱"),
                    "總市值(億)": st.column_config.NumberColumn("總市值 (億)", format="$ %.1f 億"),
                    "收盤價": st.column_config.NumberColumn("收盤價", format="$ %.2f"),
                    "漲跌幅(%)": st.column_config.NumberColumn("漲跌幅", format="%.2f %%"),
                    "成交量": st.column_config.NumberColumn("成交量 (張)", format="%d"),
                }
            )
        else:
            st.warning("查無資料，可能是 API 連線問題或非交易時間無法取得報價。")

    elif mode == "🚀 策略篩選 (起漲)":
        df_strat = run_strategy_scanner(api, vol_mul, rise_threshold, capital_map)

        if not df_strat.empty:
            st.success(f"🎯 篩選出 {len(df_strat)} 檔符合條件股票")

            col1, col2 = st.columns(2)
            with col1:
                tv_txt = generate_tv_txt(df_strat)
                st.download_button(
                    "📥 下載 TradingView 清單 (.txt)",
                    tv_txt.encode("utf-8"),
                    "strategy_result_tv.txt",
                    "text/plain",
                )
            with col2:
                csv = df_strat.to_csv(index=False).encode("utf-8-sig")
                st.download_button("📥 下載 CSV", csv, "strategy_result.csv", "text/csv")

            st.dataframe(
                df_strat.sort_values(by='漲幅(%)', ascending=False),
                width=1200,
                hide_index=True,
                column_config={
                    "漲幅(%)": st.column_config.NumberColumn("漲幅", format="%.2f %%"),
                    "總市值(億)": st.column_config.NumberColumn("市值", format="$ %.1f 億"),
                    "收盤價": st.column_config.NumberColumn("收盤價", format="%.2f"),
                }
            )
        else:
            st.info("今日無符合「起漲條件」的股票。")

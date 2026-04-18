import streamlit as st
import shioaji as sj
import pandas as pd
from datetime import datetime, timedelta, date
import time

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

# 嘗試匯入 finlab (回測用)
try:
    import finlab
    from finlab import data
    HAS_FINLAB = True
except ImportError:
    HAS_FINLAB = False

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
        # twstock.codes 包含所有上市櫃股票資訊
        for code, info in twstock.codes.items():
            # info.capital 單位通常是元，我們需要換算
            # 市值 = 股價 * 發行股數
            # 發行股數 = 實收資本額 / 10 (假設面額10元)
            if info.type == "股票" and info.capital:
                # 這裡儲存 "發行股數 (億股)"
                # capital 是資本額(元) -> 除以10變股數 -> 除以1億變億股
                issued_shares_b = (info.capital / 10) / 100000000
                capital_map[code] = issued_shares_b
    except: pass
    return capital_map

def generate_tv_list(df):
    if df is None or df.empty: return ""
    tv_lines = [f"{row.get('市場', 'TWSE')}:{row['代碼']}" for _, row in df.iterrows()]
    return ",".join(tv_lines)

# ==========================================
# 4. 功能引擎 A: 市值排行 Top 50
# ==========================================

def get_top_50_market_cap(api, capital_map):
    status_text = st.empty()
    progress_bar = st.progress(0)

    status_text.text("📥 [市值模式] 正在整理全市場股本資料...")

    # 1. 取得所有上市櫃普通股代碼
    targets = []
    market_label = {}

    # 只抓取有在 twstock 股本清單裡的股票 (過濾權證/ETF)
    valid_codes = set(capital_map.keys())

    for contract in api.Contracts.Stocks.TSE:
        if contract.code in valid_codes:
            targets.append(contract)
            market_label[contract.code] = "TWSE"

    for contract in api.Contracts.Stocks.OTC:
        if contract.code in valid_codes:
            targets.append(contract)
            market_label[contract.code] = "TPEx"

    if not targets:
        st.error("無法取得股票清單。")
        return pd.DataFrame()

    status_text.text(f"🚀 [市值模式] 掃描 {len(targets)} 檔股票最新價格...")

    # 2. 分批抓取即時報價 (Snapshots)
    results = []
    chunk_size = 300
    total_chunks = (len(targets) // chunk_size) + 1

    for idx, i in enumerate(range(0, len(targets), chunk_size)):
        batch = targets[i : i + chunk_size]
        try:
            # 延遲避免 API 過載
            time.sleep(0.1)
            snapshots = api.snapshots(batch)

            for snap in snapshots:
                code = snap.code
                close = getattr(snap, 'close', 0.0)

                # 如果收盤價是 0 (可能暫停交易或錯誤)，跳過
                if close <= 0: continue

                # 計算市值
                shares_b = capital_map.get(code, 0)
                market_cap_b = close * shares_b # 股價 * 億股 = 市值(億)

                results.append({
                    '代碼': code,
                    '名稱': batch[[b.code for b in batch].index(code)].name, # 取得對應名稱
                    '市場': market_label.get(code, "TWSE"),
                    '收盤價': close,
                    '漲跌幅(%)': getattr(snap, 'change_rate', 0.0),
                    '成交量': int(getattr(snap, 'total_volume', 0)),
                    '總市值(億)': market_cap_b
                })
        except Exception as e:
            continue

        progress_bar.progress(min((idx + 1) / total_chunks, 0.9))

    # 3. 排序並取前 50
    status_text.text("📊 正在計算並排序...")
    if results:
        df = pd.DataFrame(results)
        # 依照市值降冪排序
        df = df.sort_values(by='總市值(億)', ascending=False).head(50)
        # 重設排名索引
        df.reset_index(drop=True, inplace=True)
        df.index += 1 # 排名從 1 開始
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
    # (此函式維持您原本的邏輯，精簡顯示以節省篇幅)
    status_text = st.empty()
    progress_bar = st.progress(0)
    status_text.text("📥 [策略模式] 下載全市場清單...")

    contracts = []
    market_map = {}
    for c in api.Contracts.Stocks.TSE: contracts.append(c); market_map[c.code]="TWSE"
    for c in api.Contracts.Stocks.OTC: contracts.append(c); market_map[c.code]="TPEx"

    candidates = []
    chunk_size = 200

    # Step 1: 快篩漲幅與量
    status_text.text("🚀 [策略模式] 執行第一階段快篩...")
    for idx, i in enumerate(range(0, len(contracts), chunk_size)):
        batch = contracts[i : i+chunk_size]
        try:
            time.sleep(0.15)
            snaps = api.snapshots(batch)
            for s in snaps:
                v = getattr(s, 'total_volume', 0)
                c = getattr(s, 'change_rate', 0.0)
                if v > 500 and c >= rise_threshold:
                    candidates.append((s.code, s))
        except: pass
        progress_bar.progress((idx+1)/((len(contracts)//200)+1) * 0.5)

    if not candidates: return pd.DataFrame()

    # Step 2: 技術指標 (30日高 + 爆量)
    status_text.text(f"🔍 [策略模式] 深度分析 {len(candidates)} 檔候選股...")
    final_res = []
    start_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    for idx, (code, snap) in enumerate(candidates):
        try:
            if idx % 20 == 0: time.sleep(0.05)
            contract = api.Contracts.Stocks[code]
            kbars = api.kbars(contract, start=start_date, end=end_date)
            df = pd.DataFrame({**kbars})
            df.ts = pd.to_datetime(df.ts)

            if len(df) >= 30:
                df.Close = df.Close.astype(float); df.Volume = df.Volume.astype(float)
                highest = df.Close.tail(30).max()
                cur_close = df.Close.iloc[-1]
                cur_vol = df.Volume.iloc[-1]
                vol_ma5 = df.Volume.tail(5).mean() or 1

                if cur_close >= highest * 0.95 and cur_vol > vol_ma5 * vol_mul:
                    shares = capital_map.get(code, 0)
                    m_cap = cur_close * shares if shares else None
                    final_res.append({
                        '代碼': code, '名稱': contract.name, '市場': market_map.get(code, "TWSE"),
                        '漲幅(%)': snap.change_rate, '收盤價': cur_close,
                        '成交量': int(snap.total_volume), '5日均量': int(vol_ma5),
                        '總市值(億)': round(m_cap, 1) if m_cap else None
                    })
        except: pass
        progress_bar.progress(0.5 + (0.5 * (idx+1)/len(candidates)))

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(final_res)

# ==========================================
# 6. 主程式 UI 邏輯
# ==========================================

# --- 側邊欄：功能選擇 ---
with st.sidebar:
    st.title("🎛️ 功能選單")

    # 核心模式切換
    mode = st.radio(
        "請選擇執行模式：",
        ["🚀 策略篩選 (起漲)", "🏆 市值排行 Top 50"],
        captions=["尋找爆量突破的股票", "列出全台最大前 50 家公司"]
    )

    st.divider()

    # 根據不同模式顯示不同參數
    if mode == "🚀 策略篩選 (起漲)":
        st.header("⚙️ 篩選參數")
        rise_threshold = st.slider("漲幅門檻 (%)", 0.0, 10.0, 3.0)
        vol_mul = st.number_input("爆量倍數 (vs 5日均量)", 1.5, step=0.1)
    else:
        st.info("ℹ️ 市值排行模式無需設定參數，直接抓取當日最新數據。")

    st.divider()
    run_btn = st.button("開始執行", type="primary")

# --- 主畫面顯示 ---
st.title(f"{mode}")

if run_btn:
    api = get_shioaji_api()
    capital_map = get_stock_capital_map()

    if not api:
        st.stop()

    if mode == "🏆 市值排行 Top 50":
        # 執行市值排行
        df_rank = get_top_50_market_cap(api, capital_map)

        if not df_rank.empty:
            st.success(f"✅ 已列出今日市值最大的 50 檔股票")

            # 顯示漂亮的表格
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
        # 執行策略篩選 (使用當日即時資料)
        df_strat = run_strategy_scanner(api, vol_mul, rise_threshold, capital_map)

        if not df_strat.empty:
            st.success(f"🎯 篩選出 {len(df_strat)} 檔符合條件股票")

            # 下載按鈕
            csv = df_strat.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 下載結果 CSV", csv, "strategy_result.csv", "text/csv")

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

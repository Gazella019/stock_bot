import shioaji as sj
import pandas as pd
from datetime import datetime, timedelta
import time

# --- 1. 使用者設定區 ---
SHIOAJI_API_KEY = "GQdPttVc23aRTA3nERkCLMEfnEsDZ6Q6scYTTXkp1YaW"
SHIOAJI_SECRET_KEY = "CF2dxzYP56htFxJJAadfUecyBQgVMnR8Pk35ykohwqvG"
CA_PATH = "Sinopac.pfx"  # 你的憑證路徑
CA_PASSWORD = "O100435356"
PERSON_ID = "O100435356"

# --- 設定參數 ---
LOOKBACK_DAYS = 60       # 抓歷史資料的天數 (確保能算出30日高點)
VOL_MULTIPLIER = 1.5     # 爆量倍數 (1.5倍)
PRICE_RISE_THRESHOLD = 4 # 漲幅門檻 (%)

def login_shioaji():
    api = sj.Shioaji()
    try:
        api.login(api_key=SHIOAJI_API_KEY, secret_key=SHIOAJI_SECRET_KEY)
        api.activate_ca(ca_path=CA_PATH, ca_passwd=CA_PASSWORD, person_id=PERSON_ID)
        print("✅ Shioaji API 登入與憑證驗證成功！")
        return api
    except Exception as e:
        print(f"❌ 登入失敗: {e}")
        return None

def get_common_stocks(api):
    """
    取得全台上市櫃普通股清單
    過濾掉權證(6碼)、ETF(00開頭)等，只留股票
    """
    print("📥 正在整理全市場股票清單...")
    all_stocks = []
    
    # 遍歷上市(TSE)與上櫃(OTC)
    for market in [api.Contracts.Stocks.TSE, api.Contracts.Stocks.OTC]:
        for contract in market:
            # 簡單過濾：代碼長度為4且是普通股 (SecurityType='CN')
            # Shioaji 的 security_type: 'CN'=普通股, 'ETF'=ETF...
            # 但有時資料欄位不全，用 len(code)==4 是最快過濾權證的方法
            if len(contract.code) == 4: 
                all_stocks.append(contract)
                
    print(f"📊 共篩選出 {len(all_stocks)} 檔普通股。")
    return all_stocks

def analyze_candidate(api, contract, today_snapshot):
    """
    第二階段：針對單一候選股，抓歷史K線進行深度分析
    """
    try:
        # 1. 抓取歷史 K 線
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime('%Y-%m-%d')
        
        # 抓取日K (1T = 1 Day? 不，Shioaji kbars 輸入 '1D' 即可，若用 '1T'是1分K)
        # 注意：Shioaji kbars 通常回傳格式需轉 DF
        kbars = api.kbars(contract=contract, start=start_date, end=end_date)
        df = pd.DataFrame({**kbars})
        df.ts = pd.to_datetime(df.ts)
        
        if len(df) < 30: return None # 資料不足

        # 整理數據
        df['Close'] = df['Close'].astype(float)
        df['Volume'] = df['Volume'].astype(float) # Shioaji Volume 單位通常是 1股 (需確認是張還是股，通常 API 回傳是股/Share)
        
        # 轉換單位：若是股數，轉成張數方便閱讀 (除以1000)
        # 但 Snapshot 的 total_volume 單位通常是「張」，Kbars 可能是「股」
        # 我們統一用相對倍數比較，單位不影響倍數結果
        
        # 取得關鍵數據
        today_close = df['Close'].iloc[-1]
        today_vol = df['Volume'].iloc[-1]
        
        # --- 條件 2: 30日新高檢測 ---
        # 過去 30 天 (不含今天，或者含今天皆可，這裡取含今天的前30筆)
        past_30_days = df['Close'].tail(30)
        highest_30d = past_30_days.max()
        
        # 距離新高 < 5% (也就是股價 >= 95% 的最高價)
        is_near_high = today_close >= (highest_30d * 0.95)
        
        if not is_near_high:
            return None

        # --- 條件 3: 均量爆發檢測 ---
        # 計算 5日 與 20日 均量 (包含今日)
        vol_ma5 = df['Volume'].tail(5).mean()
        vol_ma20 = df['Volume'].tail(20).mean()
        
        # 判斷爆量
        is_vol_spike = (today_vol > vol_ma5 * VOL_MULTIPLIER) or (today_vol > vol_ma20 * VOL_MULTIPLIER)
        
        if is_vol_spike:
            return {
                '代碼': contract.code,
                '名稱': contract.name,
                '收盤價': today_close,
                '漲幅(%)': today_snapshot['change_rate'], # 使用 snapshot 的漲幅比較即時
                '30日最高': highest_30d,
                '成交量(張)': int(today_snapshot['total_volume']), # Snapshot 的量通常是張
                '量能倍數': round(today_vol / vol_ma5, 1)
            }
            
    except Exception as e:
        # print(f"分析錯誤 {contract.code}: {e}") # 除錯用
        return None
    
    return None

def main():
    api = login_shioaji()
    if not api: return

    # 1. 取得所有股票合約
    target_stocks = get_common_stocks(api)
    
    # 2. 第一階段：快篩 (Snapshot)
    # Shioaji Snapshot 有限制一次查詢數量 (建議切分批次，例如一次 200 檔)
    print("\n🚀 開始第一階段快篩：尋找今日強勢股...")
    
    chunk_size = 200
    candidates = [] # 符合第一階段的候選股
    
    for i in range(0, len(target_stocks), chunk_size):
        batch = target_stocks[i : i + chunk_size]
        snapshots = api.snapshots(batch)
        
        for snap in snapshots:
            # snap 欄位: close, open, high, low, change_rate(漲跌幅), total_volume(總量)
            try:
                # 簡單過濾：漲幅 > 3% 且 成交量 > 500張
                # 注意：snap['change_rate'] 單位可能是 % (如 3.5) 或 小數 (0.035)，Shioaji 以前版本回傳 %，需確認
                # 這裡假設回傳的是 % (例如 5.2 代表 5.2%)
                
                # 安全獲取欄位 (有些冷門股可能沒有成交量)
                if snap.total_volume < 500: continue 
                
                if snap.change_rate >= PRICE_RISE_THRESHOLD:
                    candidates.append((snap.code, snap))
            except:
                continue
                
        # 顯示進度
        print(f"  已掃描 {min(i + chunk_size, len(target_stocks))} / {len(target_stocks)} 檔...", end='\r')

    print(f"\n✅ 第一階段完成。共有 {len(candidates)} 檔股票進入複選。")
    print("-" * 30)

    # 3. 第二階段：深度分析 (Kbars)
    print("🔬 開始第二階段：分析 K 線結構 (30日新高 & 均線)...")
    
    final_results = []
    
    for code, snap in candidates:
        # 找回 contract 物件
        contract = api.Contracts.Stocks[code]
        
        result = analyze_candidate(api, contract, snap)
        if result:
            final_results.append(result)
            print(f"  🎯 發現目標: {code} {contract.name} 漲幅:{result['漲幅(%)']}%")
            
        # 稍微暫停避免 API 過熱 (Shioaji 限制較寬鬆，但安全起見)
        time.sleep(0.1)

    # 4. 輸出結果
    api.logout()
    print("\n" + "="*40)
    print("📊 最終篩選結果")
    
    if final_results:
        df_res = pd.DataFrame(final_results)
        df_res = df_res.sort_values(by='漲幅(%)', ascending=False)
        print(df_res[['代碼', '名稱', '收盤價', '漲幅(%)', '30日最高', '成交量(張)', '量能倍數']].to_string(index=False))
        
        # 存檔
        filename = f"Shioaji_Scan_{datetime.now().strftime('%Y%m%d')}.csv"
        df_res.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n📁 結果已儲存至: {filename}")
    else:
        print("今日無符合策略之股票。")

if __name__ == "__main__":
    main()
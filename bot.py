import shioaji as sj
import pandas as pd
from datetime import datetime, timedelta

# --- 1. 使用者設定區 (請務必填寫您的真實資訊) ---

# Shioaji API 設定
SHIOAJI_API_KEY = "GQdPttVc23aRTA3nERkCLMEfnEsDZ6Q6scYTTXkp1YaW"
SHIOAJI_SECRET_KEY = "CF2dxzYP56htFxJJAadfUecyBQgVMnR8Pk35ykohwqvG"

# Shioaji 憑證設定
CA_PATH = "Sinopac.pfx"  # <-- 請填寫您的憑證檔案名稱
CA_PASSWORD = "O100435356" # <-- 請填寫您的憑證密碼
PERSON_ID = "O100435356"     # 請填寫您的身分證字號

# --- 程式碼主體 (執行 API 連線與資料查詢) ---

if __name__ == "__main__":
    print("[系統] 開始執行 Shioaji API 連線測試...")
    
    # 建立 API 物件
    api = sj.Shioaji()

    # 步驟 1: 登入 API 並驗證憑證
    # 這是最關鍵的一步，如果這裡出錯，請仔細檢查上面的設定
    try:
        print("1. 正在登入永豐金 Shioaji API...")
        api.login(
            api_key=SHIOAJI_API_KEY,
            secret_key=SHIOAJI_SECRET_KEY
        )
        print("   登入成功！")
        
        print("2. 正在進行憑證驗證...")
        api.activate_ca(
            ca_path=CA_PATH,
            ca_passwd=CA_PASSWORD,
            person_id=PERSON_ID,
        )
        print("   憑證驗證成功！API 連線已準備就緒。")

    except Exception as e:
        print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!  API 連線失敗！程式已中斷。")
        print(f"!!  錯誤訊息: {e}")
        print("!!  請仔細檢查您在上方設定區填寫的：")
        print("!!  1. API Key / Secret Key 是否複製正確")
        print("!!  2. 憑證路徑 (CA_PATH) 是否正確")
        print("!!  3. 憑證密碼 (CA_PASSWORD) 是否有誤")
        print("!!  4. 身分證字號 (PERSON_ID) 是否正確")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        # 登入失敗就直接結束程式
        exit()

    # 如果程式能走到這裡，代表您的連線是成功的！
    print("-" * 50)
    print("[成功] API 連線與驗證皆已通過！")
    print("-" * 50)

    # 步驟 2: 執行測試範例 - 取得資料
    # 即使股市未開盤，我們仍然可以取得歷史資料或昨日的收盤資訊

    # --- 範例 1：取得台積電 (2330) 最近 5 個交易日的日K線資料 ---
    print("\n--- 範例 1：取得一支股票最近的日 K 線資料 ---")
    try:
        stock_id = "2330"
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=10) # 往前抓10天以確保能蓋到5個交易日

        print(f"正在查詢 {stock_id} 從 {start_date} 到 {end_date} 的日K資料...")
        
        # 呼叫 kbars API 來取得 K 棒資料
        kbars = api.kbars(
            contract=api.Contracts.Stocks[stock_id], 
            start=str(start_date), 
            end=str(end_date),
        )

        # 將回傳的資料轉換成 pandas DataFrame，方便閱讀
        df = pd.DataFrame({**kbars})
        df.ts = pd.to_datetime(df.ts) # 將時間戳轉換成日期格式
        
        print(f"成功取得 {stock_id} 的K線資料：")
        print(df.tail(5)) # 印出最近的5筆資料

    except Exception as e:
        print(f"查詢 K 線資料時發生錯誤: {e}")


    # --- 範例 2：取得多支股票的「當前報價快照」---
    # 在盤後，這會顯示當天的收盤價、成交量等資訊
    print("\n--- 範例 2：取得多支股票的當前報價快照 (Snapshots) ---")
    try:
        stocks_to_query = ["2330", "2317", "2603", "2609"]
        print(f"正在查詢 {stocks_to_query} 的報價快照...")
        
        # 準備要查詢的合約物件列表
        contracts = [api.Contracts.Stocks[sid] for sid in stocks_to_query]
        
        # 呼叫 snapshots API
        snapshots = api.quote.snapshots(contracts)

        # 轉換成 DataFrame
        df_snap = pd.DataFrame(snapshots)
        
        print("成功取得報價快照：")
        print(df_snap[['code', 'close', 'volume', 'ts']]) # 僅顯示部分重要欄位

    except Exception as e:
        print(f"查詢報價快照時發生錯誤: {e}")

    # 步驟 3: 登出 API
    api.logout()
    print("\n[系統] 已登出 API，測試完畢。")
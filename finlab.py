import finlab
from finlab import data
import pandas as pd

try:
    finlab.login()
except Exception:
    pass

print("🚀 開始下載資料...")

# 修正點：使用 '成交股數' 而非 '成交量'
close = data.get('price:收盤價')
vol = data.get('price:成交股數') 

close = close.fillna(method='ffill')
vol = vol.fillna(0)

print("⚡️ 執行策略運算...")

# A. 漲幅 > 3%
cond_rise = close > (close.shift(1) * 1.03)

# B. 30日近高
highest_30d = close.rolling(30).max()
cond_near_high = close >= (highest_30d * 0.95)

# C. 爆量 (成交股數 > 5日均量 * 1.5)
vol_ma5 = vol.rolling(5).mean()
cond_vol_spike = vol > (vol_ma5 * 1.5)

# D. 過濾太小的 (例如 < 500 張 = 500,000 股)
cond_vol_min = vol > 500000

# E. 綜合條件
final_condition = cond_rise & cond_near_high & cond_vol_spike & cond_vol_min

# 驗證
target_date = '2023-05-15' 
try:
    daily_boolean = final_condition.loc[target_date]
    selected_stocks = daily_boolean[daily_boolean].index.tolist()
    
    if selected_stocks:
        print(f"✅ {target_date} 篩選出 {len(selected_stocks)} 檔股票")
        
        report = pd.DataFrame({
            '收盤價': close.loc[target_date, selected_stocks],
            '漲幅(%)': round(((close.loc[target_date, selected_stocks] / close.shift(1).loc[target_date, selected_stocks]) - 1) * 100, 2),
            '成交量(張)': (vol.loc[target_date, selected_stocks] / 1000).astype(int),
            '30日高': highest_30d.loc[target_date, selected_stocks]
        })
        print(report.sort_values(by='漲幅(%)', ascending=False).head(10).to_string())
    else:
        print("無符合條件股票")
except KeyError:
    print(f"查無 {target_date} 資料")
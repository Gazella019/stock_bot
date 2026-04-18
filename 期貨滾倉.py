//@version=5
indicator("大台動態滾倉回測 (200%維持率)", overlay=true, max_labels_count=500)

// === 1. 輸入參數 ===
init_capital = input.float(7400000, title="初始本金 (元)", group="資金與時間設定")
start_year = input.int(2025, title="起始年份", group="資金與時間設定")
start_month = input.int(4, title="起始月份", group="資金與時間設定")
start_day = input.int(30, title="起始日期", group="資金與時間設定")

// === 2. 常數定義 ===
leverage = 17.0             // 原始保證金 = 合約價值 / 17
multiplier = 200.0          // 大台每一點 200 元
mm_ratio = 0.767            // 維持保證金約為原始保證金的 76.7%
target_risk_ratio = 2.0     // 目標維持率 200%

// === 3. 狀態變數 (使用 var 確保數值在 K 棒間傳遞) ===
var float current_capital = init_capital
var int current_contracts = 0
var bool is_active = false
var float margin_call_price = na // 追繳點位變數

// === 4. 時間過濾 ===
start_time = timestamp(start_year, start_month, start_day, 0, 0)
is_active := time >= start_time

// === 5. 核心邏輯與計算 (局部作用域) ===
if is_active
    // A. 計算今日損益 (以昨日留倉的口數計算)
    if is_active[1] and current_contracts[1] > 0
        daily_pnl = (close - close[1]) * multiplier * current_contracts[1]
        current_capital += daily_pnl
        
        // 破產防護：如果本金歸零或變負數，強制出場
        if current_capital <= 0
            current_capital := 0

    // B. 計算今日收盤時的保證金需求
    contract_value = close * multiplier
    IM = contract_value / leverage      // 單口原始保證金
    MM = IM * mm_ratio                  // 單口維持保證金

    // C. 根據 200% 維持率計算目標口數並動態調倉
    if current_capital > 0
        target_contracts = math.floor(current_capital / (IM * target_risk_ratio))
        current_contracts := target_contracts > 0 ? target_contracts : 0
    else
        current_contracts := 0

    // D. 計算明日觸發追繳的紅線點位 (Price Call)
    if current_contracts > 0
        // 公式：容忍跌幅總額 = 目前本金 - (口數 * 維持保證金)
        // 追繳點位 = 收盤價 - (容忍跌幅總額 / (口數 * 200))
        buffer_capital = current_capital - (current_contracts * MM)
        margin_call_price := close - (buffer_capital / (multiplier * current_contracts))
    else
        margin_call_price := na

    // E. 在 K 棒下方標示每日資金與口數
    info_str = str.tostring(math.round(current_capital/10000)) + "萬\n" + str.tostring(current_contracts) + "口"
    label.new(x=bar_index, y=low, text=info_str, yloc=yloc.belowbar, color=color.new(#3977aa, 80), textcolor=color.rgb(0, 0, 0), style=label.style_label_up, size=size.large)

// === 6. 視覺化呈現與資料匯出準備 (必須在全局作用域) ===
// 畫出追繳紅線
plot(margin_call_price, color=color.red, style=plot.style_stepline, linewidth=2, title="追繳紅線")

// 【新增】為了匯出資料，將資金與口數送到數據視窗 (Data Window)，設定 display=display.data_window 使其不在圖表上畫線干擾
plot(current_capital, title="每日總資金", display=display.data_window)
plot(current_contracts, title="每日持倉口數", display=display.data_window)

// 建立右下角狀態面板 (改為 position.bottom_right)
var table info_table = table.new(position.bottom_right, 2, 4, border_width=1)
if barstate.islast
    table.cell(info_table, 0, 0, "最新總資金", bgcolor=color.gray, text_color=color.white)
    table.cell(info_table, 1, 0, str.tostring(math.round(current_capital/10000)) + " 萬", bgcolor=color.black, text_color=color.white)
    
    table.cell(info_table, 0, 1, "當前口數", bgcolor=color.gray, text_color=color.white)
    table.cell(info_table, 1, 1, str.tostring(current_contracts) + " 口", bgcolor=color.black, text_color=color.white)
    
    table.cell(info_table, 0, 2, "追繳點位", bgcolor=color.maroon, text_color=color.white)
    table.cell(info_table, 1, 2, str.tostring(math.round(margin_call_price)), bgcolor=color.red, text_color=color.white)
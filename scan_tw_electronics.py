import yfinance as yf
import pandas as pd
import datetime
import requests
import time

# ==========================================
# 1. 自動取得台股上市與上櫃電子股清單
# ==========================================
def get_tw_electronics_list():
    all_stocks = []
    
    # 爬取上市股票 (TWSE)
    try:
        url_twse = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        res = requests.get(url_twse, timeout=10)
        df = pd.read_html(res.text)[0]
        df.columns = df.iloc[0]
        df = df.iloc[1:]
        
        elec_categories = ['半導體業', '電腦及週邊設備業', '光電業', '通信網路業',
                           '電子零組件業', '電子通路業', '資訊服務業', '其他電子業']
        
        twse_elec = df[df['產業別'].isin(elec_categories)].copy()
        twse_elec['Code'] = twse_elec['有價證券代號及名稱'].str.split('　').str[0]
        
        for _, row in twse_elec.iterrows():
            all_stocks.append([row['Code'] + ".TW", row['產業別'], row['Code'], "上市"])
    except Exception as e:
        print("取得上市股票清單失敗:", e)

    # 爬取上櫃股票 (TPEx)
    try:
        url_tpex = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
        res = requests.get(url_tpex, timeout=10)
        df = pd.read_html(res.text)[0]
        df.columns = df.iloc[0]
        df = df.iloc[1:]
        
        tpex_elec = df[df['產業別'].isin(elec_categories)].copy()
        tpex_elec['Code'] = tpex_elec['有價證券代號及名稱'].str.split('　').str[0]
        
        for _, row in tpex_elec.iterrows():
            all_stocks.append([row['Code'] + ".TWO", row['產業別'], row['Code'], "上櫃"])
    except Exception as e:
        print("取得上櫃股票清單失敗:", e)

    if not all_stocks:
        return [["2330.TW", "半導體業", "2330", "上市"]]
        
    return all_stocks


# ==========================================
# 2. 核心回測邏輯 (盤中觸及即進場)
# ==========================================
def backtest_strategy(df_history, ma_series):
    total_return = 0.0
    trades_count = 0
    success_trades = 0
    in_position = False

    buy_price_raw = 0.0
    buy_date = None
    buy_day_index = -1
    trade_logs = []

    fee_buy = 0.001425
    fee_sell = 0.001425 + 0.003

    start_idx = ma_series.first_valid_index()
    if start_idx is None:
        return -999, 0, 0, []

    subset = df_history.loc[start_idx:]
    ma_subset = ma_series.loc[start_idx:]

    for i in range(len(subset)):
        close = subset['Close'].iloc[i]
        high = subset['High'].iloc[i]
        low = subset['Low'].iloc[i]
        open_p = subset['Open'].iloc[i]
        date = subset.index[i].strftime('%Y-%m-%d')
        ma = ma_subset.iloc[i]
        trigger_buy = ma * 1.015

        if not in_position:
            if high >= trigger_buy and low <= trigger_buy:
                buy_price_raw = trigger_buy
                buy_date = date
                in_position = True
                buy_day_index = i
        else:
            exit_p = None
            if i == buy_day_index + 1 and subset['Close'].iloc[i - 1] < ma_subset.iloc[i - 1]:
                exit_p = open_p
            elif close < ma:
                exit_p = close

            if exit_p is not None:
                cost = buy_price_raw * (1 + fee_buy)
                proceeds = exit_p * (1 - fee_sell)
                trade_ret = (proceeds / cost) - 1

                total_return += trade_ret
                trades_count += 1
                if trade_ret > 0:
                    success_trades += 1

                trade_logs.append({
                    'buy_date': buy_date,
                    'buy_p': round(buy_price_raw, 2),
                    'sell_date': date,
                    'sell_p': round(exit_p, 2),
                    'ret': f"{trade_ret*100:+.2f}%",
                    'is_win': trade_ret > 0
                })
                in_position = False

    win_rate = (success_trades / trades_count * 100 if trades_count > 0 else 0)
    return total_return * 100, win_rate, trades_count, trade_logs


# ==========================================
# 3. 尋找最佳 MA
# ==========================================
def find_best_ma(s_data):
    best_ret = -999999
    best_res = (20, 0, 0, 0, [])
    for ma_len in range(15, 36):
        ma_series = s_data['Close'].rolling(ma_len).mean()
        ret, win, count, logs = backtest_strategy(s_data, ma_series)
        if ret > best_ret:
            best_ret = ret
            best_res = (ma_len, ret, win, count, logs)
    return best_res


# ==========================================
# 4. 主程式
# ==========================================
def main():
    today_dt = datetime.datetime.now() + datetime.timedelta(hours=8)
    print("啟動台股電子股全自動安全掃描儀 (高強度抗崩潰防護版)...")

    ticker_info = get_tw_electronics_list()
    
    industry_map = {x[0]: x[1] for x in ticker_info}
    symbol_map = {x[0]: x[2] for x in ticker_info}
    market_map = {x[0]: x[3] for x in ticker_info}
    
    rows_data = []
    success_count = 0

    print(f"總計獲取 {len(ticker_info)} 檔上市/上櫃電子股標的，開始逐檔安全分析...")

    for item in ticker_info:
        t = item[0]
        try:
            # 1. 下載單檔股票歷史資料
            s_data = yf.download(t, period="3y", auto_adjust=True, progress=False, timeout=10)
            
            # 🛡️ 鋼鐵防護盾：如果 Yahoo 回傳空資料，或格式不對，直接安全跳過，絕對不崩潰
            if s_data is None or s_data.empty or len(s_data) < 40:
                continue
            if 'Volume' not in s_data.columns or 'Close' not in s_data.columns:
                continue

            # 2. 檢查 5 日流動性門檻 (放寬至 2000張 = 2,000,000股)
            avg_vol = s_data['Volume'].tail(5).mean()
            if pd.isna(avg_vol) or avg_vol < 2000000:
                continue

            # 3. 策略與均線計算
            best_ma, ret, win, count, logs = find_best_ma(s_data)
            
            # 確保最後一筆資料有效
            if len(s_data['Close']) < best_ma:
                continue
                
            curr_p = float(s_data['Close'].iloc[-1])
            ma_val = float(s_data['Close'].rolling(best_ma).mean().iloc[-1])
            
            if pd.isna(curr_p) or pd.isna(ma_val) or ma_val == 0:
                continue
                
            diff = (curr_p / ma_val) - 1

            # 4. 嚴格過濾：偏離度正負 1% 內
            if abs(diff) <= 0.01:
                rows_data.append({
                    'symbol': symbol_map[t],
                    'industry': industry_map[t],
                    'market': market_map[t],
                    'best_ma': best_ma,
                    'curr_p': curr_p,
                    'diff_pct': diff * 100,
                    'diff_abs': abs(diff),
                    'ret': ret,
                    'win': win,
                    'count': count,
                    'logs': logs
                })
                success_count += 1
                print(f"🎯 發現符合標的：{symbol_map[t]} (偏離度: {diff*100:+.2f}%)")
                
            # 🕰️ 稍微拉長延遲，溫柔對待 Yahoo 伺服器防封鎖
            time.sleep(0.2)

        except Exception as e:
            print(f"⚠️ 獨立跳過錯誤股票 {t}: {e}")
            continue

    print(f"掃描結束！共有 {success_count} 檔股票符合最新 ±1% 均線條件。")

    # 依據「3Y策略淨利」由大到小排序
    rows_data.sort(key=lambda x: x['ret'], reverse=True)
    
    # 組合 HTML 表格
    table_rows_html = ""
    for idx, r in enumerate(rows_data):
        rank = idx + 1
        ret_color = "#f63538" if r['ret'] > 0 else "#1aa308"
        diff_color = "#ff6b6b" if abs(r['diff_pct']) > 2 else "#2b8a3e"
        market_badge = "bg-dark" if r['market'] == "上市" else "bg-info text-dark"
        
        detail_rows = ""
        for l in r['logs']:
            log_win_class = "table-success" if l['is_win'] else ""
            detail_rows += f"""
            <tr class="{log_win_class}">
                <td>{l['buy_date']}</td>
                <td>{l['buy_p']}</td>
                <td>{l['sell_date']}</td>
                <td>{l['sell_p']}</td>
                <td class="fw-bold">{l['ret']}</td>
            </tr>"""
            
        if not detail_rows:
            detail_rows = """<tr><td colspan="5" class="text-muted">該週期內無平倉交易紀錄</td></tr>"""
        
        table_rows_html += f"""
        <tr>
            <td class="fw-bold text-center text-muted">{rank}</td>
            <td class="fw-bold">{r['symbol']}</td>
            <td class="text-center"><span class="badge {market_badge}">{r['market']}</span></td>
            <td><span class="badge bg-secondary">{r['industry']}</span></td>
            <td class="text-end fw-bold">{r['curr_p']:.2f}</td>
            <td class="text-center fw-bold text-primary">{r['best_ma']} MA</td>
            <td class="text-end fw-bold" style="color: {diff_color};">{r['diff_pct']:+.2f}%</td>
            <td class="text-end fw-bold" style="color: {ret_color}; font-size: 1.1rem;">{r['ret']:+.1f}%</td>
            <td class="text-center">
                <button class="btn btn-xs btn-outline-primary py-0 px-2" style="font-size:0.75rem;" type="button" data-bs-toggle="collapse" data-bs-target="#detail_{r['symbol']}">
                    查看明細 ({r['count']}次)
                </button>
            </td>
        </tr>
        <tr class="collapse" id="detail_{r['symbol']}">
            <td colspan="9" class="bg-light p-3">
                <div class="card p-2 shadow-sm border-0">
                    <h6 class="fw-bold text-secondary mb-2">📊 {r['symbol']} 過去 3 年進出歷史對帳單 (已扣除手續費與證交稅)</h6>
                    <div class="table-responsive" style="max-height: 250px;">
                        <table class="table table-sm table-striped text-center small mb-0">
                            <thead class="table-dark">
                                <tr>
                                    <th>買入日期</th><th>買入價格 (含費)</th>
                                    <th>賣出日期</th><th>賣出價格 (扣費稅)</th>
                                    <th>精算損益</th>
                                </tr>
                            </thead>
                            <tbody>
                                {detail_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </td>
        </tr>
        """

    if not table_rows_html:
        container_content_html = """
        <div class="alert alert-info text-center shadow-sm py-5" role="alert">
            <h4 class="alert-heading mb-3">🔍 今日掃描完成</h4>
            <p class="mb-0 text-muted">目前沒有任何上市/上櫃台股電子股的股價偏離在指定 MA 均線的 <b>±1%</b> 範圍之內。</p>
            <p class="small text-muted mt-2">請靜待下一個交易日收盤後的自動掃描更新。</p>
        </div>
        """
    else:
        container_content_html = f"""
        <div class="card table-card">
            <div class="table-responsive">
                <table class="table table-hover table-bordered mb-0 align-middle">
                    <thead>
                        <tr>
                            <th style="width: 50px;">排行</th>
                            <th style="width: 90px;">股票代號</th>
                            <th style="width: 70px;">市場</th>
                            <th style="width: 140px;">產業別</th>
                            <th style="width: 90px;">目前現價</th>
                            <th style="width: 90px;">最佳均線</th>
                            <th style="width: 100px;">現價偏離度</th>
                            <th style="width: 110px;">3Y策略淨利</th>
                            <th style="width: 110px;">進出明細</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows_html}
                    </tbody>
                </table>
            </div>
        </div>
        """

    base_template = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<title>台股上市櫃電子股均線精選清單</title>
<style>
    body { background-color: #f8f9fa; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
    .main-container { max-width: 1000px; margin-top: 50px; margin-bottom: 50px; }
    .table-card { background: white; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); padding: 25px; border: none; }
    .table th { background-color: #f1f3f5; color: #495057; font-weight: 600; text-align: center; font-size: 0.9rem; }
    .table td { vertical-align: middle; font-size: 0.95rem; }
    .btn-xs { padding: 1px 5px; font-size: 0.75rem; border-radius: 3px; }
</style>
</head>
<body>
<div class="container main-container">
    <div class="text-center mb-4">
        <h2 class="fw-bold text-dark">🇹🇼 台股上市/上櫃電子股均線狙擊監控台</h2>
        <p class="text-muted">更新時間：@UPDATE_TIME@ (嚴格篩選：股價落於最佳 MA <b>±1%</b> 內 | 獨立安全數據源)</p>
    </div>
    
    @CONTAINER_CONTENT@
</div>
</body>
</html>"""

    final_html = base_template.replace("@UPDATE_TIME@", today_dt.strftime('%Y-%m-%d %H:%M')).replace("@CONTAINER_CONTENT@", container_content_html)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"完成！已輸出抗封鎖、高防禦力的 index.html")


if __name__ == "__main__":
    main()

import yfinance as yf
import pandas as pd
import datetime
import requests
import io

# 1. 獲取台股電子類股清單
def get_tw_electronics_list():
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        res = requests.get(url)
        df = pd.read_html(res.text)[0]
        df.columns = df.iloc[0]
        df = df.iloc[1:]
        elec_categories = ['半導體業', '電腦及週邊設備業', '光電業', '通信網路業', '電子零組件業', '電子通路業', '資訊服務業', '其他電子業']
        elec_df = df[df['產業別'].isin(elec_categories)].copy()
        elec_df['Ticker'] = elec_df['有價證券代號及名稱'].str.split('　').str[0] + ".TW"
        return elec_df[['Ticker', '產業別']].values.tolist()
    except:
        return [["2330.TW", "半導體業"]]

# 2. 策略回測邏輯
def backtest_strategy(df_history, ma_series):
    total_return, trades_count, success_trades = 0.0, 0, 0
    in_position = False
    buy_price_raw, buy_date, buy_day_index = 0.0, None, -1
    trade_logs = []
    fee_buy, fee_sell = 0.001425, (0.001425 + 0.003)
    start_idx = ma_series.first_valid_index()
    if start_idx is None: return -999, 0, 0, []
    subset = df_history.loc[start_idx:]
    ma_subset = ma_series.loc[start_idx:]
    for i in range(len(subset)):
        close, high, low, open_p = subset['Close'].iloc[i], subset['High'].iloc[i], subset['Low'].iloc[i], subset['Open'].iloc[i]
        date = subset.index[i].strftime('%Y-%m-%d')
        ma = ma_subset.iloc[i]
        trigger_buy = ma * 1.015
        if not in_position:
            if high > trigger_buy and low <= trigger_buy:
                buy_price_raw, buy_date, in_position, buy_day_index = trigger_buy, date, True, i
                if close < ma: continue
        else:
            exit_p = None
            if i == buy_day_index + 1 and subset['Close'].iloc[i-1] < ma_subset.iloc[i-1]:
                exit_p = open_p
            elif close < ma:
                exit_p = close
            if exit_p is not None:
                cost, proceeds = buy_price_raw * (1 + fee_buy), exit_p * (1 - fee_sell)
                trade_ret = (proceeds / cost) - 1
                total_return += trade_ret
                trades_count += 1
                if trade_ret > 0: success_trades += 1
                trade_logs.append({'buy_date': buy_date, 'buy_p': round(buy_price_raw, 2), 'sell_date': date, 'sell_p': round(exit_p, 2), 'ret': f"{trade_ret*100:+.2f}%", 'is_win': trade_ret > 0})
                in_position = False
    win_rate = (success_trades / trades_count * 100) if trades_count > 0 else 0.0
    return total_return * 100, win_rate, trades_count, trade_logs

def find_best_ma(s_data):
    best_ret = -float('inf')
    best_res = (20, 0, 0, 0, [])
    for ma_len in range(15, 36):
        ma_series = s_data['Close'].rolling(ma_len).mean()
        ret, win, count, logs = backtest_strategy(s_data, ma_series)
        if ret > best_ret:
            best_ret, best_res = ret, (ma_len, ret, win, count, logs)
    return best_res

# 3. 主執行程序
def main():
    today_dt = datetime.datetime.now() + datetime.timedelta(hours=8)
    print("啟動台股全掃描...")
    ticker_info = get_tw_electronics_list()
    tickers = [x[0] for x in ticker_info]
    industry_map = {x[0]: x[1] for x in ticker_info}

    vol_data = yf.download(tickers, period="10d", group_by='ticker', progress=False)
    valid_tickers = [t for t in tickers if t in vol_data and vol_data[t]['Volume'].tail(5).mean() > 3000000]

    print(f"篩選出 {len(valid_tickers)} 檔標的。執行回測中...")
    full_data = yf.download(valid_tickers, period="3y", auto_adjust=True, group_by='ticker', progress=False)
    
    all_cards = []
    for t in valid_tickers:
        try:
            s_data = full_data[t].dropna()
            best_ma, ret, win, count, logs = find_best_ma(s_data)
            curr_p, ma_val = s_data['Close'].iloc[-1], s_data['Close'].rolling(best_ma).mean().iloc[-1]
            diff = (curr_p / ma_val) - 1
            
            if abs(diff) <= 0.01:
                pure_symbol = t.split('.')[0]
                log_rows = "".join([f"<tr class='{'table-success' if l['is_win'] else ''}'><td>{l['buy_date']}</td><td>{l['buy_p']}</td><td>{l['sell_date']}</td><td>{l['sell_p']}</td><td>{l['ret']}</td></tr>" for l in logs])
                
                card_html = f'''
                <div class="card mb-4 shadow">
                    <div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">
                        <div><b>{t}</b> <small>({industry_map[t]})</small> <span class="badge bg-light text-dark ms-2">{best_ma}MA</span></div>
                        <div class="text-end">
                            <small style="color:#90ee90; font-weight:bold;">3Y淨報酬: {ret:+.1f}%</small><br>
                            <small>勝率: {win:.1f}% ({count}次)</small>
                        </div>
                    </div>
                    <div class="card-body">
                        <p><b>{best_ma}MA 偏離:</b> {diff*100:.2f}% | <b>現價:</b> {curr_p:.2f}</p>
                        <button class="btn btn-sm btn-outline-secondary mb-3" type="button" data-bs-toggle="collapse" data-bs-target="#logs_{pure_symbol}">對帳單 ({count}筆)</button>
                        <div class="collapse" id="logs_{pure_symbol}">
                            <div class="table-responsive mb-3" style="max-height: 250px;"><table class="table table-sm small text-center"><thead class="table-light"><tr><th>買入</th><th>價</th><th>賣出</th><th>價</th><th>損益</th></tr></thead><tbody>{log_rows}</tbody></table></div>
                        </div>
                        <div id="tv_{pure_symbol}" style="height:400px;"></div>
                        <script>
                            new TradingView.widget({{
                              "width": "100%", "height": 400, "symbol": "TWSE:{pure_symbol}.TW", "interval": "D",
                              "timezone": "Asia/Taipei", "theme": "light", "style": "1", "locale": "zh_TW",
                              "toolbar_bg": "#f1f3f6", "enable_publishing": false, "hide_top_toolbar": true,
                              "container_id": "tv_{pure_symbol}",
                              "studies": [{{ "id": "MASimple@tv-basicstudies", "inputs": {{ "length": {best_ma} }} }}],
                              "overrides": {{ 
                                "mainSeriesProperties.candleStyle.upColor": "#f63538", "mainSeriesProperties.candleStyle.downColor": "#1aa308",
                                "mainSeriesProperties.candleStyle.borderUpColor": "#f63538", "mainSeriesProperties.candleStyle.borderDownColor": "#1aa308",
                                "mainSeriesProperties.candleStyle.wickUpColor": "#f63538", "mainSeriesProperties.candleStyle.wickDownColor": "#1aa308"
                              }}
                            }});
                        </script>
                    </div>
                </div>'''
                all_cards.append({'ret': ret, 'html': card_html})
        except: continue

    all_cards.sort(key=lambda x: x['ret'], reverse=True)
    
    # --- 關鍵寫入邏輯 ---
    with open("index.html", "w", encoding="utf-8") as f:
        html_content = "".join([c['html'] for c in all_cards])
        f.write(f'''<!DOCTYPE html><html lang="zh-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet"><script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script><script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script><title>台股掃描儀</title></head><body class="bg-light py-5"><div class="container" style="max-width:850px;"><h2 class="text-center mb-4">🇹🇼 台股電子股全自動掃描儀</h2>{html_content}</div></body></html>''')
    print("完成！已產出 index.html。")

if __name__ == "__main__":
    main()

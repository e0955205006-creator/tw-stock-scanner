import yfinance as yf
import pandas as pd
import datetime
import requests
import json

# ==========================================
# 1. 取得台股上市電子股
# ==========================================
def get_tw_electronics_list():
    try:
        url = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
        res = requests.get(url, timeout=10)
        df = pd.read_html(res.text)[0]

        df.columns = df.iloc[0]
        df = df.iloc[1:]

        elec_categories = [
            '半導體業', '電腦及週邊設備業', '光電業', '通信網路業',
            '電子零組件業', '電子通路業', '資訊服務業', '其他電子业'
        ]

        elec_df = df[df['產業別'].isin(elec_categories)].copy()
        elec_df['Code'] = elec_df['有價證券代號及名稱'].str.split('　').str[0]
        elec_df['Ticker'] = elec_df['Code'] + ".TW"
        
        # 修正：配合您測試成功的格式，全面改為 TAIEX-代號 (例如 TAIEX-2308)
        elec_df['TVSymbol'] = "TAIEX-" + elec_df['Code']

        return elec_df[['Ticker', '產業別', 'TVSymbol']].values.tolist()
    except Exception as e:
        print("取得股票清單失敗:", e)
        return [["2330.TW", "半導體業", "TAIEX-2330"]]


# ==========================================
# 2. 回測策略
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
            if high > trigger_buy and low <= trigger_buy:
                buy_price_raw = trigger_buy
                buy_date = date
                in_position = True
                buy_day_index = i
                if close < ma:
                    continue
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
    print("啟動台股電子股掃描儀 (TAIEX-連字號最佳化版)...")

    ticker_info = get_tw_electronics_list()
    tickers = [x[0] for x in ticker_info]
    industry_map = {x[0]: x[1] for x in ticker_info}
    tvsymbol_map = {x[0]: x[2] for x in ticker_info}

    print("下載成交量資料...")
    vol_data = yf.download(
        tickers,
        period="10d",
        group_by='ticker',
        auto_adjust=True,
        progress=False,
        threads=True
    )

    valid_tickers = []
    for t in tickers:
        try:
            if t not in vol_data:
                continue
            avg_vol = vol_data[t]['Volume'].tail(5).mean()
            if avg_vol > 3000000:
                valid_tickers.append(t)
        except:
            continue

    print(f"符合條件股票數量: {len(valid_tickers)}")
    print("下載歷史K線資料...")

    full_data = yf.download(
        valid_tickers,
        period="3y",
        auto_adjust=True,
        group_by='ticker',
        progress=False,
        threads=True
    )

    all_cards = []

    for t in valid_tickers:
        try:
            s_data = full_data[t].dropna()
            if len(s_data) < 200:
                continue

            best_ma, ret, win, count, logs = find_best_ma(s_data)
            curr_p = s_data['Close'].iloc[-1]
            ma_val = s_data['Close'].rolling(best_ma).mean().iloc[-1]
            diff = (curr_p / ma_val) - 1

            if abs(diff) <= 0.01:
                pure_symbol = t.split('.')[0]
                tv_symbol = tvsymbol_map[t]

                log_rows = ""
                for l in logs:
                    row_class = "table-success" if l['is_win'] else ""
                    log_rows += f"""
                    <tr class='{row_class}'>
                        <td>{l['buy_date']}</td>
                        <td>{l['buy_p']}</td>
                        <td>{l['sell_date']}</td>
                        <td>{l['sell_p']}</td>
                        <td>{l['ret']}</td>
                    </tr>"""

                card_template = """
                <div class="card mb-4 shadow">
                    <div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">
                        <div>
                            <b>@TICKER@</b>
                            <small>(@INDUSTRY@)</small>
                            <span class="badge bg-light text-dark ms-2">@BEST_MA@MA</span>
                        </div>
                        <div class="text-end">
                            <small style="color:#90ee90; font-weight:bold;">3Y淨報酬: @RET@%</small><br>
                            <small>勝率: @WIN@% (@COUNT@次)</small>
                        </div>
                    </div>
                    <div class="card-body">
                        <p><b>@BEST_MA@MA 偏離:</b> @DIFF@% | <b>現價:</b> @CURR_P@</p>
                        <button class="btn btn-sm btn-outline-secondary mb-3" type="button" data-bs-toggle="collapse" data-bs-target="#logs_@PURE_SYMBOL@">
                            對帳單 (@COUNT@次)
                        </button>
                        <div class="collapse" id="logs_@PURE_SYMBOL@">
                            <div class="table-responsive mb-3" style="max-height:250px;">
                                <table class="table table-sm small text-center">
                                    <thead class="table-light">
                                        <tr>
                                            <th>買入日期</th><th>買入價</th><th>賣出日期</th><th>賣出價</th><th>損益</th>
                                        </tr>
                                    </thead>
                                    <tbody>@LOG_ROWS@</tbody>
                                </table>
                            </div>
                        </div>
                        <button class="btn btn-sm btn-success mb-3" onclick="loadChart_@PURE_SYMBOL@()">載入圖表</button>
                        <div id="wrapper_@PURE_SYMBOL@" style="height:400px; width:100%; border:1px solid #eee;"></div>
                        <script>
                        let loaded_@PURE_SYMBOL@ = false;
                        function loadChart_@PURE_SYMBOL@() {
                            if (loaded_@PURE_SYMBOL@) return;
                            loaded_@PURE_SYMBOL@ = true;
                            new TradingView.widget({
                                "width": "100%",
                                "height": 400,
                                "symbol": "@TV_SYMBOL@",
                                "interval": "D",
                                "timezone": "Asia/Taipei",
                                "theme": "light",
                                "style": "1",
                                "locale": "zh_TW",
                                "toolbar_bg": "#f1f3f6",
                                "enable_publishing": false,
                                "hide_top_toolbar": true,
                                "hide_legend": false,
                                "save_image": false,
                                "container_id": "wrapper_@PURE_SYMBOL@",
                                "studies": [
                                    {
                                        "id": "MASimple@tv-basicstudies",
                                        "inputs": { "length": @BEST_MA_INT@ }
                                    }
                                ],
                                "overrides": {
                                    "mainSeriesProperties.candleStyle.upColor": "#f63538",
                                    "mainSeriesProperties.candleStyle.downColor": "#1aa308",
                                    "mainSeriesProperties.candleStyle.borderUpColor": "#f63538",
                                    "mainSeriesProperties.candleStyle.borderDownColor": "#1aa308",
                                    "mainSeriesProperties.candleStyle.wickUpColor": "#f63538",
                                    "mainSeriesProperties.candleStyle.wickDownColor": "#1aa308"
                                }
                            });
                        }
                        </script>
                    </div>
                </div>
                """
                
                filled_html = (card_template
                    .replace("@TICKER@", str(t))
                    .replace("@INDUSTRY@", str(industry_map[t]))
                    .replace("@BEST_MA@", str(best_ma))
                    .replace("@BEST_MA_INT@", str(int(best_ma)))
                    .replace("@RET@", f"{ret:+.1f}")
                    .replace("@WIN@", f"{win:.1f}")
                    .replace("@COUNT@", str(count))
                    .replace("@DIFF@", f"{diff*100:.2f}")
                    .replace("@CURR_P@", f"{curr_p:.2f}")
                    .replace("@PURE_SYMBOL@", str(pure_symbol))
                    .replace("@LOG_ROWS@", log_rows)
                    .replace("@TV_SYMBOL@", str(tv_symbol))
                )

                all_cards.append({
                    'ret': ret,
                    'html': filled_html
                })
        except Exception as e:
            print(f"{t} 發生錯誤:", e)
            continue

    all_cards.sort(key=lambda x: x['ret'], reverse=True)
    html_cards = "".join([c['html'] for c in all_cards])

    base_template = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
<title>台股電子股掃描儀</title>
</head>
<body class="bg-light py-5">
<div class="container" style="max-width:850px;">
    <h2 class="text-center mb-4">🇹🇼 台股電子股全自動掃描儀</h2>
    <p class="text-center text-muted mb-4">更新時間：@UPDATE_TIME@</p>
    @HTML_CARDS@
</div>
</body>
</html>"""

    final_html = base_template.replace("@UPDATE_TIME@", today_dt.strftime('%Y-%m-%d %H:%M')).replace("@HTML_CARDS@", html_cards)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(final_html)

    print("完成！已輸出 index.html")


if __name__ == "__main__":
    main()

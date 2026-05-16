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
            '電子零組件業', '電子通路業', '資訊服務業', '其他電子業'
        ]

        elec_df = df[df['產業別'].isin(elec_categories)].copy()
        elec_df['Code'] = elec_df['有價證券代號及名稱'].str.split('　').str[0]
        elec_df['Ticker'] = elec_df['Code'] + ".TW"

        return elec_df[['Ticker', '產業別', 'Code']].values.tolist()
    except Exception as e:
        print("取得股票清單失敗:", e)
        return [["2330.TW", "半導體業", "2330"]]


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
    print("啟動台股電子股掃描儀 (Lightweight Charts 版)...")

    ticker_info = get_tw_electronics_list()
    tickers = [x[0] for x in ticker_info]
    industry_map = {x[0]: x[1] for x in ticker_info}

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
            
            # 計算最佳 MA 序列
            ma_series = s_data['Close'].rolling(best_ma).mean()
            ma_val = ma_series.iloc[-1]
            diff = (curr_p / ma_val) - 1

            if abs(diff) <= 0.01:
                pure_symbol = t.split('.')[0]

                # 準備要餵給 Lightweight Charts 的資料 (過去120天，避免資料量過大卡頓)
                chart_subset = s_data.tail(120)
                ma_subset = ma_series.tail(120)
                
                ohlc_list = []
                ma_list = []
                for idx, row in chart_subset.iterrows():
                    time_str = idx.strftime('%Y-%m-%d')
                    ohlc_list.append({
                        "time": time_str,
                        "open": float(row['Open']),
                        "high": float(row['High']),
                        "low": float(row['Low']),
                        "close": float(row['Close'])
                    })
                    if not pd.isna(ma_subset.loc[idx]):
                        ma_list.append({
                            "time": time_str,
                            "value": float(ma_subset.loc[idx])
                        })

                # 將資料序列化為 JSON 字串
                ohlc_json = json.dumps(ohlc_list)
                ma_json = json.dumps(ma_list)

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

                card_html = f"""
                <div class="card mb-4 shadow">
                    <div class="card-header bg-primary text-white d-flex justify-content-between align-items-center">
                        <div>
                            <b>{t}</b>
                            <small>({industry_map[t]})</small>
                            <span class="badge bg-light text-dark ms-2">
                                {best_ma}MA
                            </span>
                        </div>
                        <div class="text-end">
                            <small style="color:#90ee90; font-weight:bold;">
                                3Y淨報酬: {ret:+.1f}%
                            </small>
                            <br>
                            <small>
                                勝率: {win:.1f}% ({count}次)
                            </small>
                        </div>
                    </div>

                    <div class="card-body">
                        <p>
                            <b>{best_ma}MA 偏離:</b> {diff*100:.2f}% | <b>現價:</b> {curr_p:.2f}
                        </p>

                        <button
                            class="btn btn-sm btn-outline-secondary mb-3"
                            type="button"
                            data-bs-toggle="collapse"
                            data-bs-target="#logs_{pure_symbol}"
                        >
                            對帳單 ({count}筆)
                        </button>

                        <div class="collapse" id="logs_{pure_symbol}">
                            <div class="table-responsive mb-3" style="max-height:250px;">
                                <table class="table table-sm small text-center">
                                    <thead class="table-light">
                                        <tr>
                                            <th>買入日期</th>
                                            <th>買入價</th>
                                            <th>賣出日期</th>
                                            <th>賣出價</th>
                                            <th>損益</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {log_rows}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <button
                            class="btn btn-sm btn-success mb-3"
                            onclick="loadChart_{pure_symbol}()"
                        >
                            載入圖表
                        </button>

                        <div id="chart_{pure_symbol}" style="height:400px; width:100%; border:1px solid #eee; background-color: #fff;"></div>

                        <script>
                        let loaded_{pure_symbol} = false;
                        function loadChart_{pure_symbol}() {{
                            if (loaded_{pure_symbol}) return;
                            loaded_{pure_symbol} = true;

                            const chartContainer = document.getElementById('chart_{pure_symbol}');
                            const chart = LightweightCharts.createChart(chartContainer, {{
                                width: chartContainer.clientWidth,
                                height: 400,
                                layout: {{ backgroundColor: '#ffffff', textColor: '#333' }},
                                grid: {{ vertLines: {{ color: '#f0f0f0' }}, horzLines: {{ color: '#f0f0f0' }} }},
                                crosshair: {{ mode: LightweightCharts.CrosshairMode.Normal }},
                                priceScale: {{ borderColor: '#cccccc' }},
                                timeScale: {{ borderColor: '#cccccc' }},
                            }});

                            // 建立 K 線序列 (設定台股紅漲綠跌習慣)
                            const candlestickSeries = chart.addCandlestickSeries({{
                                upColor: '#f63538',
                                downColor: '#1aa308',
                                borderUpColor: '#f63538',
                                borderDownColor: '#1aa308',
                                wickUpColor: '#f63538',
                                wickDownColor: '#1aa308',
                            }});

                            // 餵入 Python 準備好的純原生 K 線資料
                            const rawData = {ohlc_json};
                            candlestickSeries.setData(rawData);

                            // 建立並繪製 Python 幫忙寻优出来的最佳 MA 均線
                            const maSeries = chart.addLineSeries({{
                                color: '#2196F3',
                                lineWidth: 2,
                                title: '{best_ma}MA'
                            }});
                            const maData = {ma_json};
                            maSeries.setData(maData);

                            // 響應式視窗縮放
                            window.addEventListener('resize', () => {{
                                chart.resize(chartContainer.clientWidth, 400);
                            }});
                        }}
                        </script>
                    </div>
                </div>
                """
                all_cards.append({
                    'ret': ret,
                    'html': card_html
                })
        except Exception as e:
            print(f"{t} 發生錯誤:", e)
            continue

    all_cards.sort(key=lambda x: x['ret'], reverse=True)
    html_cards = "".join([c['html'] for c in all_cards])

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
<title>台股電子股掃描儀</title>
</head>
<body class="bg-light py-5">
<div class="container" style="max-width:850px;">
    <h2 class="text-center mb-4">🇹🇼 台股電子股全自動掃描儀</h2>
    <p class="text-center text-muted mb-4">更新時間：{today_dt.strftime('%Y-%m-%d %H:%M')}</p>
    {html_cards}
</div>
</body>
</html>""")

    print("完成！已輸出 index.html")


if __name__ == "__main__":
    main()

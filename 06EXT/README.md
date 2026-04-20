PyPi Version Supported Python versions Downloads Downloads
Overview

pip install tradingview-screener

tradingview-screener is a Python package that allows you to create custom stock screeners using TradingView's official API. This package retrieves data directly from TradingView without the need for web scraping or HTML parsing.
Key Features

    Markets: Stocks, crypto, forex, CFDs, futures, bonds, and more.
    3000+ Data Fields: OHLC data, technical indicators, fundamental metrics (e.g. P/E, EPS), and even internal TradingView-only fields.
    Timeframes: Use 1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w, and 1mo — freely mix timeframes per field, no subscription required.
    Filtering: SQL-like syntax with full support for AND/OR logic.

Links

    GitHub Repository
    Documentation
    Fields
    Screeners

Note that throughout the documentation, "field" and "column" are used interchangeably. Same with "Scanner" and "Screener".
Quickstart

Here’s a simple example to get you started:

from tradingview_screener import Query

x = (Query()
 .select('name', 'close', 'volume', 'market_cap_basic')
 .get_scanner_data())
print(x)

Output:

(17580,
          ticker  name   close     volume  market_cap_basic
 0   NASDAQ:NVDA  NVDA  127.25  298220762      3.130350e+12
 1      AMEX:SPY   SPY  558.70   33701795               NaN
 2   NASDAQ:TSLA  TSLA  221.10   73869589      7.063350e+11
 3    NASDAQ:QQQ   QQQ  480.26   29102854               NaN
 4    NASDAQ:AMD   AMD  156.40   76693809      2.531306e+11
 ..          ...   ...     ...        ...               ...
 45   NASDAQ:PDD   PDD  144.22    8653323      2.007628e+11
 46     NYSE:JPM   JPM  214.52    5639973      6.103447e+11
 47     NYSE:JNJ   JNJ  160.16    7274621      3.855442e+11
 48  NASDAQ:SQQQ  SQQQ    7.99  139721164               NaN
 49  NASDAQ:ASTS  ASTS   34.32   32361315      9.245616e+09

 [50 rows x 5 columns])

By default, the result is limited to 50 rows. You can adjust this limit, but be mindful of server load and potential bans.

A more advanced query:

from tradingview_screener import Query, col

(Query()
 .select('name', 'close', 'close|1', 'close|5', 'volume', 'relative_volume_10d_calc')
 .where(
     col('market_cap_basic').between(1_000_000, 50_000_000),
     col('relative_volume_10d_calc') > 1.2,
     col('MACD.macd|1') >= col('MACD.signal|1')  # 1 minute MACD
 )
 .order_by('volume', ascending=False)
 .offset(5)
 .limit(25)
 .get_scanner_data())


Note that some fields (usually prices and indicators) have multiple timeframes that you can choose from, for example:
Timeframe 	Column
1 Minute 	close\|1
5 Minutes 	close\|5
15 Minutes 	close\|15
30 Minutes 	close\|30
1 Hour 	close\|60
2 Hours 	close\|120
4 Hours 	close\|240
1 Day 	close
1 Week 	close\|1W
1 Month 	close\|1M
Real-Time Data Access

To access real-time data, you need to pass your session cookies, as even free real-time data requires authentication.
Verify Update Mode

You can run this query to get an overview on the update_mode you get for each exchange:

from tradingview_screener import Query

_, df = Query().select('exchange', 'update_mode').limit(1_000_000).get_scanner_data()
df = df.groupby('exchange')['update_mode'].value_counts()
print(df)

exchange  update_mode          
AMEX      delayed_streaming_900    3255
NASDAQ    delayed_streaming_900    4294
NYSE      delayed_streaming_900    2863
OTC       delayed_streaming_900    7129

Using rookiepy

rookiepy is a library that loads the cookies from your local browser. So if you are logged in on Chrome (or whatever browser you use), it will use the same session.

    Install rookiepy:

    bash pip install rookiepy

    Load the cookies:

    python import rookiepy cookies = rookiepy.to_cookiejar(rookiepy.chrome(['.tradingview.com'])) # replace chrome() with your browser

    Pass the cookies when querying:

    python Query().get_scanner_data(cookies=cookies)

Now, if you re-run the update mode check:

_, df = Query().select('exchange', 'update_mode').limit(1_000_000).get_scanner_data(cookies=cookies)
df = df.groupby('exchange')['update_mode'].value_counts()
print(df)

exchange  update_mode          
AMEX      streaming                3256
NASDAQ    streaming                4286
NYSE      streaming                2860
OTC       delayed_streaming_900    7175

We now get live-data for all exchanges except OTC (because my subscription dosent include live-data for OTC tickers).
Other Ways For Loading Cookies
Extract Cookies Manually
Authenticate via API

Comparison to Similar Packages

Unlike other Python libraries that have specific features like extracting the sentiment, or what not. This package is but a (low-level) wrapper around TradingView's /screener API endpoint.

It merely documents the endpoint, by listing all the functions and operations available, the different fields you can use, the markets, instruments (even some that you wont find on TradingView's website), and so on.

This library is also a wrapper that makes it easier to generate those verbose JSON payloads.
Robustness & Longevity

This package is designed to be future-proof. There are no hard-coded values in the package, all fields/columns and markets are documented on the website, which is updated daily via a GitHub Actions script.
How It Works

When using methods like select() or where(), the Query object constructs a dictionary representing the API request. Here’s an example of the dictionary generated:

{
    'markets': ['america'],
    'symbols': {'query': {'types': []}, 'tickers': []},
    'options': {'lang': 'en'},
    'columns': ['name', 'close', 'volume', 'relative_volume_10d_calc'],
    'sort': {'sortBy': 'volume', 'sortOrder': 'desc'},
    'range': [5, 25],
    'filter': [
        {'left': 'market_cap_basic', 'operation': 'in_range', 'right': [1000000, 50000000]},
        {'left': 'relative_volume_10d_calc', 'operation': 'greater', 'right': 1.2},
        {'left': 'MACD.macd', 'operation': 'egreater', 'right': 'MACD.signal'},
    ],
}

The get_scanner_data() method sends this dictionary as a JSON payload to the TradingView API, allowing you to query data using SQL-like syntax without knowing the specifics of the API.
Feedback and Improvement

If this package has bought value to your projects, please consider starring it.
Stargazers over time

Stargazers over time
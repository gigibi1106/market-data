#!/usr/bin/env python3
"""
每日盤前市場數據抓取腳本
GitHub Actions 於台灣時間清晨執行，供 iPhone 捷徑「投資每日數據」朗讀
"""
import requests
import json
import re
from datetime import datetime, timezone, timedelta

TW_TZ = timezone(timedelta(hours=8))
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def _tag_text(html, element_id):
    """取出 id=element_id 元素內的純文字（去掉巢狀 span）"""
    m = re.search(rf'id="{element_id}"[^>]*>(.*?)</span></span>', html, re.S)
    if not m:
        m = re.search(rf'id="{element_id}"[^>]*>(.*?)</span>', html, re.S)
    if not m:
        return ''
    return re.sub(r'<[^>]+>', '', m.group(1)).strip()


def get_sgx_taiwan():
    """從 HiStock 抓富台期 (TWN) 即時報價。失敗回 None，絕不回 0。"""
    try:
        r = requests.get('https://histock.tw/index-tw/TWN',
                         headers={'User-Agent': UA}, timeout=20)
        r.raise_for_status()
        html = r.text

        # 2026-11-26 HiStock 改版成 Next.js，舊的 Price1_lbTPrice 等 id 已消失。
        # 改讀 <meta name="description">：「富台期 (TWN) 期貨, 指數 3351.5, 漲跌 -1.8, ...」
        m = re.search(r'指數\s*([\d,]+\.?\d*)\s*,\s*漲跌\s*([+\-]?[\d,]+\.?\d*)', html)
        if m:
            price = float(m.group(1).replace(',', ''))
            chg = float(m.group(2).replace(',', ''))
            pct = 0.0
            time_s = ''
        else:
            # 舊版頁面備援
            price_s = _tag_text(html, 'Price1_lbTPrice')
            chg_s   = _tag_text(html, 'Price1_lbTChange')
            pct_s   = _tag_text(html, 'Price1_lbTPercent')
            time_s  = _tag_text(html, 'Price1_lbLocalTime')
            price = float(price_s.replace(',', ''))
            chg = float(re.sub(r'[^\d.]', '', chg_s) or 0)
            if '▼' in chg_s or '-' in chg_s:
                chg = -chg
            pct = float(re.sub(r'[^\d.\-]', '', pct_s) or 0)
            if '▼' in pct_s or pct_s.strip().startswith('-'):
                pct = -abs(pct)

        # 合理性檢查：富台期正常在 1000~20000 之間，抓到 0 或離譜值視為失敗
        if not 1000 < price < 20000:
            print(f"SGX Taiwan: 價格不合理 ({price})，視為抓取失敗")
            return None

        prev = round(price - chg, 2)
        if pct == 0 and prev:
            pct = round(chg / prev * 100, 2)

        print(f"SGX Taiwan (histock): price={price} chg={chg} pct={pct}% 報價時間={time_s}")
        return {'price': price, 'prev': prev, 'chg_pct': pct, 'quote_time': time_s}
    except Exception as e:
        print(f"SGX Taiwan error: {e}")
        return None


def get_txf_night():
    """從期交所 MIS 抓台指期近月「盤後(夜盤)」報價。失敗回 None，絕不回 0。

    夜盤 15:00～次日 05:00；05:00 收盤後到下午 15:00 前查到的就是昨晚夜盤收盤。
    CRefPrice 是夜盤參考價（＝日盤收盤/結算），CDiff/CDiffRate 是相對它的漲跌。
    """
    try:
        r = requests.post(
            'https://mis.taifex.com.tw/futures/api/getQuoteList',
            json={'MarketType': '1', 'SymbolType': 'F', 'KindID': '1', 'CID': 'TXF',
                  'ExpireMonth': '', 'RowSize': '全部', 'PageNo': '',
                  'SortColumn': '', 'AscDesc': 'A'},
            headers={'User-Agent': UA}, timeout=20)
        r.raise_for_status()
        quotes = r.json()['RtData']['QuoteList']
        # 第一筆 TXF-P 是現貨指數，近月合約是第一個以 -M 結尾的
        q = next(x for x in quotes if x['SymbolID'].endswith('-M'))

        price = float(q['CLastPrice'])
        ref   = float(q['CRefPrice'])
        diff  = float(q['CDiff'])
        pct   = float(q['CDiffRate'])
        t     = q.get('CTime', '')

        if not 5000 < price < 200000:
            print(f"台指夜盤: 價格不合理 ({price})，視為抓取失敗")
            return None

        # 05:00 收盤後才算「收盤價」，否則（例如排程延遲到 15:00 後）是盤中價
        closed = bool(t) and '045500' <= t <= '150000'
        result = {'price': price, 'ref': ref, 'diff': diff, 'chg_pct': pct,
                  'contract': q['DispEName'], 'quote_time': t, 'closed': closed}
        print(f"台指夜盤 (taifex): {result}")
        return result
    except Exception as e:
        print(f"台指夜盤 error: {e}")
        return None


def get_cnbc(symbol):
    """從 CNBC 報價 API 取得價格與漲跌幅（免金鑰）。失敗回 None。"""
    try:
        r = requests.get(
            'https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol',
            params={'symbols': symbol, 'requestMethod': 'itv', 'noform': '1',
                    'partnerId': '2', 'fund': '1', 'exthrs': '1',
                    'output': 'json', 'events': '1'},
            headers={'User-Agent': UA}, timeout=20)
        r.raise_for_status()
        q = r.json()['FormattedQuoteResult']['FormattedQuote'][0]
        if q.get('code') != 0:
            print(f"CNBC {symbol}: 查無此代碼")
            return None

        price = float(str(q['last']).replace(',', ''))
        pct   = float(str(q.get('change_pct', '0')).replace('%', '').replace('+', '') or 0)
        if price <= 0:
            print(f"CNBC {symbol}: 價格為 0，視為抓取失敗")
            return None

        result = {'price': round(price, 2), 'chg_pct': round(pct, 2)}
        print(f"CNBC {symbol}: {result} 報價時間={q.get('last_timedate')}")
        return result
    except Exception as e:
        print(f"CNBC {symbol} error: {e}")
        return None


def get_yahoo(ticker):
    """Yahoo Finance v8 API 備援。失敗回 None。

    Yahoo 近期常對雲端 IP 直接回 429，所以只當第二順位，query1/query2 各試一次。
    """
    for host in ('query1', 'query2'):
        try:
            url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{ticker}'
            r = requests.get(url, headers={'User-Agent': UA}, timeout=15)
            r.raise_for_status()
            m = r.json()['chart']['result'][0]['meta']
            now  = float(m.get('regularMarketPrice') or 0)
            prev = float(m.get('chartPreviousClose') or m.get('previousClose') or 0)
            if now <= 0:
                print(f"Yahoo {ticker} ({host}): 價格為 0，視為抓取失敗")
                continue
            pct = m.get('regularMarketChangePercent')
            if pct is None and prev:
                pct = (now - prev) / prev * 100
            result = {'price': round(now, 2), 'chg_pct': round(float(pct or 0), 2)}
            print(f"Yahoo {ticker} ({host}): {result}")
            return result
        except Exception as e:
            print(f"Yahoo {ticker} ({host}) error: {e}")
    return None


def get_quote(cnbc_symbol, yahoo_ticker):
    """CNBC 為主、Yahoo 為備援"""
    return get_cnbc(cnbc_symbol) or get_yahoo(yahoo_ticker)


def direction(pct):
    if pct > 0.05:
        return f'上漲 {abs(pct):.2f}%'
    elif pct < -0.05:
        return f'下跌 {abs(pct):.2f}%'
    else:
        return '持平'


def main():
    sgx  = get_sgx_taiwan()
    txn  = get_txf_night()
    gold = get_quote('@GC.1', 'GC=F')    # COMEX 黃金期貨
    oil  = get_quote('@CL.1', 'CL=F')    # WTI 原油期貨
    vix  = get_quote('.VIX', '%5EVIX')   # CBOE 波動率指數

    now_tw = datetime.now(TW_TZ)
    today  = now_tw.strftime('%-m月%-d日')

    parts = [f"早安，今天是{today}，盤前市場快報。"]

    if sgx:
        parts.append(f" 新加坡富台指數 {sgx['price']:.0f} 點，{direction(sgx['chg_pct'])}。")
    else:
        parts.append(" 富台指數暫時抓不到資料。")

    if txn:
        verb = '收' if txn['closed'] else '目前'
        if abs(txn['chg_pct']) <= 0.05:
            move = '跟日盤收盤差不多'
        else:
            word = '上漲' if txn['diff'] > 0 else '下跌'
            move = f"比日盤收盤{word} {abs(txn['diff']):.0f} 點、{abs(txn['chg_pct']):.2f}%"
        parts.append(f" 台指期夜盤{verb} {txn['price']:.0f} 點，{move}。")
    else:
        parts.append(" 台指期夜盤暫時抓不到資料。")

    if gold:
        parts.append(f" 黃金每盎司 {gold['price']:.0f} 美元，{direction(gold['chg_pct'])}。")
    else:
        parts.append(" 黃金暫時抓不到資料。")

    if oil:
        parts.append(f" WTI 原油每桶 {oil['price']:.1f} 美元，{direction(oil['chg_pct'])}。")
    else:
        parts.append(" 原油暫時抓不到資料。")

    if vix:
        vix_level = ('偏高，市場恐慌' if vix['price'] >= 25
                     else '正常' if vix['price'] >= 15
                     else '偏低，市場樂觀')
        parts.append(f" VIX 恐慌指數 {vix['price']:.1f}，{direction(vix['chg_pct'])}，目前{vix_level}。")
    else:
        parts.append(" VIX 恐慌指數暫時抓不到資料。")

    parts.append(" 以上是今日盤前快報，祝交易順利。")
    speech = ''.join(parts)

    result = {
        'updated_at': now_tw.strftime('%Y-%m-%d %H:%M TW'),
        'data_date':  now_tw.strftime('%Y-%m-%d'),
        'speech': speech,
        'sgx_taiwan': sgx,
        'txf_night':  txn,
        'gold':       gold,
        'oil':        oil,
        'vix':        vix,
    }

    with open('market-data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n播報文字：\n{speech}")

    # 五項全掛才讓 Actions 顯示失敗（單項失效仍要產出當日檔案）
    if not any([sgx, txn, gold, oil, vix]):
        raise SystemExit("所有資料源都抓取失敗")


if __name__ == '__main__':
    main()

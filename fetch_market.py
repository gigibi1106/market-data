#!/usr/bin/env python3
"""
每日盤前市場數據抓取腳本
GitHub Actions 每天 08:45 台灣時間執行
"""
import requests
import json
import re
import os
from datetime import datetime, timezone, timedelta

FIRECRAWL_API_KEY = os.environ['FIRECRAWL_API_KEY']
TW_TZ = timezone(timedelta(hours=8))


def get_sgx_taiwan():
    """用 Firecrawl stealth 抓玩股網富台指數"""
    try:
        r = requests.post(
            'https://api.firecrawl.dev/v1/scrape',
            headers={'Authorization': f'Bearer {FIRECRAWL_API_KEY}'},
            json={
                'url': 'https://www.wantgoo.com/global/stwn&',
                'formats': ['json'],
                'jsonOptions': {
                    'prompt': '從頁面提取富台指數(STWN)的最新價格(price)、昨收(prev_close)、漲跌幅百分比(change_pct，正數為漲、負數為跌)。回傳 JSON。'
                },
                'proxy': 'stealth',
                'waitFor': 8000
            },
            timeout=90
        )
        data = r.json().get('data', {}).get('json', {})
        price   = float(data.get('price') or 0)
        prev    = float(data.get('prev_close') or data.get('previousClose') or 0)
        chg_pct = float(data.get('change_pct') or data.get('changePercent') or 0)

        if chg_pct == 0 and prev and abs(price - prev) > 0.01:
            chg_pct = round((price - prev) / prev * 100, 2)

        print(f"SGX Taiwan (firecrawl/wantgoo): price={price}, prev={prev}, pct={chg_pct}%")
        return {'price': price, 'prev': prev, 'chg_pct': chg_pct}
    except Exception as e:
        print(f"SGX Taiwan error: {e}")
        return {'price': 0, 'prev': 0, 'chg_pct': 0}


def get_yahoo(ticker):
    """從 Yahoo Finance v8 API 取得價格與漲跌幅"""
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        m = r.json()['chart']['result'][0]['meta']
        now  = float(m.get('regularMarketPrice') or 0)
        prev = float(m.get('chartPreviousClose') or m.get('previousClose') or 0)
        pct  = m.get('regularMarketChangePercent')
        if pct is None and prev:
            pct = (now - prev) / prev * 100
        result = {'price': round(now, 2), 'chg_pct': round(float(pct or 0), 2)}
        print(f"Yahoo {ticker}: {result}")
        return result
    except Exception as e:
        print(f"Yahoo {ticker} error: {e}")
        return {'price': 0, 'chg_pct': 0}


def direction(pct):
    if pct > 0.05:
        return f'上漲 {abs(pct):.2f}%'
    elif pct < -0.05:
        return f'下跌 {abs(pct):.2f}%'
    else:
        return '持平'


def main():
    sgx  = get_sgx_taiwan()
    gold = get_yahoo('GC=F')
    oil  = get_yahoo('CL=F')
    vix  = get_yahoo('%5EVIX')

    now_tw = datetime.now(TW_TZ)
    today  = now_tw.strftime('%-m月%-d日')

    vix_level = '偏高，市場恐慌' if vix['price'] >= 25 else '正常' if vix['price'] >= 15 else '偏低，市場樂觀'

    speech = (
        f"早安，今天是{today}，盤前市場快報。"
        f" 新加坡富台指數 {sgx['price']:.0f} 點，{direction(sgx['chg_pct'])}。"
        f" 黃金每盎司 {gold['price']:.0f} 美元，{direction(gold['chg_pct'])}。"
        f" WTI 原油每桶 {oil['price']:.1f} 美元，{direction(oil['chg_pct'])}。"
        f" VIX 恐慌指數 {vix['price']:.1f}，{direction(vix['chg_pct'])}，目前{vix_level}。"
        f" 以上是今日盤前快報，祝交易順利。"
    )

    result = {
        'updated_at': now_tw.strftime('%Y-%m-%d %H:%M TW'),
        'speech': speech,
        'sgx_taiwan': sgx,
        'gold':       gold,
        'oil':        oil,
        'vix':        vix,
    }

    with open('market-data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n播報文字：\n{speech}")


if __name__ == '__main__':
    main()

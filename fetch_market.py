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

TW_TZ = timezone(timedelta(hours=8))


def get_sgx_taiwan():
    """從玩股網抓取富台指數（Playwright stealth 繞過 bot 偵測）"""
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-blink-features=AutomationControlled']
            )
            ctx = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800}
            )
            Stealth().apply_stealth_sync(ctx)
            page = ctx.new_page()
            page.goto('https://www.wantgoo.com/global/stwn&', wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(8000)

            og       = page.evaluate("document.querySelector('meta[property=\"og:description\"]')?.content || ''")
            prev_el  = page.query_selector('[c-model="previousClose"]')
            prev_text = prev_el.text_content().strip() if prev_el else ''
            browser.close()

        # og:description 格式: 最新價格3874.75漲跌幅3.34%
        m_price = re.search(r'最新價格([\d,\.]+)', og)
        m_pct   = re.search(r'漲跌幅([\d\.]+)%', og)
        if not m_price:
            print("SGX Taiwan: 無法從 og:description 解析價格")
            return {'price': 0, 'prev': 0, 'chg_pct': 0}

        price   = float(m_price.group(1).replace(',', ''))
        prev    = float(prev_text.replace(',', '')) if prev_text else 0
        chg_pct = float(m_pct.group(1)) if m_pct else (round((price - prev) / prev * 100, 2) if prev else 0)

        if price and prev and price < prev:
            chg_pct = -abs(chg_pct)

        print(f"SGX Taiwan (wantgoo): price={price}, prev={prev}, pct={chg_pct}%")
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

import os
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup

ECOS_KEY = os.getenv("ECOS_API_KEY", "")

def get_ecos_value(stat_code, item_code):
    now = datetime.now()
    end_date = now.strftime("%Y%m")
    start_date = f"{now.year if now.month > 2 else now.year - 1}{(now.month - 2) % 12 or 12:02d}"
    url = f"http://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}/json/kr/1/10/{stat_code}/M/{start_date}/{end_date}/{item_code}"
    try:
        res = requests.get(url, timeout=10).json()
        rows = res["StatisticSearch"]["row"]
        return float(rows[-1]["DATA_VALUE"])
    except:
        return None

def main():
    base_rate = get_ecos_value("722Y001", "0101000")
    ktb_5y = get_ecos_value("817Y002", "010200000")
    cofix = get_ecos_value("901Y059", "0101000")

    market_data = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "base_rate": base_rate if base_rate else 2.75,
        "ktb_5y": ktb_5y if ktb_5y else 2.72,
        "cofix": cofix if cofix else 2.95,
        "fss_headline": "가계대출 관리 강화 및 2금융권 모니터링",
        "key_issues": [
            f"기준금리 {base_rate if base_rate else 2.75}% 안착 국면",
            "스트레스 DSR 3단계 전면 시행 하 주담대 한도 축소",
            "DSR 규제 예외 항목인 보험계약대출로의 수요 이동"
        ]
    }
    with open("latest_market_data.json", "w", encoding="utf-8") as f:
        json.dump(market_data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()

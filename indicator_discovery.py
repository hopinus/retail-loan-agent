"""Discover Korean annual indicators from a publisher catalog, without a topic-to-code map."""
import json
import re
from decimal import Decimal
from urllib.parse import urlencode
from market_watch import download

CATALOG = 'https://api.worldbank.org/v2/sources/2/series?format=json&per_page=2000'


def subject(question):
    # Transmit only the public indicator term. Keep the lending question and portfolio local.
    match = re.search(r'([가-힣A-Za-z][가-힣A-Za-z ]{0,28}?)(?:이|가|의)?\s*(?:상승|하락|증가|감소|변화|변동)', question)
    if not match:
        return ''
    # A separated direction follows the whole noun in '식품물가 상승' / '건축허가 감소'.
    whole = re.match(r'([가-힣A-Za-z][가-힣A-Za-z ]{0,28}?)\s+(?:상승|하락|증가|감소|변화|변동)',question)
    if whole and whole[1].strip() in ('식품물가', '건축허가', '국제유가'):
        return whole[1].strip()
    return re.sub(r'^(?:한국의? |최근 |국내 |우리나라 )+', '', match[1].strip()).strip()


def discover(term, year):
    labels = [term.lower()] if term.isascii() else []
    code = SERIES.get(term.replace(' ', ''))
    if code:
        candidates = [(0,code,'')]
    else:
        if not labels:
            query = urlencode(dict(action='wbsearchentities', language='ko', uselang='en',
                                   format='json', limit=5, search=term))
            hits = json.loads(download('https://www.wikidata.org/w/api.php?' + query))['search']
            labels = [h['label'].lower() for h in hits if h.get('match', {}).get('text') == term and h.get('label')]
        catalog = json.loads(download(CATALOG))['source'][0]['concept'][0]['variable']
        candidates = []
        for entry in catalog:
            title = entry['value'].lower()
            head = re.split(r'[,(:]', title)[0].strip()
            for label in labels:
                core = label.removesuffix(' rate')
                if head not in (core, label) and not title.startswith(label + ' ('):
                    continue
                # Select an aggregate series. Exclude subpopulations unless directly requested.
                if any(w in title and w not in label for w in ('male', 'female', 'youth', 'ages ', 'education', 'rural', 'urban', 'long-term')):
                    continue
                score = (head == label, 'total' in title, 'national estimate' in title, -len(title))
                candidates.append((score, entry['id'], entry['value']))
        if not labels:
            raise IndicatorGap('검색어와 일치하는 통계 용어를 확인하지 못했습니다.')
        if not candidates:
            raise IndicatorGap('공식 목록에서 요청 대상과 측정 방식이 일치하는 지표를 찾지 못했습니다.')
    for _, code, title in sorted(set(candidates), reverse=True)[:4]:
        if not re.fullmatch(r'[A-Za-z0-9._-]+', code):
            continue
        url = f'https://api.worldbank.org/v2/country/KOR/indicator/{code}?source=2&format=json&per_page=15'
        payload = json.loads(download(url))
        rows = {}
        for row in (payload[1] or []):
            if row['countryiso3code'] != 'KOR' or row['indicator']['id'] != code or row['value'] is None:
                continue
            title = row['indicator']['value']
            period, value = int(row['date']), Decimal(str(row['value']))
            if period < year and value.is_finite():
                rows[period] = value
        periods = sorted(rows)
        if len(periods) < 2 or periods[-1] - periods[-2] != 1:
            continue
        a, b = periods[-2:]
        unit = '%' if '%' in title else ''
        delta_unit = '%p' if unit else ' (원 지표 단위)'
        summary = (f'한국 연간 통계 · {a}년 {rows[a]:,.3f}{unit} → {b}년 {rows[b]:,.3f}{unit} · '
                   f'변화 {rows[b]-rows[a]:+,.3f}{delta_unit}. '
                   f'검색어 “{term}”로 WDI 지표 목록에서 {code} 선택.')
        if code == 'CM.MKT.TRAD.CD':
            if title.lower() != 'stocks traded, total value (current us$)':
                raise IndicatorGap('주식 거래대금의 금액 단위를 확인하지 못했습니다.')
            title = '한국 주식 거래대금 · ' + title
        return '세계은행 WDI', title, url, b, summary
    raise IndicatorGap('한국의 연속된 두 연도에서 비교 가능한 관측값을 확보하지 못했습니다.')
# Reviewed WDI series for ambiguous Korean terms. Titles and country are verified on retrieval.
SERIES = {
    '주식거래대금':'CM.MKT.TRAD.CD', '실업률':'SL.UEM.TOTL.NE.ZS', '청년실업률':'SL.UEM.1524.ZS',
    '고용률':'SL.EMP.TOTL.SP.ZS', '경제활동참가율':'SL.TLF.CACT.ZS',
    '인플레이션':'FP.CPI.TOTL.ZG', '소비자물가지수':'FP.CPI.TOTL',
    '국내총생산':'NY.GDP.MKTP.KD', '경제성장률':'NY.GDP.MKTP.KD.ZG',
    '일인당국내총생산':'NY.GDP.PCAP.KD','가계소비지출':'NE.CON.PRVT.KD',
    '총저축':'NY.GNS.ICTR.CN','인구':'SP.POP.TOTL','도시화율':'SP.URB.TOTL.IN.ZS',
    '출산율':'SP.DYN.TFRT.IN','기대수명':'SP.DYN.LE00.IN','노년부양비':'SP.POP.DPND.OL',
    '환율':'PA.NUS.FCRF','원달러환율':'PA.NUS.FCRF',
    '수출':'NE.EXP.GNFS.KD','수입':'NE.IMP.GNFS.KD','경상수지':'BN.CAB.XOKA.CD',
    '외환보유액':'FI.RES.XGLD.CD','외국인직접투자':'BX.KLT.DINV.CD.WD',
    '은행부실대출비율':'FB.AST.NPER.ZS','빈곤율':'SI.POV.NAHC',
}
class IndicatorGap(ValueError):
    pass

"""Public observations and editable, hypothetical lending sensitivity scenarios."""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from xml.etree import ElementTree

import indicator_discovery
import domestic_indicators
from market_watch import download, text

RATE = 'https://www.bok.or.kr/portal/singl/baseRate/list.do?menuNo=200643'
VOLUME = 'https://fchart.stock.naver.com/sise.nhn?symbol=KOSPI&timeframe=day&count=12&requestType=0'


def topic(question):
    compact = re.sub(r'\s+', '', question)
    if not re.search('영향|분석|시나리오|미치|배분', compact):
        return None
    term = indicator_discovery.subject(question).replace(' ', '')
    term = re.sub(r'^(?:국내|한국은행|한국의|최근)', '', term)
    if term == '미국정책금리' or ((term in domestic_indicators.ECOS or term in domestic_indicators.NATIONAL or term == '최저임금')
            and not re.search('미국|일본|중국|유럽|유로존|영국|독일|해외', compact)):
        return 'domestic'
    if re.search('미국|일본|중국|유럽|유로존|영국|독일|해외', compact):
        return 'unsupported_country'
    if term in ('금리','기준금리') or re.match(r'^(?:한국은행)?(?:기준)?금리인상',compact):
        return 'rate'
    if term in ('주식거래량','코스피거래량'):
        return 'stocks'
    if term in ('주식투자수요','주식거래'):
        return 'stocks_proxy'
    if term == '주식거래대금':
        return 'catalog'
    if '금리' in term or '주식' in term:
        return 'unsupported_measure'
    if not re.search('보도자료|금융당국|금융위|금감원', question) and indicator_discovery.subject(question):
        return 'catalog'
    return None


def observation(kind, today):
    if kind == 'rate':
        rows = {}
        for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>', download(RATE).decode().lower(), re.S):
            match = re.fullmatch(r'(\d{4})\s+(\d+)월\s*(\d+)일\s+([\d.]+)', text(tr))
            if match:
                year, month, day, rate = match.groups()
                d = date(int(year), int(month), int(day))
                if d <= today:
                    rows[d] = Decimal(rate)
        if len(rows) < 2:
            raise ValueError('비교 가능한 변경일 부족')
        a, b = sorted(rows)[-2:]
        summary = f'최근 두 변경일 비교 · {a} {rows[a]}% → {b} {rows[b]}% · 변화 {rows[b]-rows[a]:+.2f}%p'
        return '한국은행', '한국은행 기준금리', RATE, b, summary

    root = ElementTree.fromstring(download(VOLUME).decode('cp949'))
    chart = root.find('.//chartdata')
    if chart is None or chart.get('symbol') != 'KOSPI':
        raise ValueError('지수 확인 실패')
    rows = {}
    for item in chart.findall('item'):
        fields = item.attrib['data'].split('|')
        d = datetime.strptime(fields[0], '%Y%m%d').date()
        if d < today and len(fields) == 6 and fields[-1].isdigit():
            rows[d] = int(fields[-1])
    days = sorted(rows)[-10:]
    if len(days) != 10:
        raise ValueError('완료된 거래일 부족')
    old, new = sum(rows[d] for d in days[:5]), sum(rows[d] for d in days[5:])
    if old <= 0:
        raise ValueError('기준 거래량 부족')
    ratio = new / old * 100
    summary = (f'완료된 5거래일 평균 거래량 비교 · {days[0]}~{days[4]} = 100 기준, '
               f'{days[5]}~{days[9]} = {ratio:.2f} · 변화 {ratio-100:+.2f}%. '
               '거래량은 매수·매도를 모두 포함하는 활동 지표로, 순투자 수요와 다를 수 있습니다.')
    return '네이버페이 증권', '코스피 일별 거래량', VOLUME, days[-1], summary


def analyze(kind, portfolio, question=''):
    today = datetime.now(timezone(timedelta(hours=9))).date()
    term = indicator_discovery.subject(question) if kind in ('catalog','domestic') else ''
    publisher, title, url, latest, summary = (domestic_indicators.observe(re.sub(r'^(?:국내|한국은행|한국의|최근)', '',term.replace(' ','')),today) if kind=='domestic' else indicator_discovery.discover(term, today.year)
        if kind == 'catalog' else observation(kind, today))
    # Explicit stress settings, independent of the observed move. Scale only with local portfolio size.
    if kind == 'rate':
        name = '금리 상승 민감도'
        settings = [(-5, 0), (-5, -2), (0, 0)]
        rationale = '조달 비용과 차입 부담 상승을 가정해 주담대·신용 실행 상한을 기준 대비 5% 낮추고 신용 회수는 2% 줄입니다.'
    elif kind == 'stocks':
        name = '주식 투자 수요 증가 민감도'
        settings = [(0, 0), (3, 0), (3, -2)]
        rationale = '투자자금 차입이 늘어난다는 가정으로 신용·보험계약대출 최소 실행을 기준 대비 3% 높이고 보험계약대출 회수는 2% 줄입니다.'
    else:
        name = term + ' 변화 민감도'
        names = ('주택담보대출', '신용대출', '보험계약대출')
        selected = [n for n in names if n in question or (n == names[0] and '주담대' in question)]
        selected = selected or list(names)
        recovery = bool(re.search('회수|상환|연체', question))
        settings = [((0, -2) if recovery else (-2, 0)) if n in selected else (0, 0) for n in names]
        rationale = ('관측된 변화와 별도로 ' + '·'.join(selected) +
                     ('의 회수 지연을 가정해 기준 회수액을 2% 줄입니다. 실행계획은 유지합니다.' if recovery else
                      '의 실행이 위축되는 경우를 가정해 실행 상한을 기준보다 2% 낮춥니다. 회수계획은 유지합니다.'))
    rationale += ' 비율은 담당자 검토용 가상 충격이며 관측치에서 추정한 계수가 아닙니다.'
    product_settings = dict(zip(('주택담보대출', '신용대출', '보험계약대출'), settings))
    impacts, lines = {}, []
    for row in portfolio:
        product = row['product']
        execution, repayment = product_settings[product]
        impact = {'repayment_delta': round(row['repayment'] * repayment / 100, 5)}
        action = '기존 실행 유지'
        if execution:
            bound = round(row['execution'] * (100 + execution) / 100, 5)
            impact['execution_floor' if execution > 0 else 'execution_ceiling'] = bound
            action = ('최소 실행' if execution > 0 else '실행 상한') + f' {bound:g}억'
        lines.append(f"{product} · {action}, 회수 변화 {impact['repayment_delta']:+g}억")
        impacts[product] = impact
    source = dict(title=title, url=url, publisher=publisher, published_at=str(latest),
                  scope='지표 관측일 · 공개 시계열', excerpt=summary)
    return {'answer': f'{publisher} · {title}\n{summary}\n\n조건부 시나리오 · {rationale}\n' + '\n'.join(lines),
            'mode': 'indicator', 'tools_used': (['지표 용어 검색', 'WDI 통계 목록 검색', '한국 연간 관측값 검증'] if kind == 'catalog' else ['국내 공식 시계열 검증'] if kind=='domestic' else ['공개 시계열 비교']), 'sources': [source],
            'draft': dict(name=name, rationale=rationale, impacts=impacts)}

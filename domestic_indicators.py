"""Pinned official series; validate every returned dimension and compare consecutive periods."""
import json
import re
from decimal import Decimal
from market_watch import download, text
from indicator_discovery import IndicatorGap

# term, display definition, table, items, cycle, reported unit
ECOS = {
    '미국정책금리': ('미국 중앙은행 정책금리', '902Y006','US','M','%'),
    '주택담보대출금리': ('예금은행 신규취급 주택담보대출 금리','121Y006','BECBLA0302','M','연리%'),
    '주식투자자예탁금': ('증시 투자자예탁금','901Y056','S23A','M','원'),
    '식품물가': ('식품물가 · 식료품 소비자물가지수 (food price index)','901Y009','A01','M','2020=100'),
    '가계부채': ('가계부채 · 가계신용 잔액 (가계대출 및 판매신용, household debt)','151Y001','1000000','Q','십억원'),
    '주택가격': ('전국 종합 주택매매가격지수 (house price index)','901Y149','00/a0','M','2026.06=100'),
    '전세가격': ('전국 종합 주택전세가격지수','901Y150','00/a0','M','2026.06=100'),
    '건축허가': ('건축허가 동수 · 전체 용도','901Y037','I43AB/2','M','동수'),
    '산업생산': ('전산업생산지수 · 농림어업 제외 (industrial production)','901Y033','A00/1','M','2020=100'),
    '소매판매': ('소매판매액지수 · 불변 총지수 (retail sales)','901Y100','G0/T2','M','2020=100'),
    '소비자심리지수': ('소비자심리지수 · 전체','511Y002','FME/99988','M',''),
    '국제유가': ('국제유가 · 브렌트유 (Brent crude oil)','902Y003','010103','M','달러/배럴'),
    '빈곤율': ('처분가능소득 기준 상대적 빈곤율 (poverty headcount, 중위소득 50% 이하)','901Y112','I38B/90','A',''),
}
WAGE='https://www.minimumwage.go.kr/minWage/policy/decisionMain.do'


NATIONAL = {
    '장기실업률': ('5027', '장기실업률', '장기실업률 (long-term unemployment, 전체 실업자 중 1년 이상 실업자)', '%'),
    '가계가처분소득': ('5048', '전체 가구', '전체 가구 처분가능소득 (disposable income)', '천원'),
}


def national_observation(term,today):
    code,label,title,unit=NATIONAL[term]
    url=f'https://www.index.go.kr/unity/potal/eNara/sub/showStblGams3.do?freq=Y&idx_cd={code}&period=N&stts_cd={code}01'
    html=download(url).decode('utf8')
    rows=[text(tr) for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',html,re.S|re.I)]
    years=next((r.split() for r in rows if re.fullmatch(r'\d{4}(?: \d{4})+',r)),[])
    record=next((r[len(label):].split() for r in rows if r.startswith(label+' ')),[])
    if len(years)!=len(record) or len(years)<2:
        raise IndicatorGap('국가지표체계 원표에서 대상 행과 비교 기간을 확인하지 못했습니다.')
    a,b=map(int,years[-2:])
    if b!=a+1 or not today.year-2<=b<=today.year:
        raise IndicatorGap(f'국가지표체계 해당 표의 최종 관측은 {b}년입니다. 최근 영향 분석을 위한 가정을 생성하지 않았습니다.')
    x,y=(Decimal(v.replace(',','')) for v in record[-2:])
    return '국가지표체계',title,url,b,f'{title} · {a}년 {x}{unit} → {b}년 {y}{unit} · 변화 {y-x:+}{"%p" if unit=="%" else unit}'


def observe(term,today):
    if term in NATIONAL:
        return national_observation(term,today)
    if term == '최저임금':
        values = {}
        page = download(WAGE).decode('utf8')
        for tr in re.findall(r'<tr\b[^>]*>(.*?)</tr>',page,re.S|re.I):
            cells=[text(c) for c in re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>',tr,re.S|re.I)]
            if len(cells)<2: continue
            match=re.search(r"(\d{2})\.01\.01",cells[0])
            if match and re.fullmatch(r'[\d,]+',cells[1]):
                year=2000+int(match[1])
                if year<=today.year: values[year]=Decimal(cells[1].replace(',',''))
        title,publisher,url,unit='한국 시간급 최저임금 (minimum wage)','최저임금위원회',WAGE,'원/시간'
        period=str
    else:
        title,table,items,cycle,unit=ECOS[term]
        width={'M':12,'Q':4,'A':1}[cycle]
        current=today.year*width+({'M':today.month-1,'Q':(today.month-1)//3,'A':0}[cycle])
        def period(i):
            y,n=divmod(i,width)
            return f'{y}{n+1:02d}' if cycle=='M' else f'{y}Q{n+1}' if cycle=='Q' else str(y)
        url=(f'https://ecos.bok.or.kr/api/StatisticSearch/sample/json/kr/1/10/{table}/{cycle}/'
             f'{period(current-9)}/{period(current-1)}/{items}')
        obj=json.loads(download(url))
        values={}
        expected=items.split('/')
        for r in obj.get('StatisticSearch',{}).get('row',[]):
            dims=[r[f'ITEM_CODE{i}'] for i in range(1,5) if r.get(f'ITEM_CODE{i}')]
            if r['STAT_CODE']!=table or dims!=expected or (r['UNIT_NAME'] or '').strip()!=unit:
                raise IndicatorGap('ECOS 관측 행의 계열 또는 단위가 설정과 다릅니다.')
            keys=[i for i in range(current-9,current) if period(i)==r['TIME']]
            if keys and r['DATA_VALUE'] is not None:
                val=Decimal(str(r['DATA_VALUE']).replace(',',''))
                if val.is_finite():values[keys[0]]=val
        publisher='한국은행 ECOS'
        if '=' in unit: unit='지수'
        if not unit: unit='%' if term=='빈곤율' else '지수'
    dates=sorted(values)
    if len(dates)<2 or dates[-1]-dates[-2]!=1:
        raise IndicatorGap('공식 통계의 같은 계열에서 연속 두 기간을 확인하지 못했습니다.')
    a,b=dates[-2:]
    if term=='최저임금' and b!=today.year:
        raise IndicatorGap('현 적용 연도의 최저임금 확인 실패')
    diffunit='%p' if '%' in unit else unit
    summary=f'{title} · {period(a)} {values[a]:,}{unit} → {period(b)} {values[b]:,}{unit} · 변화 {values[b]-values[a]:+,}{diffunit}'
    return publisher,title,url,period(b),summary

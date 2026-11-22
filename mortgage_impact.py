"""Evidence-based mortgage signals for the reviewed BOK survey release."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urlencode

import market_watch


SURVEY_URL = ('https://www.bok.or.kr/portal/bbs/B0000501/view.do'
              '?menuNo=201264&nttId=11065895&programType=newsData')
SURVEY_TITLE = '금융기관 대출행태서베이 · 2026년 3분기 동향 및 4분기 전망'
# Reviewed against the attached PDF. Values are DI points, in demand/supply order.
SURVEY = {
    3: {'국내은행 가계 주택관련대출': (14, -17), '생명보험회사 전체 대출': (3, -20)},
    4: {'국내은행 가계 주택관련대출': (14, 0), '생명보험회사 전체 대출': (14, -3)},
}

# Each rule binds scope, effective date and the measure to reviewed source language.
POLICY_RELEASES = (
    (
        '86606', '2026년도 가계부채 관리방안', date(2026, 4, 1), date(2026, 4, 17),
        (('全금융권', '26.4.17일부터시행'),),
        (
            (
                (('수도권·규제지역아파트담보대출', '만기연장', '원칙적으로불허'),
                 ('예외적으로만기연장', '임차인')),
                '다주택자·임대사업자의 수도권·규제지역 아파트 담보대출 만기연장 원칙적 제한. 임차인 등 예외 적용.',
            ),
        ),
    ),
    (
        '84824', '가계부채 관리 강화 방안', date(2025, 6, 27), date(2025, 6, 28),
        (('은행자율관리조치사항', '全금융권으로확대시행', '6.28일부터'),),
        (
            (
                (('생활안정자금목적주담대한도', '최대1억원', '2채이상', '취급을금지', '지방소재주택'),),
                '수도권·규제지역 주택의 생활안정자금 주담대 한도 최대 1억 원. 해당 지역 내 2주택 이상 보유자는 취급 금지. 지방 비규제지역은 금융회사 자율.',
            ),
            (
                (('주담대대출만기를30년이내로제한', '수도권', '규제지역'),),
                '수도권·규제지역 주담대 대출만기 30년 이내 제한.',
            ),
        ),
    ),
)


def search_policy_releases(source):
    publisher, _, base = market_watch.SOURCES[source]
    parser = market_watch.parse_fsc if source == 'fsc' else market_watch.parse_fss
    rows = {}
    for keyword in ('가계부채 관리', '주택담보대출', '주담대', '부동산 시장 안정', '규제지역 추가 지정'):
        params = ({'srchKey': 'sj', 'srchText': keyword} if source == 'fsc'
                  else {'searchCnd': '1', 'searchWrd': keyword})
        try:
            url = base + ('&' if '?' in base else '?') + urlencode(params)
            found = parser(market_watch.download(url))
        except (OSError, ValueError):
            continue
        for row in found:
            title = re.sub(r'\s+', '', row['title'])
            if row['published_at'] and re.search(r'관리|규제|시행|대책|제한|개정', title):
                rows.setdefault(row['url'], {**row, 'publisher': publisher})
    return list(rows.values())


def explicit_policy(passage, published, quarter_end):
    compact = re.sub(r'\s+', '', passage)
    if re.search(r'검토|추진|예정|계획|예고|제안|논의|은행권에한해|보험.*제외', compact):
        return None
    if not re.search(r'(?:全|전)금융권|보험업권|보험회사|보험사', compact):
        return None
    if not re.search(r'주택담보대출|주담대', compact):
        return None
    restriction = bool(re.search(r'한도.{0,24}(?:축소|제한|인하)|(?:취급|만기연장).{0,12}(?:금지|불허|제한)|LTV.{0,20}(?:인하|강화)', compact))
    easing = bool(re.search(r'한도.{0,24}(?:확대|상향)|LTV.{0,20}(?:완화|상향)|만기연장.{0,12}허용', compact))
    if restriction == easing:
        return None
    dates = re.findall(r"(?<!\d)(?:(20\d{2}|\d{2})[.년])?(\d{1,2})[.월](\d{1,2})일(?:부터|부로)?(?:이미)?(?:시행|적용)", compact)
    if len(dates) != 1:
        return None
    year, month, day = dates[0]
    try:
        effective = date(int(year) + (2000 if len(year) == 2 else 0) if year else published.year,
                         int(month), int(day))
    except ValueError:
        return None
    if effective <= quarter_end:
        return effective, '강화' if restriction else '완화'
    return None


def regional_ltv_policy(passages, published, quarter_end):
    for index, passage in enumerate(passages):
        effective_match = re.search(
            r'규제지역으로지정된지역.*?대출규제가(\d{1,2})\.(\d{1,2})일부터즉시적용된다',
            re.sub(r'\s+', '', passage))
        if not effective_match:
            continue
        scope = passages[index + 1:index + 2]
        measure = passages[index + 2:index + 5]
        if not any('보험업감독규정' in line for line in scope):
            continue
        ltv = next((line for line in measure if re.match(r'\[1\]\s*\(주담대 LTV\)', line)
                    and re.search(r'LTV\s*강화.*70%\s*→.*40%', line)), None)
        region = next((line for line in passages[:index] if
                       '규제지역' in line and '즉시 적용' in line and '70% → 40%' in line), None)
        if not ltv or not region:
            continue
        try:
            effective = date(published.year, *map(int, effective_match.groups()))
        except ValueError:
            continue
        if published <= effective <= quarter_end:
            return effective, (
                f'보험업감독규정 적용 · {region.lstrip("▴ ")} · '
                '신규 규제지역 내 일반 주담대 LTV 강화. 생애최초·정책모기지 등 별도 비율 및 경과규정 적용.')
    return None


def verified_supply_policies(quarter_end):
    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(search_policy_releases, ('fsc', 'fss')))
    reviewed = {f'https://www.fsc.go.kr/no010101/{rule[0]}': rule for rule in POLICY_RELEASES}
    candidates = []
    for batch in batches:
        eligible = [row for row in batch if row['url'] not in reviewed
                    and row['published_at'] <= quarter_end.isoformat()]
        eligible.sort(key=lambda row: ('규제지역추가지정' in re.sub(r'\s+', '', row['title']),
                                       row['published_at']), reverse=True)
        candidates.extend(eligible[:8])
    # Keep the reviewed measures available while independently checking newly discovered releases.
    candidates.extend({'url': url, 'title': rule[1], 'publisher': '금융위원회',
                       'published_at': rule[2].isoformat()} for url, rule in reviewed.items())

    def inspect(row):
        try:
            published = date.fromisoformat(row['published_at'])
            if published > quarter_end:
                return []
            release = market_watch.analyze_release(row, '', limit=1000)
        except (OSError, ValueError):
            return []
        source = {key: release[key] for key in ('url', 'title', 'publisher', 'published_at')}
        rule = reviewed.get(row['url'])
        if rule:
            _, _, _, effective, common_checks, measures = rule
            passages = [re.sub(r'\s+', '', line) for line in release['evidence']]

            def matches(checks):
                return all(any(all(term in passage for term in terms) for passage in passages)
                           for terms in checks)

            if effective > quarter_end or not matches(common_checks):
                return []
            return [{**source, 'effective_at': effective.isoformat(), 'direction': '강화',
                     'text': f'{effective.isoformat()} 시행 · 전 금융권(보험업권 포함) · {description}'}
                    for checks, description in measures if matches(checks)]
        evidence = []
        regional = regional_ltv_policy(release['evidence'], published, quarter_end)
        if regional:
            effective, description = regional
            evidence.append({**source, 'effective_at': effective.isoformat(), 'direction': '강화',
                             'text': f'{effective.isoformat()} 시행 · {description}'})
        for passage in release['evidence']:
            match = explicit_policy(passage, published, quarter_end)
            if match:
                effective, direction = match
                evidence.append({**source, 'effective_at': effective.isoformat(), 'direction': direction,
                                 'text': f'{effective.isoformat()} 시행 · {passage}'})
        return evidence

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = pool.map(inspect, candidates)
        unique = {}
        for evidence in results:
            for item in evidence:
                key = (item['effective_at'], re.sub(r'[^가-힣a-zA-Z0-9]', '', item['text']))
                unique.setdefault(key, item)
    return list(unique.values())


def is_impact_question(question):
    compact = re.sub(r'\s+', '', question)
    return (bool(re.search(r'보험사|보험회사|보험업권|생명보험|생보사', compact))
            and bool(re.search(r'주담대|주택담보대출', compact))
            and bool(re.search(r'수요|공급|영향도|등급|대출태도', compact)))


def analyze(question, days=30):
    compact = re.sub(r'\s+', '', question)
    years = {int(year) for year in re.findall(r'(20\d{2})년?', compact)}
    quarters = {int(q) for q in re.findall(r'([1-4])(?:/4)?분기', compact)}
    quarter = next(iter(quarters), 3 if '동향' in compact and '전망' not in compact else 4)
    supported = (years in (set(), {2026}) and len(quarters) <= 1 and quarter in SURVEY
                 and not re.search(r'다음분기|내년|작년|(?<!\d)(?:1[0-2]|[1-9])월', compact))
    period = f'2026년 {quarter}분기 ' + ('전망' if quarter == 4 else '동향')
    grades = []
    for index, (axis, metric, labels, pages) in enumerate((
        ('수요', '대출수요지수', ('감소', '보합', '증가'), (7, 9)),
        ('공급', '대출태도지수', ('강화', '보합', '완화'), (5, 8)),
    )):
        grade = {'axis': axis, 'level': '판단 유보', 'confidence': '부족', 'evidence': []}
        if supported:
            values = SURVEY[quarter]
            directions = set()
            for (scope, metrics), page in zip(values.items(), pages):
                value = metrics[index]
                directions.add((value > 0) - (value < 0))
                grade['evidence'].append({
                    'text': f'{scope} {metric} {value:+d} (DI, 첨부 PDF {page}쪽)'.replace('+0', '0'),
                    'title': SURVEY_TITLE, 'url': SURVEY_URL, 'publisher': '한국은행',
                    'published_at': '2026-10-26',
                })
            grade['confidence'] = '간접'
            if len(directions) == 1:
                grade['level'] = labels[directions.pop() + 1]
                grade['reason'] = '두 간접 지표의 방향이 일치합니다.'
            else:
                grade['reason'] = '은행 주택관련대출과 생명보험회사 전체 대출 지표의 방향이 달라 판단을 유보했습니다.'
        else:
            grade['reason'] = '요청 기간에 해당하는 검증된 서베이 지표가 없습니다.'
        grades.append(grade)
    if supported:
        policies = verified_supply_policies(date(2026, quarter * 3, 30 if quarter == 3 else 31))
        if policies:
            supply = grades[1]
            survey_level = supply['level']
            directions = {policy['direction'] for policy in policies}
            supply['level'] = (f'{next(iter(directions))} 요인 확인 (일부)' if len(directions) == 1
                               else '강화·완화 요인 병존')
            supply['confidence'] = '직접(정책 적용 대상)'
            supply['reason'] = (
                f'원문에서 확인한 공급 영향 근거 {len(policies)}건을 해당 대출에 반영했습니다. '
                f'한국은행 간접 지표만 적용한 등급은 {survey_level}입니다.')
            supply['evidence'] = policies + supply['evidence']
        else:
            grades[1]['reason'] += ' 등록된 정책의 적용 범위와 시행일은 원문에서 재확인하지 못했습니다.'
    result = {'answer': f'보험사 주택담보대출 · {period}' if supported else '보험사 주택담보대출 · 요청 기간 미확인',
              'impact_grades': grades, 'mode': 'mortgage_impact',
              'tools_used': ['한국은행 서베이 검증 데이터', '금융위·금감원 공식 본문 조회']}
    if supported:
        releases = market_watch.answer_release_question(
            '금융위와 금감원 가계대출 보도자료에서 보험업권과 주담대는?', days)
        result['citations'] = releases['citations']
        result['answer'] += ('\n서베이 두 지표는 보험사 주담대의 간접 근거입니다. '
                             '공급에는 원문에서 적용 범위와 시행일을 확인한 정책을 반영합니다. '
                             '금융위·금감원 가계대출 증감은 관측된 시장 흐름으로 함께 표시합니다.')
        if not result['citations']:
            result['answer'] += '\n금융위·금감원 보도자료 본문 근거 미확인.'
    return result

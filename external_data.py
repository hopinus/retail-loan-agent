"""Read-only official data connectors. Never expose authenticated URLs/errors."""
import copy
import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError

_lock = Lock()
_cache = {}
_keys = {}


def now():
    # Windows installations may not include the IANA timezone database.
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=9)))


def secret_path():
    return Path(os.environ['LOCALAPPDATA']) / 'RetailLendingAgent' / 'external.dpapi'


def credentials():
    result = {}
    try:
        from local_credentials import transform
        result = json.loads(transform(secret_path().read_bytes(), False).decode())
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    result.update(_keys)
    for name, env in [('ecos', 'ECOS_API_KEY'), ('dart', 'DART_API_KEY')]:
        if os.getenv(env):
            result[name] = os.environ[env].strip()
    return result


def configure(ecos='', dart='', persist=True):
    values = credentials()
    for name, value in [('ecos', ecos), ('dart', dart)]:
        if value:
            if not re.fullmatch(r'[A-Za-z0-9_-]{8,200}', value):
                raise ValueError('API 키에는 영문·숫자·밑줄·하이픈만 입력해 주세요.')
            values[name] = value
    if persist:
        from local_credentials import transform
        encrypted = transform(json.dumps(values).encode(), True)
        path = secret_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_bytes(encrypted)
        temp.replace(path)
    with _lock:
        _keys.update(values)
        _cache.clear()


def status():
    keys = credentials()
    return {name: {'configured': bool(keys.get(name)),
                   'note': '설정 여부이며 실제 조회 성공은 데이터 조회로 확인하세요.'}
            for name in ('ecos', 'dart')}


def fetch_json(url):
    try:
        with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=15) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError()
        return json.loads(raw.decode('utf-8-sig'))
    except HTTPError as exc:
        raise ValueError(f'공식 데이터 서버 HTTP {exc.code}. 인증·이용한도·서비스 상태를 확인하세요.') from None
    except (URLError, OSError, ValueError):
        raise ValueError('공식 데이터 서버에 연결하지 못했거나 응답 형식이 올바르지 않습니다.') from None


def _ecos(key):
    rows = []
    for start in range(1, 1001, 100):
        data = fetch_json('https://ecos.bok.or.kr/api/KeyStatisticList/' + quote(key, safe='') + f'/json/kr/{start}/{start+99}/')
        if not isinstance(data, dict):
            raise ValueError('ECOS 응답 구조가 올바르지 않습니다.')
        if 'RESULT' in data:
            code = str(data['RESULT'].get('CODE', 'UNKNOWN'))
            raise ValueError('ECOS 조회 실패: ' + (code if re.fullmatch(r'[A-Z0-9-]{1,30}', code) else 'UNKNOWN'))
        group = data.get('KeyStatisticList', {})
        batch = group.get('row', [])
        rows.extend(batch)
        if not batch or len(rows) >= int(group.get('list_total_count', len(rows))):
            break
    if not rows:
        raise ValueError('ECOS 주요지표가 반환되지 않았습니다.')
    return {'rows': [{'name': r.get('KEYSTAT_NAME'), 'value': r.get('DATA_VALUE'),
                      'unit': r.get('UNIT_NAME'), 'reference_period': r.get('CYCLE') or r.get('TIME'),
                      'published_at': None} for r in rows],
            'sources': [{'title': '한국은행 ECOS 100대 통계지표', 'url': 'https://ecos.bok.or.kr/',
                         'published_at': None}],
            'note': '각 지표의 기준시점과 단위를 확인하세요. 기준시점은 공표일이 아니며 API에 공표일이 없어 미확인으로 표시합니다. 금리·대출·경기 지표를 포함한 주요지표 조회이며 실시간 시세가 아닙니다.'}


def _dart(key, corp_code):
    end = now().date()
    begin = end - timedelta(days=30)
    params = {'crtfc_key': key, 'bgn_de': begin.strftime('%Y%m%d'),
              'end_de': end.strftime('%Y%m%d'), 'page_no': 1, 'page_count': 40,
              'sort': 'date', 'sort_mth': 'desc'}
    if corp_code:
        params['corp_code'] = corp_code
    data = fetch_json('https://opendart.fss.or.kr/api/list.json?' + urlencode(params))
    if not isinstance(data, dict):
        raise ValueError('OpenDART 응답 구조가 올바르지 않습니다.')
    code = data.get('status')
    if code not in ('000', '013'):
        hints = {'010': '인증키 오류', '011': '사용할 수 없는 인증키', '012': '접근 IP 제한',
                 '020': '요청 한도 초과', '100': '요청 인자 확인', '800': '시스템 점검'}
        raise ValueError('OpenDART 조회 실패: ' + hints.get(code, '인증·서비스 상태 확인'))
    rows = []
    for row in data.get('list', []):
        receipt = row.get('rcept_no', '')
        if not re.fullmatch(r'\d{14}', receipt):
            continue
        date = str(row.get('rcept_dt', ''))
        rows.append({'company': row.get('corp_name'), 'corp_code': row.get('corp_code'),
                     'title': row.get('report_nm'), 'published_at': date,
                     'url': 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + receipt})
    return {'rows': rows, 'sources': [{'title': str(r['company']) + ' · ' + str(r['title']),
                                      'url': r['url'], 'published_at': r['published_at']} for r in rows],
            'total_count': data.get('total_count', 0), 'period': {'from': str(begin), 'to': str(end)},
            'corp_code': corp_code or None,
            'note': '최근 30일 공시 목록 중 최신 최대 40건입니다. 회사 미지정 시 전체 기업 대상이며 경쟁 보험사 전용 결과가 아닙니다. 접수일은 통계 기준일과 다릅니다. 공시 제목·접수일만 조회했으며 본문·재무수치·대출잔액은 읽지 않았습니다.'}


def _financial(key, corp_code, year, report, fs_div):
    params = {'crtfc_key': key, 'corp_code': corp_code, 'bsns_year': year,
              'reprt_code': report, 'fs_div': fs_div}
    data = fetch_json('https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?' + urlencode(params))
    if not isinstance(data, dict):
        raise ValueError('DART 재무정보 응답 구조가 올바르지 않습니다.')
    if data.get('status') == '013':
        raise ValueError('해당 회사·사업연도·보고서·연결/별도 조건의 재무정보가 없습니다. 다른 조건을 선택하세요.')
    if data.get('status') != '000':
        raise ValueError('DART 재무정보 조회 실패. 인증·요청한도·회사 및 보고서 조건을 확인하세요.')
    wanted = ('자산총계', '부채총계', '자본총계', '대출', '영업이익', '당기순이익', '보험수익', '보험서비스')
    rows = []
    sources = {}
    for row in data.get('list', []):
        if row.get('sj_div') not in ('BS', 'IS', 'CIS'):
            continue
        if not any(word in row.get('account_nm', '').replace(' ', '') for word in wanted):
            continue
        receipt = str(row.get('rcept_no', ''))
        url = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + receipt if re.fullmatch(r'\d{14}', receipt) else 'https://opendart.fss.or.kr/'
        rows.append({'account': row.get('account_nm'), 'statement': row.get('sj_nm'),
                     'current_period': row.get('thstrm_nm'), 'current_amount': row.get('thstrm_amount'),
                     'previous_period': row.get('frmtrm_nm'), 'previous_amount': row.get('frmtrm_amount'),
                     'current_cumulative_amount': row.get('thstrm_add_amount'),
                     'previous_same_period': row.get('frmtrm_q_nm'),
                     'previous_same_period_amount': row.get('frmtrm_q_amount'),
                     'previous_cumulative_amount': row.get('frmtrm_add_amount'),
                     'currency': row.get('currency') or 'API 미제공·보고서 확인 필요', 'url': url})
        sources[url] = {'title': f'DART {corp_code} · {year} · {report} · {fs_div} 재무제표',
                        'url': url, 'published_at': None}
    return {'rows': rows[:60], 'sources': list(sources.values()), 'corp_code': corp_code,
            'year': year, 'report': report, 'fs_div': fs_div,
            'note': '지정한 회사·사업연도·보고서·연결/별도 기준의 재무상태표·손익계산서 주요 계정입니다. API 금액 문자열과 통화 단위를 보존하며 억원으로 자동 변환하지 않습니다. 분/반기 손익의 당기금액은 3개월 금액일 수 있습니다. 전기 금액이 동일 기간이 아닐 수 있으므로 기간이 일치할 때만 증감률을 계산하세요. 주요 계정은 자산·부채·자본·대출·손익·보험수익 키워드로 선택했으며 주담대/신용/보험계약대출 세부 잔액이나 K-ICS 수치를 추정하지 않습니다. 이 응답에 공표일은 없어 미확인입니다.'}


def query(provider, corp_code='', force=False, year='', report='11011', fs_div='OFS'):
    if provider not in ('ecos', 'dart', 'dart_financial'):
        raise ValueError('지원하지 않는 데이터 제공자입니다.')
    if corp_code and not re.fullmatch(r'\d{8}', corp_code):
        raise ValueError('DART 고유번호는 숫자 8자리입니다. 종목코드와 다릅니다.')
    if provider == 'dart_financial':
        if not corp_code:
            return {'provider': provider, 'ok': False, 'status': 'selection_required', 'rows': [], 'sources': [],
                    'error': '회사 고유번호를 지정하고 재무정보 조회를 눌러 주세요.'}
        year = str(year or now().year - 1)
        if not re.fullmatch(r'\d{4}', year) or not 2015 <= int(year) <= now().year or report not in ('11011', '11012', '11013', '11014') or fs_div not in ('OFS', 'CFS'):
            raise ValueError('사업연도(2015년 이후)·보고서·연결/별도 조건을 확인하세요.')
    key = credentials().get('dart' if provider == 'dart_financial' else provider)
    if not key:
        return {'provider': provider, 'ok': False, 'status': 'not_configured', 'rows': [], 'sources': [],
                'error': '자료 관리에서 해당 API 키를 설정해 주세요.'}
    cache_key = (provider, corp_code, year, report, fs_div, hashlib.sha256(key.encode()).hexdigest())
    with _lock:
        cached = _cache.get(cache_key)
        if not force and cached and time.monotonic() - cached[0] < 600:
            result = copy.deepcopy(cached[1])
            result['cached'] = True
            return result
    try:
        if provider == 'ecos':
            payload = _ecos(key)
        elif provider == 'dart':
            payload = _dart(key, corp_code)
        else:
            payload = _financial(key, corp_code, year, report, fs_div)
        result = {'provider': provider, 'ok': True, 'status': 'verified',
                  'fetched_at': now().isoformat(), 'cached': False, **payload}
        with _lock:
            _cache[cache_key] = (time.monotonic(), copy.deepcopy(result))
        return result
    except ValueError as exc:
        return {'provider': provider, 'ok': False, 'status': 'failed', 'rows': [], 'sources': [],
                'error': str(exc), 'fetched_at': now().isoformat()}


def context(corp_code='', financial=None):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(query, provider, corp_code if provider == 'dart' else '')
                   for provider in ('ecos', 'dart')]
        result = {provider: future.result() for provider, future in zip(('ecos', 'dart'), futures)}
    if financial:
        result['dart_financial'] = query('dart_financial', **financial)
    return result

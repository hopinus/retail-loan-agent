"""Bounded public RSS/press-list monitoring. No arbitrary URL fetches."""
import copy
import re
import time
import html
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from threading import Lock
from urllib.parse import urlencode, urlsplit, urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

SOURCES = {
    'fss': ('금융감독원', 'official', 'https://www.fss.or.kr/fss/bbs/B0000188/list.do?menuNo=200218'),
    'fsc': ('금융위원회', 'official', 'https://www.fsc.go.kr/no010101'),
    'bok': ('한국은행', 'official', 'https://www.bok.or.kr/portal/bbs/B0000552/news.rss'),
    'mk': ('매일경제', 'press', 'https://www.mk.co.kr/rss/30100041/'),
    'hankyung': ('한국경제', 'press', 'https://www.hankyung.com/feed/economy'),
}
DEFAULT = '가계대출, 금리, 보험, 주택담보, 신용대출, DSR, K-ICS'
_cache = {}
_lock = Lock()


class SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != 'https' or target.netloc != urlsplit(req.full_url).netloc:
            raise ValueError('Unexpected redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def text(value):
    value = html.unescape(html.unescape(value or ''))
    value = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', value, flags=re.S | re.I)
    return re.sub(r'\s+', ' ', re.sub('<[^>]*>', ' ', value)).strip()


def download(url):
    req = Request(url, headers={'User-Agent': 'RetailLendingResearch/1.0', 'Accept': 'application/rss+xml, application/xml, text/html'})
    with build_opener(SameHostRedirect()).open(req, timeout=12) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('Response too large')
    return data


def parse_feed(data, source):
    root = ET.fromstring(data)
    rows = []
    for item in root.findall('.//item')[:150]:
        title = text(item.findtext('title'))[:250]
        url = (item.findtext('link') or '').strip()
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname != urlsplit(SOURCES[source][2]).hostname:
            continue
        raw_date = item.findtext('pubDate') or item.findtext('{http://purl.org/dc/elements/1.1/}date')
        date = None
        try:
            date = parsedate_to_datetime(raw_date).isoformat()
        except (TypeError, ValueError, OverflowError):
            try:
                date = datetime.fromisoformat(raw_date).isoformat()
            except (TypeError, ValueError):
                pass
        if title:
            # Store a short publisher-provided excerpt, never full news articles.
            rows.append({'title': title, 'url': url, 'published_at': date,
                         'excerpt': text(item.findtext('description'))[:100],
                         'scope': 'RSS 제목·발행자 제공 짧은 요약 (본문 미조회)'})
    return rows


def parse_fss(data):
    page = data.decode('utf-8', errors='replace')
    rows = []
    for block in re.findall(r'<tr\b[^>]*>(.*?)</tr>', page, re.S | re.I):
        for href, label in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', block, re.S | re.I):
            url = urljoin(SOURCES['fss'][2], html.unescape(href))
            if urlsplit(url).hostname != 'www.fss.or.kr' or '/B0000188/view.do' not in url:
                continue
            title = text(label)[:250]
            date = re.search(r'20\d{2}[-.]\d{2}[-.]\d{2}', text(block))
            if title:
                rows.append({'title': title, 'url': url, 'published_at': date.group().replace('.', '-') if date else None,
                             'excerpt': '', 'scope': '공식 보도자료 목록 제목 (본문·첨부 미조회)'})
    return rows


def parse_fsc(data):
    rows = []
    page = data.decode('utf-8', errors='replace')
    for block in re.findall(r'<li\b[^>]*>(.*?)</li>', page, re.S):
        link = re.search(r'<a\b[^>]*href="(/no010101/\d+)(?:\?[^"]*)?"[^>]*>(.*?)</a>', block, re.S)
        if not link:
            continue
        date = re.search(r'20\d{2}[-.]\d{2}[-.]\d{2}', text(block))
        rows.append({'title': text(link[2])[:250], 'url': urljoin(SOURCES['fsc'][2], link[1]),
                     'published_at': date[0].replace('.', '-') if date else None,
                     'excerpt': '', 'scope': '공식 보도자료 목록 제목 (본문·첨부 미조회)'})
    return rows


class ReleaseBody(HTMLParser):
    def __init__(self, marker):
        super().__init__()
        self.marker = marker
        self.depth = 0
        self.finished = False
        self.ignored = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if self.finished:
            return
        if tag == 'div':
            if self.depth or self.marker in (dict(attrs).get('class') or '').split():
                self.depth += 1
        if self.depth and tag in ('script', 'style'):
            self.ignored += 1
        if self.depth and tag in ('p', 'br', 'li', 'tr', 'div'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag in ('script', 'style') and self.ignored:
            self.ignored -= 1
        if tag in ('p', 'li', 'tr', 'div'):
            self.parts.append('\n')
        if tag == 'div':
            self.depth -= 1
            self.finished = self.depth == 0

    def handle_data(self, data):
        if self.depth and not self.ignored:
            self.parts.append(re.sub(r'\s+', ' ', data))


def analyze_release(row, keywords, limit=3):
    url = row['url']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc not in ('www.fsc.go.kr', 'www.fss.or.kr'):
        raise ValueError('금융위·금감원 보도자료만 분석할 수 있습니다.')
    fsc = parsed.netloc == 'www.fsc.go.kr'
    if fsc:
        valid = re.fullmatch(r'/no010101/\d+', parsed.path)
    else:
        valid = parsed.path == '/fss/bbs/B0000188/view.do'
    if not valid:
        raise ValueError('보도자료 상세 페이지가 아닙니다.')
    page = download(url).decode('utf-8', errors='replace')
    if fsc:
        start = re.search(r'<div\b[^>]*class="board-view-wrap"', page)
        page = page[start.start():] if start else ''
    parser = ReleaseBody('cont' if fsc else 'n-dbdata')
    parser.feed(page)
    passages = list(dict.fromkeys(
        line.strip() for line in ''.join(parser.parts).splitlines()
        if 25 <= len(line.strip()) <= 650
    ))
    if not passages or not parser.finished:
        raise ValueError('HTML 본문에서 인용할 문장을 찾지 못했습니다. 원문과 첨부를 확인하세요.')
    words = [word.strip().casefold() for word in keywords.split(',') if word.strip()]
    def relevance(passage):
        compact = re.sub(r'\s+', '', passage.casefold())
        return sum(word in compact for word in words)

    ranked = sorted(passages, key=relevance, reverse=True)
    return {
        'title': row['title'], 'publisher': row['publisher'], 'published_at': row['published_at'],
        'url': url, 'evidence': ranked[:limit],
        'note': '보도자료 HTML 본문에서 발췌했습니다. 적용 업권과 시행일은 명시된 범위에서 확인하세요. 첨부파일은 별도 확인이 필요합니다.',
    }


def answer_release_question(question, days=30):
    compact = re.sub(r'\s+', '', question)
    agencies = []
    if re.search(r'금융위(?:원회)?', compact):
        agencies.append('fsc')
    if re.search(r'금감원|금융감독원', compact):
        agencies.append('fss')
    if not agencies and not re.search(r'보도자료|금융당국.*발표', compact):
        return None
    topics = [term for term in ('가계대출', '가계부채', '스트레스DSR', 'DSR', 'K-ICS',
                                '주택담보대출', '주담대', '신용대출', '보험계약대출', '금리')
              if term in compact]
    year_month = re.search(r'(?<!\d)(?:(20\d{2})년)?(1[0-2]|0?[1-9])월', compact)
    period = str(int(year_month[2])) + '월' if year_month else None
    focus = [('보험업권', '보험사', '보험회사', '보험'), ('시행일', '시행', '적용'),
             ('주택담보대출', '주담대'), ('기타대출',)]
    requested = [group for group in focus if any(term in compact for term in group)]
    if '전체' in compact or '전금융권' in compact:
        requested.insert(0, ('전체 가계대출', '全금융권가계대출', '전금융권가계대출',
                             f'{period or ""}가계대출('))
    cutoff = (datetime.now(timezone(timedelta(hours=9))) - timedelta(days=days)).date().isoformat()
    citations = []
    missing = []
    checked = set()
    for agency in agencies or ['fsc', 'fss']:
        publisher = SOURCES[agency][0]
        rows = source_fetch(agency, False)['rows']
        if topics:
            base = SOURCES[agency][2]
            params = ({'srchKey': 'sj', 'srchText': topics[0]} if agency == 'fsc'
                      else {'searchCnd': '1', 'searchWrd': topics[0]})
            url = base + ('&' if '?' in base else '?') + urlencode(params)
            try:
                parser = parse_fsc if agency == 'fsc' else parse_fss
                rows = parser(download(url)) + rows
            except (OSError, ValueError):
                pass
        attempts = 0
        for row in rows:
            if attempts == 2:
                break
            title = re.sub(r'\s+', '', row['title'])
            if row['url'] in checked or (topics and not any(term in title for term in topics)):
                continue
            if period and (not re.search(r'(?<!\d)' + period, title) or
                           (year_month[1] and year_month[1] + '년' not in title)):
                continue
            if not period and (not row['published_at'] or row['published_at'] < cutoff):
                continue
            checked.add(row['url'])
            attempts += 1
            terms = topics + [term for group in requested for term in group]
            try:
                release = analyze_release({**row, 'publisher': publisher}, ','.join(terms), limit=12)
            except (OSError, ValueError):
                continue
            passages = release['evidence']
            if requested:
                passages = list(dict.fromkeys(
                    line for group in requested
                    for line in [next((line for line in passages if any(
                        term in re.sub(r'\s+', '', line) for term in group)), None)]
                    if line is not None
                ))
            elif topics:
                passages = [line for line in passages if any(term in re.sub(r'\s+', '', line) for term in topics)]
            for passage in passages[:3]:
                citations.append({'text': passage, 'url': release['url'], 'title': release['title'],
                                  'publisher': publisher, 'published_at': release['published_at']})
            if passages:
                break
        if not any(item['publisher'] == publisher for item in citations):
            missing.append(publisher)
    answer = '질문과 관련된 공식 보도자료 본문 구절입니다.' if citations else '질문에 해당하는 공식 보도자료 본문 근거를 확인하지 못했습니다.'
    if missing:
        answer += '\n본문 근거 미확인: ' + ', '.join(missing)
    if citations:
        for group in requested:
            if not any(term in re.sub(r'\s+', '', item['text']) for item in citations for term in group):
                answer += '\n' + group[0] + ' 관련 근거 미확인'
        answer += '\n첨부파일에만 있는 내용은 별도 확인이 필요합니다.'
    return {'answer': answer, 'citations': citations, 'mode': 'official_sources', 'tools_used': ['공식 보도자료 본문 조회']}


def source_fetch(source, force):
    name, kind, url = SOURCES[source]
    with _lock:
        cached = _cache.get(source)
        if cached and not force and time.monotonic() - cached[0] < 900:
            result = copy.deepcopy(cached[1]); result['cached'] = True
            return result
    result = {'source': source, 'name': name, 'kind': kind, 'feed_url': url, 'cached': False,
              'fetched_at': datetime.now(timezone.utc).isoformat(), 'rows': []}
    try:
        data = download(url)
        parser = {'fss': parse_fss, 'fsc': parse_fsc}.get(source)
        result['rows'] = parser(data) if parser else parse_feed(data, source)
        if not result['rows']:
            raise ValueError('No parseable items')
        result['ok'] = True
    except Exception:
        result.update(ok=False, error='접근 차단·시간 초과 또는 목록 형식 변경으로 조회하지 못했습니다. 원문 사이트에서 확인하세요.')
    with _lock:
        _cache[source] = (time.monotonic(), copy.deepcopy(result))
    return result


def collect(keywords=DEFAULT, days=30, force=False):
    words = [w.strip() for w in keywords.split(',') if w.strip()][:12]
    if not words or any(len(w) > 40 for w in words) or not 1 <= days <= 90:
        raise ValueError('키워드(쉼표 구분, 항목당 40자 이하)와 기간(1~90일)을 확인하세요.')
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda source: source_fetch(source, force), SOURCES))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    items, seen = [], set()
    for result in results:
        for row in result['rows']:
            if not any(word.casefold() in (row['title'] + ' ' + row['excerpt']).casefold() for word in words):
                continue
            if row['published_at'] and row['published_at'][:10] < cutoff:
                continue
            if row['url'] in seen:
                continue
            seen.add(row['url'])
            items.append({**row, 'publisher': result['name'], 'kind': result['kind']})
    items.sort(key=lambda item: (item['kind'] == 'official', item['published_at'] or ''), reverse=True)
    items = items[:30]
    return {'ok': any(result['ok'] for result in results), 'provider': 'market_watch', 'rows': items,
            'keywords': words, 'days': days, 'fetched_at': datetime.now(timezone.utc).isoformat(),
            'source_status': [{k: v for k, v in result.items() if k != 'rows'} for result in results],
            'sources': [{'title': row['publisher'] + ' · ' + row['title'], 'url': row['url'],
                         'published_at': row['published_at']} for row in items],
            'error': '모든 수집처 조회에 실패했습니다.' if not any(r['ok'] for r in results) else None,
            'note': '공식 발표와 언론 보도를 구분한 제한적 최신 목록 탐색입니다. 전체 웹/과거기사 검색이 아닙니다. 제목·RSS 요약만 확인했고 본문/첨부/유료기사는 읽지 않았습니다. 제목만으로 확정 정책·시행일·수치를 추정하지 마세요. 공표일 미상 자료는 기간 검증 불가이며 같은 사건의 보도를 독립 근거로 중복 계산하지 마세요.'}

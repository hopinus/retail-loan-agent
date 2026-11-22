"""Build review candidates from the official HTML text, keeping uncertain fields explicit."""
import re
from datetime import date
from hashlib import sha256
from urllib.parse import urlencode
from market_watch import SOURCES, analyze_release, download, parse_fsc, parse_fss

UNKNOWN = '본문에서 확인되지 않음 · 원문 및 첨부 확인'


def releases(agency, term):
    source = SOURCES[agency]
    params = {'srchKey':'sj','srchText':term} if agency=='fsc' else {'searchCnd':'1','searchWrd':term}
    url = source[2] + (('&' if '?' in source[2] else '?') + urlencode(params) if term else '')
    rows = (parse_fsc if agency=='fsc' else parse_fss)(download(url))
    return [dict(r,publisher=source[0]) for r in rows if not term or term in r['title']][:20]


def effective_date(sentence, published):
    # Only dates explicitly tied to application or commencement.
    m = re.search(r'(?:(20\d\d|[’‘\x27]\d\d)[.년]\s*)?(\d{1,2})[.월]\s*(\d{1,2})(?:일|\.)?\s*(?:부터|시행|적용|～|~)',sentence)
    if not m or not published:
        return None
    year = int(m[1][-2:])+2000 if m[1] else int(published[:4])
    try: return date(year,int(m[2]),int(m[3])).isoformat()
    except ValueError: return None


def extract(row):
    if row['publisher'] == '금융감독원':
        from attachments import documents
        found = [action for name, url, paragraphs in documents(row) for action in dsr_attachment_rows(row, name, url, paragraphs)]
        if found:
            return found
    lines = analyze_release(row,'',limit=500)['evidence']
    numbered = [v for v in lines if re.match(r'^\[\d+\]\s*\(',v)]
    candidates = numbered or [s.strip() for v in lines for s in re.split(r'(?<=다\.)\s+',v)
        if re.search('대출|LTV|DSR',s) and re.search('시행|제한|금지|적용한다|확대한다|완화한다',s)
        and not re.search('기대|논의|검토 중|당부',s)]
    global_date = next((v for v in lines if '금번 조치' in v and '즉시 적용' in v and effective_date(v,row['published_at'])), '')
    transition = [v for v in lines if '종전' in v and ('규정' in v or '적용' in v)]
    actions=[]
    for line in dict.fromkeys(candidates):
        header=re.match(r'^\[\d+\]\s*\(([^)]+)\)\s*(.*)',line)
        target=header[2] if header else line
        product = ('주택담보대출' if re.search('주담대|주택담보|LTV',line) and not re.search('사업자대출|전세대출',line)
                   else '신용대출' if '신용대출' in line else '보험계약대출' if '보험계약대출' in line else '')
        date_line=line if effective_date(line,row['published_at']) else (global_date if numbered else '')
        exceptions=[line] if re.search('제외|예외|다만',line) else []
        if numbered and global_date: exceptions += ['발표 공통 경과조치 · '+t for t in transition]
        key=sha256((row['url']+'\n'+line).encode()).hexdigest()
        actions.append(dict(id=key,title=row['title']+' · '+(header[1] if header else line[:40]),
            publisher=row['publisher'],url=row['url'],published_at=row['published_at'] or '미확인',
            quote=line,target=target,effective=effective_date(date_line,row['published_at']) or UNKNOWN,
            date_evidence=date_line,exceptions=' '.join(exceptions) or UNKNOWN,product=product))
    return actions[:20]


def dsr_attachment_rows(row, name, url, lines):
    # The commencement paragraph scopes the numbered measures in this implementation plan.
    commencement = next((s for s in lines if '모든 가계대출' in s and '시행' in s and effective_date(s, row['published_at'])), '')
    if not commencement or '스트레스 DSR' not in name or '별첨' not in name:
        return []
    transition = next((s for s in lines if '종전규정' in s and '매매계약' in s), '')
    result = []
    for i, line in enumerate(lines):
        if '신용대출은 잔액이' in line and '경우에만' in line:
            product = '신용대출'
            target = line.split('다만,')[-1].split('경우에만')[0].strip() + '경우'
            exception = line
        elif '지방 주담대에 대해서는' in line and '유예' in line:
            product = '주택담보대출'
            target = '지방 주택담보대출'
            exception = ' '.join(s for s in [line, transition] if s)
        else:
            continue
        source = f'{name} · 본문 문단 {i+1}'
        result.append(dict(id=sha256((url+line).encode()).hexdigest(), title=source,
            publisher=row['publisher'], url=url, published_at=row['published_at'], quote=line,
            target=target, effective=effective_date(commencement,row['published_at']),
            date_evidence=commencement, exceptions=exception, product=product))
    return result


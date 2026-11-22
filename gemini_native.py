"""Gemini native generateContent REST integration.

Avoids the OpenAI-compatibility function-call translation which may return HTTP
400 on Gemini 3-family models. Preserves Gemini's original thought signatures
by replaying the entire model response when returning function results.
No secrets are logged or returned.
"""
from __future__ import annotations
import json
import re
import gzip
import time
import random
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Callable
from urllib.parse import urlencode

API_BASE='https://generativelanguage.googleapis.com/v1beta/models/'
VALID_MODEL=re.compile(r'^[a-zA-Z0-9_.-]{2,100}$')

class GeminiNativeError(Exception):
    def __init__(self, status: int | str, public_message: str):
        self.status=status
        self.public_message=public_message
        super().__init__(f'HTTP {status}: {public_message}')

def post(key: str, model: str, payload: dict) -> dict:
    if not VALID_MODEL.fullmatch(model):
        raise GeminiNativeError('CONFIG','모델 이름이 올바르지 않습니다.')
    url=f'{API_BASE}{model}:generateContent'
    body=json.dumps(payload,ensure_ascii=False).encode('utf-8')
    req=Request(url,body,headers={
        'Content-Type':'application/json',
        'x-goog-api-key':key,
    },method='POST')
    return request_json(req, key)


def request_json(req: Request, key: str) -> dict:
    # Retry only explicit transient server failures, never invalid keys/quota.
    for attempt in range(3):
        try:
            return _request_json_once(req, key)
        except GeminiNativeError as exc:
            if exc.status not in (502, 503, 504):
                raise
            if attempt == 2:
                raise GeminiNativeError(exc.status,
                    'Gemini 서버가 일시적으로 혼잡하여 자동 재시도 2회 후에도 응답하지 못했습니다. '
                    '잠시 후 같은 질문을 다시 보내 주세요. 계속되면 연결 창에서 다른 모델을 선택해 주세요.') from None
            time.sleep(2 ** attempt + random.uniform(0, 0.5))


def _request_json_once(req: Request, key: str) -> dict:
    try:
        with urlopen(req,timeout=55) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        msg = '응답을 해석하지 못했습니다. Google API 또는 중간 프록시의 응답 형식을 확인해야 합니다.'
        raw = ''
        try:
            body = exc.read(64000)
            if body.startswith(b'\x1f\x8b'):
                body = gzip.decompress(body)
            raw=body.decode('utf-8-sig',errors='replace')
            j=json.loads(raw)
            # Some Google gateways return an array of error objects.
            if isinstance(j, list):
                j = next((item for item in j if isinstance(item, dict) and 'error' in item), {})
            error = j.get('error', {}) if isinstance(j, dict) else {}
            if isinstance(error, dict):
                message = error.get('message')
                status = error.get('status')
                reasons = [detail.get('reason') for detail in error.get('details', [])
                           if isinstance(detail, dict) and isinstance(detail.get('reason'), str)]
                parts = [str(part) for part in [status, message, *reasons] if part]
                if parts:
                    msg = ' | '.join(parts)
        except Exception:
            # Report a bounded, redacted text explanation for HTML/proxy errors.
            safe = raw.replace(key, '[API_KEY]') if key else raw
            safe = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', safe, flags=re.S | re.I)
            safe = re.sub(r'<[^>]*>', ' ', safe)
            safe = re.sub(r'\s+', ' ', safe).strip()
            safe = re.sub(r'[A-Za-z0-9_.+/=-]{24,}', '[REDACTED]', safe)
            content_type = exc.headers.get('Content-Type', 'unknown') if exc.headers else 'unknown'
            msg = f'JSON 이외의 오류 응답 ({content_type}): {safe[:400] or "본문 없음"}'
        # Avoid reflecting a key or excessively verbose/sensitive server payload.
        if key: msg=msg.replace(key,'[API_KEY]')
        msg=re.sub(r'AIza[a-zA-Z0-9_-]{20,}', '[API_KEY]',msg)
        msg=re.sub(r'AQ\.[a-zA-Z0-9_-]{15,}', '[API_KEY]',msg)
        msg=re.sub(r'https?://[^\s]+key=[^\s&]+','[URL]',msg)
        raise GeminiNativeError(exc.code,str(msg)[:650]) from None
    except URLError:
        raise GeminiNativeError('NETWORK','Google API 연결 실패. 네트워크·방화벽을 확인해 주세요.') from None
    except (TimeoutError, OSError):
        raise GeminiNativeError('NETWORK','Google API에 연결하지 못했습니다.') from None

def list_models(key: str) -> list[str]:
    """Discover generateContent models, including all result pages."""
    models = set()
    token = ''
    seen = set()
    while True:
        query = {'pageSize': 100}
        if token:
            query['pageToken'] = token
        req = Request(API_BASE.rstrip('/') + '?' + urlencode(query),
                      headers={'x-goog-api-key': key}, method='GET')
        data = request_json(req, key)
        for model in data.get('models', []):
            name = model.get('name', '').removeprefix('models/')
            if 'generateContent' in model.get('supportedGenerationMethods', []) and VALID_MODEL.fullmatch(name):
                models.add(name)
        token = data.get('nextPageToken', '')
        if not token:
            return sorted(models)
        if token in seen:
            raise GeminiNativeError('RESPONSE', '모델 목록 페이지 응답이 반복됩니다.')
        seen.add(token)


def extract_text(data: dict) -> str:
    parts=(data.get('candidates') or [{}])[0].get('content',{}).get('parts',[])
    return '\n'.join(p['text'] for p in parts if isinstance(p.get('text'),str) and not p.get('thought'))

def gemini_ping(key: str, model: str) -> str:
    data=post(key,model,{'contents':[{'role':'user','parts':[{'text':'안녕하세요. 한 문장으로 응답해주세요.'}]}]})
    return extract_text(data) or '응답은 성공했으나 텍스트가 없습니다.'

def gemini_chat(key: str, model: str, system: str, message: str,
                history: list[dict], resolver: Callable[[str],dict], *,
                require_scenario: bool = False) -> dict:
    # The history is presented as contextual *data*. User/model alternation is
    # simpler and more resilient when only the current turn is sent as API contents.
    transcript=[]
    for h in history[-8:]:
        if h.get('role') in ('user','assistant'):
            transcript.append(f"{h['role']}: {str(h.get('content',''))[:1300]}")
    prompt=('이전 대화(참고 자료):\n'+'\n'.join(transcript)+'\n\n' if transcript else '')+f'현재 사용자 질문: {message}'
    contents=[{'role':'user','parts':[{'text':prompt}]}]
    tools=[{'functionDeclarations':[{
        'name':'get_analysis_data',
        'description':'소매여신 내부 집계·시나리오·등록 근거자료 조회. 사실 근거 확인에 반드시 사용하세요.',
        'parameters':{
            'type':'OBJECT',
            'properties':{'kind':{'type':'STRING','enum':['portfolio','scenario','market','policy','references','external','all'],
                                  'description':'조회할 자료 종류'}},
            'required':['kind']
        }
    }]}]
    cfg={'systemInstruction':{'parts':[{'text':system}]}, 'contents': contents,
         'tools':tools, 'toolConfig':{'functionCallingConfig':{'mode':'AUTO'}}}
    scenario_tool = 'get_current_scenario'
    if require_scenario:
        cfg['tools'] = [{'functionDeclarations': [{
            'name': scenario_tool,
            'description': '현재 적용된 불리 시나리오의 상품별 순증, 전체 순증, 가정한도 잔여를 계산합니다.',
        }]}]
        cfg['toolConfig'] = {'functionCallingConfig': {
            'mode': 'ANY', 'allowedFunctionNames': [scenario_tool],
        }}
    used=[]
    for _ in range(4):
        data=post(key,model,cfg)
        content=(data.get('candidates') or [{}])[0].get('content',{})
        calls=[p['functionCall'] for p in content.get('parts',[]) if 'functionCall' in p]
        if require_scenario and not used and [call.get('name') for call in calls] != [scenario_tool]:
            raise GeminiNativeError('TOOL', '현재 시나리오 계산 도구 호출을 확인하지 못했습니다.')
        if require_scenario and used:
            answer = extract_text(data)
            if calls or not answer:
                raise GeminiNativeError('TOOL', '현재 시나리오 계산 결과에 대한 텍스트 응답을 받지 못했습니다.')
            return {'answer': answer, 'mode': 'live', 'tools_used': used, 'sources': []}
        if not calls:
            answer=extract_text(data)
            if used and answer:
                return {'answer':answer,'mode':'live','tools_used':used,'sources':[]}
            # If tool was not selected, provide authenticated deterministic data
            # explicitly and request a *text-only* grounded response.
            break
        # Preserve the ENTIRE Gemini model content (including thoughtSignature)
        # so multi-turn function calling can resume without HTTP 400.
        contents.append(content)
        response_parts=[]
        for call in calls:
            if require_scenario:
                name = scenario_tool
                result = resolver('scenario')
                used.append('scenario')
            elif call.get('name')!='get_analysis_data':
                result={'error':'알 수 없는 도구'}
                name='get_analysis_data'
            else:
                name=call['name']
                kind=str((call.get('args') or {}).get('kind','portfolio'))
                result=resolver(kind)
                used.append(kind)
            fr={'name':name,'response':{'result':result}}
            if call.get('id'): fr['id']=call['id']
            response_parts.append({'functionResponse':fr})
        contents.append({'role':'user','parts':response_parts})
        if require_scenario:
            cfg['toolConfig'] = {'functionCallingConfig': {'mode': 'NONE'}}
    # A deterministic local retrieval step is always available if Gemini does
    # not select a function or a tool loop exceeds the application step cap.
    # This is labeled 'server_context' not claimed as an LLM tool call.
    data=resolver('portfolio')
    refs=resolver('references')
    scenario=resolver('scenario')
    question=(prompt+'\n\n아래는 서버 계산 엔진이 검증한 입력 데이터입니다. '
             '외부 최신 뉴스는 조회하지 않았습니다. 반드시 이 자료에 근거해 답하세요.\n'
             +json.dumps({'portfolio':data,'scenario':scenario,'reference_notes':refs}, ensure_ascii=False))
    final=post(key,model,{'systemInstruction':{'parts':[{'text':system}]},
                           'contents':[{'role':'user','parts':[{'text':question}]}]})
    answer=extract_text(final)
    if not answer: raise GeminiNativeError('EMPTY','모델이 텍스트 답변을 반환하지 않았습니다.')
    return {'answer':answer,'mode':'live','tools_used':used+['server_context'], 'sources':[]}

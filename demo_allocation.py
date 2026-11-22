"""Reproduce the synthetic submission case without external services."""

from pathlib import Path

from fastapi.testclient import TestClient

from app import PRODUCTS, app

REFERENCE = {
    'category': 'market', 'title': '보험계약대출 이용 증가 (가상)',
    'content': '평가용 가상 자료에서 보험계약대출 이용 증가를 제시합니다.',
    'published_at': '2026-11-01',
}


def reproduce(client):
    for route in ('/', '/static/allocation.js'):
        client.get(route).raise_for_status()
    sample = Path(__file__).with_name('data') / 'sample_portfolio.csv'
    client.post('/api/upload', files={'file': (sample.name, sample.read_bytes())}).raise_for_status()
    client.post('/api/references', json=REFERENCE).raise_for_status()
    source_id = next(key for key, source in client.get('/api/allocation/evidence').raise_for_status().json().items()
                     if source['title'] == REFERENCE['title'])
    mortgage, credit, policy = PRODUCTS
    strategy = {
        'cap': 35, 'products': {
            mortgage: {'priority': 2, 'target': -150, 'net_max': -150},
            credit: {'priority': 1, 'target': 150},
            policy: {'priority': 3, 'execution_max': 200},
        },
        'scenarios': [{
            'name': '보험계약대출 이용 증가', 'source_id': source_id, 'assumptions_approved': True,
            'rationale': '가상 근거를 검토해 최소 실행 180억 원, 회수 5억 원 감소를 승인합니다.',
            'impacts': {policy: {'execution_floor': 180, 'repayment_delta': -5}},
        }],
    }
    comparison = client.post('/api/allocation/compare', json=strategy).raise_for_status().json()
    recommended, alternative = comparison['cases'][1]['plans']
    assert [row['net'] for row in recommended['result']['rows']] == [-200, 150, 85]
    assert [row['net'] for row in alternative['result']['rows']] == [-180, 130, 85]
    selection = {'cap': 35, 'overrides': recommended['overrides']}
    applied = client.post('/api/scenario', json=selection).raise_for_status().json()
    assert (applied['total_net'], applied['assumed_remaining']) == (35, 0)
    assert [(row['execution'], row['repayment']) for row in applied['rows']] == [(300, 500), (270, 120), (180, 95)]
    report = client.post('/api/report', json={**selection, 'allocation': {
        'comparison_id': comparison['comparison_id'], 'scenario_index': 1, 'plan_index': 0,
    }}).raise_for_status().text
    assert all(value in report for value in (
        REFERENCE['title'], '내부 목표와 필수 제약', '담당자가 승인한 실행·회수 가정',
        '총순증 상한 및 상품 우선순위', '같은 시나리오의 대안과 차이', '기존 실행계획 유지',
        '<td>신용대출</td><td>150</td><td>130</td><td>20</td>',
    ))
    return comparison, report


if __name__ == '__main__':
    with TestClient(app, headers={'X-Session-Id': 'submission-demo'}) as client:
        _, report = reproduce(client)
    target = Path('retail-lending-demo-report.html')
    target.write_text(report, encoding='utf-8')
    print(f'PASS: comparison, selected plan, report. Output: {target.resolve()}')

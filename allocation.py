"""Compare monthly execution plans under explicit strategy and market assumptions."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


Amount = Annotated[Decimal, Field(ge=-10**9, le=10**9, decimal_places=5)]
Nonnegative = Annotated[Decimal, Field(ge=0, le=10**9, decimal_places=5)]
TICK = Decimal('0.00001')
MAX_EXECUTION = Decimal(10**9)


class AllocationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ProductStrategy(AllocationInput):
    target: Amount | None = None
    priority: int = Field(ge=1, le=3)
    execution_min: Nonnegative = Decimal(0)
    execution_max: Nonnegative = MAX_EXECUTION
    net_min: Amount | None = None
    net_max: Amount | None = None


class MarketImpact(AllocationInput):
    execution_floor: Nonnegative | None = None
    execution_ceiling: Nonnegative | None = None
    repayment_delta: Amount = Decimal(0)


class MarketScenario(AllocationInput):
    name: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=2500)
    rationale: str = Field(min_length=1, max_length=600)
    impacts: dict[str, MarketImpact]
    assumptions_approved: bool


class PolicyReview(AllocationInput):
    policy_id: str = Field(min_length=1,max_length=80)
    decision: Literal['이번 달 적용', '향후 시나리오', '해당 없음']
    reason: str = Field(min_length=1, max_length=500)
    monthly_ceiling: Nonnegative | None = None


class AllocationRequest(AllocationInput):
    cap: Nonnegative
    policy_review: PolicyReview | None = None
    policy_reviews: list[PolicyReview] = Field(default_factory=list, max_length=20)
    products: dict[str, ProductStrategy]
    scenarios: list[MarketScenario] = Field(default_factory=list, max_length=5)


def money(value):
    return Decimal(str(value)).quantize(TICK)


def compare(data, request, evidence, compute):
    products = {row['product']: row for row in data}
    if request.products.keys() != products.keys():
        raise ValueError('세 상품의 전략 조건을 입력해 주세요.')
    for product, rule in request.products.items():
        if rule.execution_min > rule.execution_max:
            raise ValueError(f'{product}의 실행 하한이 상한보다 큽니다.')
        if rule.net_min is not None and rule.net_max is not None and rule.net_min > rule.net_max:
            raise ValueError(f'{product}의 순증 하한이 상한보다 큽니다.')

    cases = [compare_case(products, request, compute)]
    for scenario in request.scenarios:
        if not scenario.name.strip() or not scenario.rationale.strip():
            raise ValueError('시나리오 이름과 외부 근거를 가정에 적용한 이유를 입력해 주세요.')
        source = evidence.get(scenario.source_id)
        if source is None:
            raise ValueError(f'{scenario.name}: 현재 자료 목록에서 근거를 다시 선택해 주세요.')
        if not scenario.assumptions_approved:
            raise ValueError(f'{scenario.name}: 외부 근거와 실행·회수 가정을 검토해 승인해 주세요.')
        if scenario.impacts.keys() - products.keys():
            raise ValueError('지원하지 않는 상품이 시나리오에 포함되어 있습니다.')
        if not any(i.execution_floor is not None or i.execution_ceiling is not None or i.repayment_delta
                   for i in scenario.impacts.values()):
            raise ValueError(f'{scenario.name}: 최소 실행액, 실행 가능액 상한, 회수 변화액 중 하나를 입력해 주세요.')
        case = compare_case(products, request, compute, scenario, source)
        for plan in case['plans']:
            baseline = next((p for p in cases[0]['plans'] if p['label'] == plan['label']), None)
            baseline = baseline or next(iter(cases[0]['plans']), None)
            plan['baseline_label'] = baseline['label'] if baseline else None
            plan['changes'] = [
                {'product': row['product'], **{
                    field: round(row[field] - previous[field], 5)
                    for field in ('execution', 'repayment', 'net')
                }}
                for row, previous in zip(plan['result']['rows'], baseline['result']['rows'])
            ] if baseline else []
        cases.append(case)
    return cases


def compare_case(products, request, compute, scenario=None, source=None):
    case = {
        'name': scenario.name if scenario else '기준 시나리오',
        'rationale': scenario.rationale if scenario else '집계자료의 회수와 기타조정을 기준으로 계산합니다.',
        'source': source, 'issues': [], 'assumptions': [], 'plans': [],
    }
    bounds = {}
    repayment = {}
    net_offsets = {}
    for name, row in products.items():
        rule = request.products[name]
        impact = scenario.impacts.get(name, MarketImpact()) if scenario else MarketImpact()
        repayment[name] = money(row['repayment']) + impact.repayment_delta
        offset = money(row['adjustment']) - repayment[name]
        net_offsets[name] = offset
        lower, upper = rule.execution_min, rule.execution_max
        if impact.execution_floor is not None:
            lower = max(lower, impact.execution_floor)
        if impact.execution_ceiling is not None:
            upper = min(upper, impact.execution_ceiling)
        if rule.net_min is not None:
            lower = max(lower, rule.net_min - offset)
        if rule.net_max is not None:
            upper = min(upper, rule.net_max - offset)
        case['assumptions'].append({
            'product': name, 'repayment': float(repayment[name]),
            'repayment_delta': float(impact.repayment_delta),
            'execution_floor': (None if impact.execution_floor is None else float(impact.execution_floor)),
            'execution_ceiling': (None if impact.execution_ceiling is None
                                  else float(impact.execution_ceiling)),
            'execution_min': float(lower), 'execution_max': float(upper),
        })
        if not 0 <= repayment[name] <= MAX_EXECUTION:
            case['issues'].append(f'{name}의 시나리오 회수액이 입력 범위를 벗어납니다.')
        if lower > upper:
            case['issues'].append(f'{name}의 필수 조건 충돌 · 실행 하한 {lower:,.5f}억 / 상한 {upper:,.5f}억')
        bounds[name] = (lower, upper)

    if scenario and not case['issues']:
        # Isolate the external shock before internal priorities and the shared cap redistribute execution.
        effects = []
        for name, row in products.items():
            impact = scenario.impacts.get(name, MarketImpact())
            original = money(row['execution'])
            execution = original
            if impact.execution_floor is not None:
                execution = max(execution, impact.execution_floor)
            if impact.execution_ceiling is not None:
                execution = min(execution, impact.execution_ceiling)
            change = execution - original
            effects.append({'product': name, 'execution_delta': change, 'repayment_delta': impact.repayment_delta,
                            'net_delta': change - impact.repayment_delta})
        case['external_effect'] = {
            'rows': [{k: float(v) if isinstance(v, Decimal) else v for k, v in effect.items()} for effect in effects],
            'total_delta': float(sum(effect['net_delta'] for effect in effects)),
        }

    minimum_net = sum(bounds[name][0] + net_offsets[name] for name in products)
    if minimum_net > request.cap and not case['issues']:
        case['issues'].append(f'상품별 최소 실행을 적용해도 총순증 상한을 {minimum_net - request.cap:,.5f}억 원 초과합니다.')
    if case['issues']:
        return case

    # With fixed repayments, each extra unit of execution uses one unit of the
    # shared net-increase limit. Fully serve each priority before the next one.
    priority = sorted(products, key=lambda name: request.products[name].priority)
    targets = {name: (request.products[name].target - net_offsets[name]
                      if request.products[name].target is not None
                      else money(products[name]['execution'])) for name in products}
    goal_priority = sorted(priority, key=lambda name: request.products[name].target is None)
    baseline = {name: money(row['execution']) for name, row in products.items()}
    strategy_data = [dict(row, target=request.products[name].target)
                     for name, row in products.items()]
    approaches = [('전략 목표 우선', targets, goal_priority), ('기존 실행계획 유지', baseline, priority)]
    for label, desired, order in approaches:
        headroom = request.cap - minimum_net
        overrides = {}
        decisions = {}
        for name in order:
            lower, upper = bounds[name]
            execution = min(max(desired[name], lower), upper, lower + headroom)
            reasons = []
            rule = request.products[name]
            impact = scenario.impacts.get(name, MarketImpact()) if scenario else MarketImpact()
            if execution > desired[name]:
                if lower == rule.execution_min:
                    reasons.append('내부 실행 하한')
                if rule.net_min is not None and lower == rule.net_min - net_offsets[name]:
                    reasons.append('내부 순증 하한')
                if lower == impact.execution_floor:
                    reasons.append('환경상 최소 실행 예상액')
            if execution < desired[name]:
                if execution == upper:
                    if upper == rule.execution_max:
                        reasons.append('내부 실행 상한')
                    if rule.net_max is not None and upper == rule.net_max - net_offsets[name]:
                        reasons.append('내부 순증 상한')
                    if upper == impact.execution_ceiling:
                        reasons.append('환경상 실행 가능액 상한')
                if execution == lower + headroom:
                    reasons.append('총순증 상한 및 상품 우선순위')
            decisions[name] = {'desired_execution': float(desired[name]), 'limits': reasons}
            headroom -= execution - lower
            overrides[f'{name}.execution'] = float(execution)
            overrides[f'{name}.repayment'] = float(repayment[name])
            overrides[f'{name}.adjustment'] = float(money(products[name]['adjustment']))
        result = compute(strategy_data, float(request.cap), overrides)
        result['rows'] = [
            dict(row, target=None if row['target'] is None else float(row['target']))
            for row in result['rows']
        ]
        if case['plans'] and overrides == case['plans'][0]['overrides']:
            continue
        case['plans'].append({'label': label, 'overrides': overrides, 'result': result,
                              'decisions': decisions})
    return case

def stress_comparison(data, request, cases, compute):
    """Freeze executions at the approved planning case, then vary collections and bounds."""
    products = {row['product']: row for row in data}
    credit, policy = '신용대출', '보험계약대출'
    order = sorted(products, key=lambda name: (name != credit, request.products[name].priority))
    rules = {name: request.products[name].model_copy(update={'priority': rank})
             for rank, name in enumerate(order, 1)}
    output = []
    for scenario, anchor in zip(request.scenarios, cases[1:]):
        plans = [('기존 계획 유지', {n: money(r['execution']) for n, r in products.items()}, [])]
        for label, reserve in [('신용대출 목표 우선', 0), ('총량 여유 5억 원 확보', 5)]:
            planning = request.model_copy(update={'cap': request.cap - reserve, 'products': rules})
            case = compare_case(products, planning, compute, scenario, anchor['source'])
            plan = case['plans'][0] if case['plans'] else None
            fixed = {r['product']: money(r['execution']) for r in plan['result']['rows']} if plan else {}
            plans.append((label, fixed, case['issues']))
        impacts = scenario.impacts.copy()
        impact = impacts.get(policy, MarketImpact())
        impacts[policy] = impact.model_copy(update={'repayment_delta': impact.repayment_delta - 5})
        stress = scenario.model_copy(update={'name': '회수 추가 둔화', 'impacts': impacts})
        stressed = compare_case(products, request, compute, stress, anchor['source'])
        rows = []
        for env in (cases[0], anchor, stressed):
            assumptions = {r['product']: r for r in env['assumptions']}
            offsets = {n: money(products[n]['adjustment']) - money(a['repayment'])
                       for n, a in assumptions.items()}
            for label, fixed, issues in plans:
                row = {'scenario': env['name'], 'plan': label, 'issues': issues or env['issues']}
                rows.append(row)
                if not fixed or any(not 0 <= a['repayment'] <= MAX_EXECUTION for a in assumptions.values()):
                    continue
                total = sum(fixed.values()) + sum(offsets.values())
                target = request.products[credit].target
                row.update(total=float(total), excess=float(max(0, total - request.cap)),
                           shortfall=None if target is None else float(max(0, target-fixed[credit]-offsets[credit])))
                if row['issues']:
                    continue
                # Project onto each product's feasible interval, then cut only the remaining excess.
                adjusted = {n: min(max(v, money(assumptions[n]['execution_min'])),
                                   money(assumptions[n]['execution_max'])) for n, v in fixed.items()}
                overflow = max(0, sum(adjusted.values()) + sum(offsets.values()) - request.cap)
                for n in reversed(order):
                    cut = min(overflow, adjusted[n] - money(assumptions[n]['execution_min']))
                    adjusted[n] -= cut
                    overflow -= cut
                row['changes'] = {n: float(adjusted[n]-fixed[n]) for n in products}
                row['adjusted_net'] = float(sum(adjusted.values()) + sum(offsets.values()))
        output.append({'anchor': scenario.name, 'plans': {label: {n: float(v) for n,v in fixed.items()}
                                                         for label, fixed, _ in plans}, 'rows': rows})
    return output

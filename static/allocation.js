'use strict';

const allocationForm = $('allocationForm');
const allocationNumber = new Intl.NumberFormat('ko-KR', {maximumFractionDigits: 5});
const allocationAmount = value => value === null ? '—' : allocationNumber.format(value);
const strategicFields = [
  ['target', '순증 목표', -1e9], ['priority', '우선순위', 1],
  ['execution_min', '실행 하한', 0], ['execution_max', '실행 상한', 0],
  ['net_min', '순증 하한', -1e9], ['net_max', '순증 상한', -1e9],
];
const impactFields = [
  ['execution_floor', '최소 실행 예상액', 0],
  ['execution_ceiling', '실행 가능액 상한', 0],
  ['repayment_delta', '회수 변화액', -1e9],
];
let allocationEvidence = {};
let evidenceRequest = 0;
let allocationRevision = 0;
let strategyEdited = false;

function allocationInput(label, min, value) {
  const input = el('input');
  input.type = 'number';
  input.min = min;
  input.max = 1e9;
  input.step = '0.00001';
  input.value = value ?? '';
  input.setAttribute('aria-label', label);
  return input;
}

function allocationProductRow(product, fields, defaults = {}) {
  const row = el('tr');
  row.dataset.product = product;
  const heading = el('th', '', product);
  heading.scope = 'row';
  row.append(heading);
  for (const [key, label, min] of fields) {
    let field;
    if (key === 'priority') {
      field = el('select');
      field.setAttribute('aria-label', product + ' ' + label);
      for (const rank of [1, 2, 3]) field.add(new Option(String(rank), String(rank)));
      field.value = defaults[key];
    } else {
      field = allocationInput(product + ' ' + label, min, defaults[key]);
    }
    field.name = key;
    const cell = el('td');
    cell.append(field);
    row.append(cell);
  }
  return row;
}

function invalidateAllocation() {
  ++allocationRevision;
  $('allocationResults').replaceChildren();
  $('allocationStatus').textContent = '';
}

function loadAllocationBaseline() {
  if (!app.baseline) return;
  if (!strategyEdited) {
    allocationForm.elements.cap.value = app.baseline.assumed_cap;
    $('allocationRules').replaceChildren(...app.baseline.rows.map((row, index) =>
      allocationProductRow(row.product, strategicFields, {
        target: row.target === null ? null : Number(row.target.toFixed(5)), priority: index + 1,
      })));
  }
  $('allocationBasis').textContent = `${app.state.month} · ${app.state.data_origin}`;
  all('#allocationCases [name=assumptions_approved]').forEach(input => { input.checked = false; });
  invalidateAllocation();
  $('allocationSubmit').disabled = false;
}

function fillEvidence(select) {
  const selected = select.value;
  select.replaceChildren(new Option('외부 근거 선택', ''));
  for (const [id, source] of Object.entries(allocationEvidence)) {
    select.add(new Option(`${source.publisher} · ${source.published_at || '공표일 미확인'} · ${source.title}`, id));
  }
  if (selected && !allocationEvidence[selected]) select.add(new Option('목록에서 빠진 근거 · 다시 선택 필요', selected));
  select.value = selected;
  renderEvidencePreview(select);
}

function renderEvidencePreview(select) {
  const preview = select.closest('fieldset')?.querySelector('.allocation-source-preview');
  if (!preview) return;
  const source = allocationEvidence[select.value];
  preview.replaceChildren();
  if (source) {
    preview.append(sourceSummary(source));
    if (source.excerpt) preview.append(el('p', 'note', source.excerpt));
  }
}

async function refreshAllocationEvidence() {
  const request = ++evidenceRequest;
  const status = $('allocationEvidenceStatus');
  status.textContent = '근거 목록을 확인하는 중입니다.';
  try {
    const sources = await api('/api/allocation/evidence');
    if (request !== evidenceRequest) return;
    allocationEvidence = sources;
    all('#allocationCases select').forEach(fillEvidence);
    const count = Object.keys(sources).length;
    status.textContent = count ? `선택 가능한 근거 ${count}건` : '자료 관리에서 외부 자료를 수집하거나 등록하세요.';
  } catch (error) {
    if (request === evidenceRequest) status.textContent = error.message;
  }
}

function sourceSummary(source) {
  const summary = el('p', 'note');
  summary.append(document.createTextNode(
    `${source.publisher} · ${source.published_at || '공표일 미확인'} · ${source.scope} · `));
  if (/^https?:\/\//i.test(source.url)) {
    const link = el('a', 'download-link', source.title);
    link.href = source.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    summary.append(link);
  } else {
    summary.append(document.createTextNode(source.title));
  }
  return summary;
}

function suggestImpact(card) {
  const source = allocationEvidence[card.querySelector('select').value];
  const status = card.querySelector('.allocation-hint');
  if (!source) {
    status.textContent = '외부 근거를 먼저 선택하세요.';
    return;
  }
  const signals = new Map();
  for (const sentence of [source.title, ...(source.excerpt || '').split(/[.!?。\n]/)]) {
    const text = sentence.replace(/\s/g, '');
    if (/않|아니|부인|철회|미확정|사실무근|여부|검토|가능성|둔화/.test(text)) continue;
    const matches = [/주택담보대출|주담대|LTV/i, /신용대출/, /보험계약대출|약관대출/]
      .map((pattern, i) => pattern.test(text) ? PRODUCTS[i] : null).filter(Boolean);
    if (matches.length !== 1) continue;
    const increasing = /(?:수요|신청|이용)(?:량|액|건수)?(?:이|가|은|는)?(?:증가|확대)/.test(text);
    const restricted = /강화|축소|제한|중단/.test(text);
    if (increasing === restricted) continue;
    const direction = increasing ? '증가' : '제약';
    signals.set(matches[0] + direction, {product: matches[0], increasing, sentence});
  }
  if (signals.size !== 1) {
    status.textContent = '제목·요약에서 하나의 상품과 변화 방향을 특정하기 어렵습니다. 원문을 검토하고 가정을 입력하세요.';
    return;
  }
  const {product, increasing: policyLoan, sentence} = [...signals.values()][0];
  const baseline = app.baseline.rows.find(row => row.product === product).execution;
  const input = [...card.querySelectorAll('tbody tr')].find(row => row.dataset.product === product)
    .querySelector(policyLoan ? '[name=execution_floor]' : '[name=execution_ceiling]');
  const rationale = card.querySelector('textarea');
  if (input.value !== '' || rationale.value.trim()) {
    status.textContent = '입력된 가정을 유지했습니다. 가정 초안을 쓰려면 해당 금액과 가정 근거를 비워 주세요.';
    return;
  }
  if (baseline === 0 || (policyLoan && baseline > 1e9 / 1.1)) {
    status.textContent = '기준 실행액으로 10% 민감도 초안을 만들 수 없습니다. 금액을 직접 입력하세요.';
    return;
  }
  input.value = Number((baseline * (policyLoan ? 1.1 : 0.9)).toFixed(5));
  card.querySelector('[name=assumptions_approved]').checked = false;
  rationale.value = `근거 문장 “${sentence.slice(0, 200)}”의 ${policyLoan ? '이용 증가' : '대출 제약'} 신호가 ${product}에 적용된다고 가정합니다. `
    + `기준 실행액 대비 ${policyLoan ? '10% 증가한 금액을 최소 실행 예상액' : '10% 감소한 금액을 실행 가능액 상한'}으로 둔 민감도 가정입니다. 실제 영향은 적용 범위와 내부 자료를 확인해 조정하세요.`;
  status.textContent = '10%는 민감도 검토용 초기값입니다. 가정과 금액을 검토한 뒤 비교하세요.';
  invalidateAllocation();
}

function addAllocationCase() {
  const container = $('allocationCases');
  if (container.children.length >= 5) return;
  const card = el('fieldset', 'allocation-case');
  const name = el('input');
  name.maxLength = 80;
  name.required = true;
  name.value = '외부 환경 변화';
  const select = el('select');
  select.required = true;
  fillEvidence(select);
  const rationale = el('textarea');
  rationale.maxLength = 600;
  rationale.required = true;
  rationale.rows = 2;
  const approved = el('input');
  approved.type = 'checkbox';
  approved.name = 'assumptions_approved';
  approved.required = true;
  const approvalLabel = el('label', 'allocation-actions');
  approvalLabel.append(approved, document.createTextNode('외부 근거와 위 실행·회수 가정을 검토하고 이번 비교에 적용하는 데 동의합니다.'));
  card.addEventListener('input', event => {
    if (event.target !== approved) approved.checked = false;
  });
  const remove = el('button', 'btn light', '삭제');
  const suggest = el('button', 'btn light', '제목·요약 분석 및 영향 가정 만들기');
  remove.type = suggest.type = 'button';
  const hint = el('span', 'note allocation-hint');
  hint.setAttribute('role', 'status');
  select.addEventListener('change', () => {
    renderEvidencePreview(select);
    hint.textContent = '근거가 바뀌었습니다. 적용 상품과 기존 가정을 다시 확인하세요.';
  });
  suggest.addEventListener('click', () => suggestImpact(card));
  remove.addEventListener('click', () => {
    card.remove();
    $('allocationAdd').disabled = false;
    invalidateAllocation();
  });
  const header = el('div', 'allocation-case-header');
  header.append(allocationLabel('시나리오 이름', name), allocationLabel('외부 근거', select), remove);
  const actions = el('div', 'allocation-actions');
  actions.append(suggest, hint);
  card.append(el('legend', '', '외부 환경 가정'), header, el('div', 'allocation-source-preview'), actions,
    allocationLabel('이 근거를 실행·회수 가정에 적용한 이유', rationale),
    allocationTable(['상품', ...impactFields.map(field => field[1])],
      PRODUCTS.map(product => allocationProductRow(product, impactFields))), approvalLabel);
  container.append(card);
  $('allocationAdd').disabled = container.children.length >= 5;
  invalidateAllocation();
  select.focus();
}

function allocationLabel(title, input) {
  const label = el('label', 'allocation-label', title);
  label.append(input);
  return label;
}

function allocationTable(headings, rows) {
  const scroller = el('div', 'allocation-scroll');
  const table = el('table', 'result-table allocation-table');
  const thead = el('thead');
  const header = el('tr');
  for (const title of headings) {
    const th = el('th', '', title);
    th.scope = 'col';
    header.append(th);
  }
  thead.append(header);
  const body = el('tbody');
  body.append(...rows);
  table.append(thead, body);
  scroller.append(table);
  return scroller;
}

function allocationRows(rows) {
  return Object.fromEntries([...rows].map(row => [row.dataset.product, Object.fromEntries(
    [...row.querySelectorAll('input, select')].filter(field => field.value !== '').map(field => [field.name, field.value])
  )]));
}

function renderAllocation(data) {
  const results = $('allocationResults');
  const summary = [];
  const details = [];
  const status = el('p', 'allocation-choice');
  status.setAttribute('role', 'status');
  const buttons = [];
  for (const [scenarioIndex, scenario] of data.cases.entries()) {
    const panel = el('section', 'panel allocation-panel');
    panel.append(el('h3', '', scenario.name));
    if (scenario.source) {
      panel.append(el('h4', '', '외부 자료에서 확인한 내용'));
      panel.append(sourceSummary(scenario.source));
      if (scenario.source.excerpt) panel.append(el('p', 'note', scenario.source.excerpt));
      panel.append(el('p', 'note', scenario.source.publisher === '사용자 등록'
        ? '담당자가 등록한 제목과 내용입니다. 원문과 사실관계는 별도 확인이 필요합니다.'
        : '확인 범위는 위에 표시한 목록 또는 발행자 요약입니다. 상품 적용 여부와 영향 금액은 아래 가정에서 확인할 수 있습니다.'));
      panel.append(el('h4', '', '담당자가 승인한 실행·회수 가정'));
    }
    panel.append(el('p', '', scenario.rationale));
    const assumptions = scenario.assumptions.map(row => {
      const tr = el('tr');
      const values = [row.product, row.execution_floor, row.execution_ceiling, row.repayment_delta, row.repayment,
        row.execution_min, row.execution_max];
      values.forEach((value, index) => tr.append(el('td', '', index ? allocationAmount(value) : value)));
      return tr;
    });
    panel.append(allocationTable(['상품', '환경상 최소 실행', '환경상 실행 상한', '회수 변화', '가정 회수',
      '적용 실행 하한', '적용 실행 상한'], assumptions));
    if (scenario.external_effect) {
      const effect = scenario.external_effect;
      const signed = value => (value > 0 ? '+' : '') + allocationAmount(value);
      panel.append(el('h4', '', '외부 변화의 직접 영향 · 총순증 ' + signed(effect.total_delta) + '억 원'),
        el('p', 'note', '기존 실행계획에 승인한 외부 실행 하한·상한과 회수 변화만 적용했습니다. 기타조정은 고정하며, 내부 총량 상한에 따른 재배분 전 금액입니다.'),
        allocationTable(['상품', '실행 변화', '회수 변화', '순증 영향 (실행 변화 − 회수 변화)'],
          effect.rows.map(r => comparisonRow([r.product, ...[r.execution_delta, r.repayment_delta, r.net_delta].map(signed)]))));
    }
    if (scenario.issues.length) {
      const issues = el('ul', 'warning-box');
      scenario.issues.forEach(issue => issues.append(el('li', '', issue)));
      panel.append(issues);
      summary.push(comparisonRow([scenario.name, '가능한 배분안 없음', '—', '—', '—', '—', '—', '—']));
    }
    for (const [index, plan] of scenario.plans.entries()) {
      const result = plan.result;
      const label = index === 0 ? `추천 · ${plan.label}` : plan.label;
      const gaps = result.rows.filter(row => row.target_gap !== null && row.target_gap !== 0);
      const describeGap = row => {
        const limits = plan.decisions[row.product].limits;
        const limiting = index === 0 && limits.length ? ' · ' + limits.join(', ') : '';
        return `${row.product} ${allocationAmount(row.target_gap)}억${limiting}`;
      };
      const reason = index === 0
        ? '실행·순증 범위와 총순증 상한 안에서 우선순위가 높은 상품의 순증 목표부터 최대한 맞춘 안입니다.'
        : '상품 우선순위에 따라 기준 집계자료의 기존 실행액을 최대한 유지한 안입니다.';
      const article = el('article', 'allocation-plan');
      article.append(el('h4', '', label), el('p', '', reason),
        el('p', 'note', gaps.length
          ? '목표와 차이가 남는 상품 · ' + gaps.map(describeGap).join(' / ')
          : result.rows.some(row => row.target !== null) ? '입력한 순증 목표를 모두 충족합니다.' : '순증 목표 미입력 · 기준 실행액에 가깝게 계산했습니다.'));
      article.append(allocationTable(['상품', '실행', '회수', '순증', '목표', '목표 대비'],
        result.rows.map(row => comparisonRow([
          row.product, ...[row.execution, row.repayment, row.net, row.target, row.target_gap].map(allocationAmount),
        ]))));
      if (scenario.source) {
        article.append(el('h4', '', '기준안 대비 상품별 배분 변화'));
        if (plan.baseline_label) {
          article.append(el('p', 'note', `비교 기준 · 기준 시나리오의 ${plan.baseline_label}`),
            allocationTable(['상품', '실행 변화', '회수 변화', '순증 변화'], plan.changes.map(change =>
              comparisonRow([change.product, ...['execution', 'repayment', 'net'].map(field =>
                (change[field] > 0 ? '+' : '') + allocationAmount(change[field]))]))));
        } else {
          article.append(el('p', 'note', '기준 시나리오의 필수 제약이 충돌해 비교할 기준안이 없습니다.'));
        }
      }
      article.append(el('h4', '', index === 0 ? '추천을 결정한 제약' : '기존 실행계획에 적용한 제약'));
      article.append(allocationTable(['상품', '제약 적용 전 실행 요청', '배분 실행', '실행액을 조정한 제약'],
        result.rows.map(row => {
          const decision = plan.decisions[row.product];
          return comparisonRow([row.product, allocationAmount(decision.desired_execution),
            allocationAmount(row.execution), decision.limits.join(' · ') || '요청 금액 반영']);
        })));
      const button = el('button', 'btn light', '이 배분안 선택');
      buttons.push(button);
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => {
        clearTimeout(scenarioTimer);
        ++app.computeSeq;
        app.scenario = {cap: data.cap, overrides: plan.overrides};
        app.allocationSelection = {
          label: `${scenario.name} / ${plan.label}`,
          reference: {comparison_id: data.comparison_id, scenario_index: scenarioIndex, plan_index: index},
        };
        app.scenarioResult = result;
        renderScenarioFields();
        all('#scenarioFields input').forEach(input => {
          input.value = plan.overrides[`${input.dataset.product}.${input.dataset.field}`];
        });
        setPreset('manual');
        renderScenario();
        renderReport();
        buttons.forEach(item => item.setAttribute('aria-pressed', String(item === button)));
        status.textContent = `선택한 배분안 · ${scenario.name} / ${plan.label}. 시나리오 분석에 금액을 적용했습니다.`;
        $('allocationStatus').textContent = status.textContent;
      });
      const totals = el('div', 'allocation-actions');
      totals.append(el('strong', '', `총순증 ${allocationAmount(result.total_net)}억 · 상한 여유 ${allocationAmount(result.assumed_remaining)}억`), button);
      article.append(totals);
      panel.append(article);
      summary.push(comparisonRow([scenario.name, label, ...result.rows.map(row => allocationAmount(row.net)),
        allocationAmount(result.total_net), allocationAmount(result.assumed_remaining),
        gaps.length ? `${gaps.length}개 상품` : result.rows.some(row => row.target !== null) ? '없음' : '목표 미입력']));
    }
    details.push(panel);
  }
  const overview = el('section', 'panel allocation-panel');
  overview.append(el('h3', '', '시나리오별 배분 비교'),
    el('p', 'note', `${data.month} · ${data.data_origin} · 억 원 · 내부 총순증 상한 ${allocationAmount(data.cap)}억`),
    allocationTable(['시나리오', '배분안', ...PRODUCTS, '전체 순증', '상한 여유', '목표 차이'], summary), status);
  const stressPanels = (data.stress || []).map(group => {
    const panel = el('section', 'panel allocation-panel');
    const detail = el('details', 'stress-detail');
    detail.append(el('summary', '', '전체 환경의 수치와 계획별 실행액 보기'),
      el('p', 'note', '단위 억 원. 기존 계획은 집계자료의 실행액입니다. 나머지 두 계획은 승인한 환경에서 편성합니다. 여유안은 편성 시 상한보다 5억 원을 남깁니다.'),
      allocationTable(['고정 계획 실행액', ...PRODUCTS], Object.entries(group.plans).map(([label, amounts]) =>
        comparisonRow([label, ...PRODUCTS.map(n => allocationAmount(amounts[n] ?? null))]))),
      el('p', 'note', '추가 둔화는 승인 환경에서 보험계약대출 회수가 5억 원 더 줄어드는 가상 민감도 조건입니다. 고정 실행액으로 초과·미달을 먼저 계산합니다. 조정 시 상품별 한도를 맞춘 뒤 총량 초과분만큼 후순위부터 줄이며 신용대출을 우선 보호합니다.'),
      allocationTable(['환경', '고정 계획', '유지 시 총순증', '총량 상한 초과', '신용 목표 미달', '필수 제약 충족을 위한 실행 조정', '조정 후 총순증'],
        group.rows.map(r => {
          const changes = Object.entries(r.changes || {}).filter(([, v]) => v)
            .map(([n,v]) => n + ' ' + (v > 0 ? '+' : '') + allocationAmount(v));
          return comparisonRow([r.scenario, r.plan, ...[r.total, r.excess, r.shortfall].map(v => allocationAmount(v ?? null)),
            r.issues.length ? r.issues.join(' · ') : changes.join(' / ') || '조정 없음', allocationAmount(r.adjusted_net ?? null)]);
        })));
    panel.classList.add('stress-panel');
    panel.append(el('h3', '', '환경별 계획 비교'), el('p', 'stress-context',
      group.anchor + ' 기준 편성 · 내부 총순증 상한 ' + allocationAmount(data.cap) + '억 원'));
    const controls = el('div', 'stress-switch');
    controls.setAttribute('role', 'group');
    controls.setAttribute('aria-label', '비교 환경 선택');
    const grid = el('div', 'stress-cards');
    grid.setAttribute('aria-live', 'polite');
    const size = Object.keys(group.plans).length;
    const switches = [];
    function showEnvironment(offset) {
      switches.forEach((button, i) => button.setAttribute('aria-pressed', String(i * size === offset)));
      grid.replaceChildren(...group.rows.slice(offset, offset + size).map(stressCard));
    }
    for (let offset = 0; offset < group.rows.length; offset += size) {
      const button = el('button', '', group.rows[offset].scenario);
      button.type = 'button';
      button.addEventListener('click', () => showEnvironment(offset));
      switches.push(button);
      controls.append(button);
    }
    panel.append(controls, grid, detail);
    showEnvironment(group.rows.length - size);
    return panel;
  });
  if (data.policy_note) overview.prepend(el('p','allocation-choice','정책 검토 · '+data.policy_note));
  results.replaceChildren(...stressPanels, overview, ...details);
}

function stressCard(row) {
  const adjustments = Object.entries(row.changes || {}).filter(([, value]) => value);
  const critical = row.issues.length || row.excess > 0;
  const warning = row.shortfall > 0 || adjustments.length;
  const tone = critical ? 'danger' : warning ? 'warning' : 'clear';
  const status = row.issues.length ? '제약 충돌' : row.excess > 0 ? '상한 초과' :
    adjustments.length ? '실행 조정 필요' : row.shortfall > 0 ? '신용 목표 미달' : '제약 충족';
  const card = el('article', 'stress-card ' + tone);
  card.append(el('h4', '', row.plan), el('span', 'stress-status', status),
    el('p', 'stress-label', '계획 유지 시 총순증'),
    el('strong', 'stress-total', row.total == null ? '—' : allocationAmount(row.total) + '억 원'));
  const metrics = el('dl', 'stress-metrics');
  for (const [label, value] of [['상한 초과액', row.excess], ['신용 목표 미달액', row.shortfall]]) {
    metrics.append(el('dt', '', label), el('dd', value > 0 ? 'attention' : '',
      value == null ? '—' : allocationAmount(value) + '억'));
  }
  const change = el('div', 'stress-adjust');
  change.append(el('strong', '', '필수 제약을 위한 실행 조정'));
  for (const [name, value] of adjustments) {
    change.append(el('div', '', name + ' ' + (value > 0 ? '+' : '−') + allocationAmount(Math.abs(value)) + '억'));
  }
  if (!adjustments.length) change.append(el('div', '', row.issues.join(' · ') || '조정 없음'));
  if (adjustments.length) change.append(el('small', '', '조정 후 총순증 ' + allocationAmount(row.adjusted_net) + '억'));
  card.append(metrics, change);
  return card;
}

function comparisonRow(values) {
  const row = el('tr');
  const [first, ...remaining] = values;
  const heading = el('th', '', first);
  heading.scope = 'row';
  row.append(heading, ...remaining.map(value => el('td', '', value)));
  return row;
}

allocationForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!app.baseline) return;
  const revision = ++allocationRevision;
  $('allocationResults').replaceChildren();
  $('allocationSubmit').disabled = true;
  $('allocationStatus').textContent = '전략 제약을 검토하고 배분안을 계산하는 중입니다.';
  try {
    const result = await api('/api/allocation/compare', {
      method: 'POST',
      body: {
        cap: allocationForm.elements.cap.value,
        policy_reviews: all('#releaseActions fieldset').filter(c=>c.querySelector('select').value).map(c=>({
          policy_id:c.dataset.id,decision:c.querySelector('select').value,reason:c.querySelector('textarea').value.trim(),
          monthly_ceiling:c.querySelector('input').disabled ? null : c.querySelector('input').value
        })),
        policy_review: $('policyDecision').value ? {
          policy_id: $('policyTable').dataset.policy, decision: $('policyDecision').value,
          reason: $('policyReason').value.trim(), monthly_ceiling: $('policyLimit').disabled ? null : $('policyLimit').value
        } : null,
        products: allocationRows($('allocationRules').rows),
        scenarios: all('.allocation-case').map(card => ({
          name: card.querySelector('input').value.trim(),
          source_id: card.querySelector('select').value,
          rationale: card.querySelector('textarea').value.trim(),
          assumptions_approved: card.querySelector('[name=assumptions_approved]').checked,
          impacts: allocationRows(card.querySelectorAll('tbody tr')),
        })),
      },
    });
    if (revision !== allocationRevision) return;
    renderAllocation(result);
    $('allocationStatus').textContent = result.cases.some(scenario => scenario.plans.length)
      ? '비교 결과에서 적용할 배분안을 선택하세요.'
      : '제약을 모두 충족하는 배분안이 없습니다. 결과에서 충돌 사유를 확인하세요.';
  } catch (error) {
    if (revision === allocationRevision) $('allocationStatus').textContent = error.message;
  } finally {
    $('allocationSubmit').disabled = false;
  }
});
allocationForm.addEventListener('input', event => {
  if (event.target.name === 'cap' || event.target.closest('#allocationRules')) strategyEdited = true;
  invalidateAllocation();
});
$('allocationSubmit').disabled = true;
$('allocationAdd').addEventListener('click', addAllocationCase);
$('allocationRefresh').addEventListener('click', refreshAllocationEvidence);
document.addEventListener('allocation:open', refreshAllocationEvidence);
document.addEventListener('portfolio:loaded', loadAllocationBaseline);

$('allocationFetch').addEventListener('click', async () => {
  const button = $('allocationFetch');
  const status = $('allocationEvidenceStatus');
  if ($('watchEnabled').value !== 'on') {
    status.textContent = '자료 관리에서 외부 탐색을 켠 후 조회하세요.';
    return;
  }
  if (watching) {
    status.textContent = '외부 자료 조회가 진행 중입니다. 완료 후 근거 목록을 다시 불러오세요.';
    return;
  }
  button.disabled = true;
  status.textContent = '공개 자료를 조회하고 있습니다.';
  try {
    await refreshWatch(true);
    await refreshAllocationEvidence();
    status.textContent = $('watchState').textContent + ' · ' + status.textContent;
  } finally {
    button.disabled = false;
  }
});

async function openIndicatorDraft(draft) {
  go('allocation');
  await refreshAllocationEvidence();
  if (!allocationEvidence[draft.source_id]) throw new Error('지표 근거를 불러올 수 없습니다. 다시 조회하세요.');
  const cards = all('.allocation-case');
  let card = cards.find(item => item.dataset.indicator === draft.source_id);
  if (card) { card.scrollIntoView({block:'center'}); return; }
  if (cards.length >= 5) throw new Error('시나리오는 최대 5개입니다. 기존 시나리오를 정리하세요.');
  addAllocationCase();
  card = $('allocationCases').lastElementChild;
  card.dataset.indicator = draft.source_id;
  card.querySelector('input').value = draft.name;
  const select = card.querySelector('select');
  select.value = draft.source_id;
  renderEvidencePreview(select);
  card.querySelector('textarea').value = draft.rationale;
  for (const row of card.querySelectorAll('tbody tr')) {
    for (const [field,value] of Object.entries(draft.impacts[row.dataset.product])) {
      row.querySelector('[name=' + field + ']').value = value;
    }
  }
  card.scrollIntoView({block:'center'});
}

$('policyTable').addEventListener('toggle', async () => {
  if (!$('policyTable').open || $('policyTable').dataset.policy) return;
  try {
    const p = await api('/api/allocation/policy-example');
    const link=el('a','download-link',p.publisher+' · '+p.title);
    link.href=p.url; link.target='_blank'; link.rel='noopener noreferrer';
    $('policyFacts').replaceChildren(link, allocationTable(['검토 항목','발표 당시 내용'],[
      ['근거 문장',p.quote], ['적용 대상',p.target], ['발표일 / 시행일',p.published_at+' / '+p.effective],
      ['예외',p.exceptions]].map(comparisonRow)));
    $('policyTable').dataset.policy=p.id;
    $('policyDecision').disabled=false;
  } catch(error) { $('policyFacts').textContent=error.message; }
});
$('policyDecision').addEventListener('change', () => {
  const decision=$('policyDecision').value;
  $('policyReason').disabled=!decision; $('policyReason').required=!!decision;
  $('policyLimit').disabled=!decision || decision==='해당 없음';
  $('policyLimit').required=!$('policyLimit').disabled;
  if (decision) $('policyTable').open=true;
  invalidateAllocation();
});

$('releaseFetch').onclick=async () => {
  const button=$('releaseFetch'), list=$('releaseList');
  button.disabled=true; list.replaceChildren(); $('releaseExtract').disabled=true;
  try {
    const query=new URLSearchParams({agency:$('releaseAgency').value,term:$('releaseTerm').value});
    const rows=await api('/api/allocation/policy-releases?'+query,{headers:{'X-External-Request':'1'}});
    rows.forEach(r=>list.add(new Option((r.published_at||'공표일 미확인')+' · '+r.title,r.url)));
    $('releaseStatus').textContent='공식 발표 '+rows.length+'건';
    $('releaseExtract').disabled=!rows.length;
  } catch(e) { $('releaseStatus').textContent=e.message; }
  finally { button.disabled=false; }
};
$('releaseExtract').onclick=async () => {
  const button=$('releaseExtract'); button.disabled=true;
  try {
    const actions=await api('/api/allocation/policy-actions',{method:'POST',headers:{'X-External-Request':'1'},body:{url:$('releaseList').value}});
    for (const p of actions) {
      if (all('#releaseActions fieldset').some(c=>c.dataset.id===p.id)) continue;
      const card=el('fieldset','allocation-case-review'); card.dataset.id=p.id;
      const link=el('a','download-link',p.publisher+' · 발표 '+p.published_at+' · 원문');link.href=p.url;link.target='_blank';link.rel='noopener noreferrer';
      const decision=el('select'),reason=el('textarea'),limit=el('input');
      ['','이번 달 적용','향후 시나리오','해당 없음'].forEach(v=>decision.add(new Option(v||'검토하지 않음',v)));
      if (!p.product) {decision.options[1].disabled=true;decision.options[2].disabled=true;}
      if (!/^\d{4}-\d{2}-\d{2}$/.test(p.effective)) decision.options[1].disabled=true;
      limit.type='number';limit.min=0;limit.max=1e9;limit.step='0.00001'; reason.maxLength=500;
      reason.disabled=limit.disabled=true;
      decision.onchange=()=>{reason.required=!!decision.value;reason.disabled=!decision.value;
        limit.required=!!decision.value && decision.value!=='해당 없음';limit.disabled=!limit.required; invalidateAllocation();};
      card.append(el('legend','',p.title),link,allocationTable(['검토 항목','공식 HTML 본문 발췌'],[
        ['근거 문장',p.quote],['적용 대상·조건',p.target],['시행일',p.effective],['날짜 근거',p.date_evidence||'미확인'],
        ['예외·경과조치',p.exceptions]].map(comparisonRow)),allocationLabel('검토 결정',decision),
        allocationLabel('선택 이유',reason),allocationLabel((p.product||'상품 미확인')+' 월간 실행 상한 (억 원)',limit));
      $('releaseActions').append(card);
    }
    $('releaseStatus').textContent=actions.length ? actions.length+'개 조치 후보 · 원문과 첨부를 대조해 검토하세요.' : 'HTML 본문에서 조치를 확인하지 못했습니다. 원문·첨부 확인이 필요합니다.';
  } catch(e) { $('releaseStatus').textContent=e.message; }
  finally {button.disabled=false;}
};

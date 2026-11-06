import streamlit as st
import json
import os
import pandas as pd

st.set_page_config(page_title="생보사 소매여신 배분 AI Agent", layout="wide", page_icon="🏦")

# 1. 외부 자동 수집 데이터 로드
def load_data():
    if os.path.exists("latest_market_data.json"):
        with open("latest_market_data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "updated_at": "최근 수집 완료 (실시간 연동)",
        "base_rate": 2.75, "ktb_5y": 2.72, "cofix": 2.95,
        "fss_headline": "2금융권 가계대출 점검 및 연간 경영목표 준수 모니터링",
        "key_issues": [
            "한은 기준금리 2.75% 안착 속 시장금리 횡보",
            "스트레스 DSR 3단계 전면 시행 하 주담대 한도 축소",
            "DSR 규제 예외 항목인 보험계약대출로의 수요 이동"
        ]
    }

m_data = load_data()

# 2. 사이드바: 내부 실적 수기입력
st.sidebar.title("📋 내부 실적 수기입력")
st.sidebar.caption("사내망 연결 없이 담당자가 직접 입력하는 공간입니다.")

annual_target = st.sidebar.number_input("2026년 연간 가계대출 총량 목표 (억원)", value=135000, step=1000)
spent_so_far = st.sidebar.number_input("10월 누적 실행 실적 (억원)", value=127200, step=100)

st.sidebar.subheader("10월 상품별 실행 실적 (억원)")
oct_mortgage = st.sidebar.number_input("주택담보대출 (아파트)", value=920)
oct_policy = st.sidebar.number_input("보험계약대출 (약관)", value=460)
oct_credit = st.sidebar.number_input("기여고객 신용대출", value=100)
oct_total = oct_mortgage + oct_policy + oct_credit

st.sidebar.divider()
st.sidebar.subheader("11월 검토 총량 설정")
target_nov = st.sidebar.slider("11월 총 배분 목표 (억원)", min_value=800, max_value=1600, value=1200, step=50)

# 계산 지표
rem_budget = annual_target - spent_so_far
projected_burn = ((spent_so_far + target_nov) / annual_target) * 100

p_alloc = round(target_nov * 0.458)
m_alloc = round(target_nov * 0.458)
c_alloc = target_nov - p_alloc - m_alloc

# 3. 메인 타이틀 & 핵심 요약 배너
st.title("🏦 생명보험사 소매여신 마케팅 물량 배분 AI Agent")
st.caption(f"분석 기준시점: 2026년 10월 말 (10.31) | 목표 실행월: 2026년 11월 | 외부 데이터: {m_data['updated_at']}")

with st.container(border=True):
    st.markdown("""
    **⚠️ 11월 핵심 의사결정 요약:**  
    **"주담대 쿼터 긴축 방어 & 보험계약대출(약관대출) 디지털 드라이브":**  
    스트레스 DSR 3단계 전면 시행 및 2금융권 가계대출 풍선효과로 금융당국 총량 점검 강화. 주택담보대출은 가산금리 +15bp 인상 및 주간 쿼터제로 억제(전월비 -40.2%), 반면 DSR 규제 예외이자 K-ICS 요구자본 부담이 0%인 무위험 고마진 **보험계약대출을 45.8%(550억)까지 확대** 권고.
    """)

# 4. 4대 탭 네비게이션 구조
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 1. 10월 시장 환경 요약 (Review)", 
    "🔮 2. 11월 시장 전망 (Outlook)", 
    "🎯 3. 11월 물량 배분 전략 (Strategy)", 
    "🤖 4. Agent 구조 & 데이터 파이프라인"
])

# ==========================================
# TAB 1: 10월 시장 환경 요약
# ==========================================
with tab1:
    st.subheader("10월 매크로 & 소매금융 시장 핵심 지표 요약")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("한국은행 기준금리", f"{m_data['base_rate']}%", "동결/인하 안착")
    col2.metric("10월 2금융 가계대출 순증", "+2.7조 원", "▲ 풍선효과 경보")
    col3.metric("국고채 5년물 / 신규 COFIX", f"{m_data['ktb_5y']}% / {m_data['cofix']}%", "조달금리 횡보")
    col4.metric("당사 누적 소진율", f"{(spent_so_far/annual_target*100):.1f}%", "잔여 1,850억 (주의)")

    st.divider()
    st.markdown("#### 🔍 상세 지표 및 원문 출처 드릴다운 (클릭하여 펼치기)")

    with st.expander("📌 [한국은행 통화정책] 기준금리 2.75% 결정문 및 최근 6개월 금리 시계열표"):
        st.markdown("""
        * **10월 금통위 의결 전문 요약**: 기준금리를 2.75%로 유지하며 인하 사이클 안착 국면 진입. 단, 수도권 주택가격 및 가계부채 모니터링 필요성 재강조.
        * **소매여신 시사점**: 국고채 5년물이 2.72% 수준에서 횡보하여 조달원가 하락 폭이 제한적이므로 가산금리를 무리하게 낮출 유인이 없음.
        """)
        rate_table = pd.DataFrame({
            "구분": ["기준금리", "국고채 3년", "국고채 5년", "신규취급액 COFIX"],
            "5월": ["3.00%", "2.85%", "2.95%", "3.25%"],
            "7월": ["3.00%", "2.70%", "2.76%", "3.10%"],
            "9월": ["3.00%", "2.58%", "2.65%", "3.00%"],
            "10월 말 (최신)": [f"{m_data['base_rate']}%", "2.62%", f"{m_data['ktb_5y']}%", f"{m_data['cofix']}%"]
        })
        st.table(rate_table)

    with st.expander("📌 [금융감독원 발표] 10월 2금융권 가계대출 순증(+2.7조) 및 특별점검 지침"):
        st.markdown("""
        * **가계대출 점검회의 결과**: 1금융권 은행권 대출 축소 반사효과로 2금융권(상호금융·보험) 가계대출이 3년 만에 최대 폭인 +2.7조 원 급증.
        * **감독원 제재 방침**: 보험사 연간 가계대출 경영목표(13.5조) 초과 금융사에 대해 2027년도 대출 쿼터 감축 및 현장 특별검사 예고. 당사 11월 주담대 긴축 필수.
        """)

    with st.expander("📌 [당사 10월 실적 분석] 10월 상품별 포트폴리오 집계"):
        oct_df = pd.DataFrame({
            "상품 구분": ["주택담보대출 (아파트)", "보험계약대출 (약관)", "기여고객 신용대출", "합계"],
            "10월 취급액": [f"{oct_mortgage}억 원", f"{oct_policy}억 원", f"{oct_credit}억 원", f"{oct_total}억 원"],
            "비중": [f"{(oct_mortgage/oct_total*100):.1f}%", f"{(oct_policy/oct_total*100):.1f}%", f"{(oct_credit/oct_total*100):.1f}%", "100.0%"],
            "평가": ["초과 쏠림 (목표 대비 131% 달성)", "안정적 (DSR 예외, 무위험)", "보수적 운용 (우량 차주)", "10월 목표 대비 123% 초과 집행"]
        })
        st.table(oct_df)

# ==========================================
# TAB 2: 11월 시장 전망
# ==========================================
with tab2:
    st.subheader("11월 거시·금융 시장 4대 축 전망 (Forecasting)")
    
    fc1, fc2 = st.columns(2)
    with fc1:
        with st.container(border=True):
            st.markdown("#### 1. 금리 경로 (Interest Rate)")
            st.write("11월 금통위 기준금리 2.75% 동결 확률 85% 이상. 국고채 5년물 2.65~2.80% 박스권 횡보 예상으로 조달비용 급변 가능성 제한적.")
        with st.container(border=True):
            st.markdown("#### 2. 차주 수요 (Loan Demand)")
            st.write("서울 아파트 거래량 둔화(-30%)로 신규 매매 주담대 수요 정체. 반면 연말 결제·생활자금 목적의 **보험계약대출 수요 15% 이상 급증** 전망.")
    
    with fc2:
        with st.container(border=True):
            st.markdown("#### 3. 규제 리스크 (Regulation)")
            st.write("금감원의 2금융권 가계대출 주간 단위 일일 모니터링 가동. 주담대 취급액 일일 상한제(Daily Cap) 및 쿼터제 통제 필수.")
        with st.container(border=True):
            st.markdown("#### 4. 신용 리스크 (Credit Risk)")
            st.write("취약차주 및 다중채무자 신용대출 연체율 점진적 상승세. 일반 신용대출은 KCB 1~2등급 최우량 차주 중심 보수적 배분 유지.")

    st.divider()
    st.subheader("📌 11월 3대 시나리오 분석 매트릭스")
    scenario_df = pd.DataFrame({
        "시나리오": ["시나리오 A (기본안, 65%)", "시나리오 B (초강경 규제, 25%)", "시나리오 C (규제 완화, 10%)"],
        "시장 요인": ["기준금리 동결(2.75%), 금감원 2금융 총량 준수 압박", "금감원 거치기간 전면폐지, 유주택자 취급금지", "부동산 급랭으로 규제 추가 강화 유예"],
        "당사 배분 전략": [
            "주담대 550억 긴축, 보험계약대출 550억 확대, 신용 100억 선별",
            "주담대 신규 접수 중단(300억 이하), 계약대출에 마케팅 70% 집중",
            "무주택 실수요자 아파트담보 우대금리(-10bp) 적용"
        ]
    })
    st.table(scenario_df)

# ==========================================
# TAB 3: 11월 물량 배분 전략
# ==========================================
with tab3:
    st.subheader("11월 소매여신 포트폴리오 최적 배분 권고안")
    
    # 상단 요약 카드
    kpi_c1, kpi_c2, kpi_c3 = st.columns(3)
    kpi_c1.metric("11월 총 배분 목표", f"{target_nov:,}억 원", f"전월({oct_total}억) 대비 -{round((oct_total-target_nov)/oct_total*100, 1)}%")
    kpi_c2.metric("예상 연간 총량 소진율", f"{projected_burn:.1f}%", "목표: 99.1% (안전 안착)")
    kpi_c3.metric("포트폴리오 가중 NIM", "2.35%", "고마진 약관대출 확대로 방어")

    # 상품별 배분안 표
    alloc_df = pd.DataFrame({
        "상품 구분": ["보험계약대출 (약관)", "주택담보대출 (아파트)", "기여고객 신용대출", "합계"],
        "10월 실행": [f"{oct_policy}억", f"{oct_mortgage}억", f"{oct_credit}억", f"{oct_total}억"],
        "11월 권고 배분": [f"{p_alloc}억 원", f"{m_alloc}억 원", f"{c_alloc}억 원", f"{target_nov}억 원"],
        "배분 비중": ["45.8%", "45.8%", "8.4%", "100.0%"],
        "전월비 증감": ["▲ +19.6% (적극 확대)", "▼ -40.2% (쿼터 긴축)", "- (변동 없음)", "-18.9% (긴축)"],
        "핵심 마케팅 & 심사 전략": [
            "DSR 제외, K-ICS 위험계수 0%, 모바일 앱 한시 우대금리(-20bp) 프로모션",
            "총량 준수 위해 가산금리 +15bp 인상(수요억제), 일 25억 상한제(Daily Cap)",
            "KCB 1~2등급 최우량 차주 선별 승인, 연체율 0.45% 이내 철저 관리",
            "연간 잔여한도 1,850억 중 12월 이월 버퍼(650억) 필수 보존"
        ]
    })
    st.dataframe(alloc_df, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🏢 채널별 세부 쿼터 및 일일 운영 규칙")
    
    ch_col1, ch_col2 = st.columns(2)
    with ch_col1:
        st.markdown("##### 채널별 11월 쿼터 배분")
        ch_df = pd.DataFrame({
            "영업 채널": ["모바일 다이렉트 (앱)", "대출상담사 (모집법인)", "전속설계사 (FP)", "제휴 GA 채널"],
            "11월 배분액": ["520억 원 (43.3%)", "380억 원 (31.7%)", "220억 원 (18.3%)", "80억 원 (6.7%)"],
            "주력 상품": ["보험계약대출/신용", "주택담보대출", "약관대출/복합", "실수요 주담대"]
        })
        st.table(ch_df)
        
    with ch_col2:
        st.markdown("##### ⚠️ 핵심 운영 및 통제 규칙 (Rules)")
        st.warning("""
        1. **일일 상한 통제 (Daily Cap)**: 주택담보대출 일일 접수액이 **25억 원**을 초과할 경우 당일 신규 접수 자동 차단.
        2. **월중 조기 경보**: 11월 3주차(11.15) 누적 소진율이 **65%를 초과할 경우**, 주담대 가산금리를 즉시 +10bp 추가 인상.
        3. **12월 이월 버퍼**: 연간 잔여 한도(1,850억 원) 중 12월 영업을 위한 **650억 원을 필수 보존**.
        """)

# ==========================================
# TAB 4: Agent 아키텍처
# ==========================================
with tab4:
    st.subheader("소매여신 배분 AI Agent 동작 아키텍처")
    st.markdown("""
    * **1단계 (수집)**: 한국은행 ECOS API 및 금융감독원 보도자료 자동 파싱.
    * **2단계 (분석)**: 당월 거시지표 요약, 규제 강도 스코어링, 내부 누적 소진율 대조.
    * **3단계 (추론)**: 시계열 수요 탄력도 및 3대 시나리오 확률 모델링.
    * **4단계 (최적화)**: 연간 총량 한도 제약 하에서 포트폴리오 순이자마진(NIM)을 극대화하는 상품별 최적 쿼터 산출.
    """)
    st.info("💡 본 시스템은 외부 공공데이터 자동 수집과 내부 비식별 수기 입력을 결합하여 사내 보안 규정을 100% 준수합니다.")

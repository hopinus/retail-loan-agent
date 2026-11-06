import streamlit as st
import json
import os
import pandas as pd

st.set_page_config(page_title="소매여신 배분 Agent", layout="wide")

def load_data():
    if os.path.exists("latest_market_data.json"):
        with open("latest_market_data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "updated_at": "최초 동기화 전",
        "base_rate": 2.75, "ktb_5y": 2.72, "cofix": 2.95,
        "fss_headline": "가계대출 관리 강화 기조",
        "key_issues": ["기준금리 2.75% 유지", "스트레스 DSR 3단계 시행"]
    }

m_data = load_data()

st.title("🏦 생보사 소매여신 배분 AI Agent (외부 참조용)")
st.caption(f"외부 데이터 동기화: {m_data['updated_at']}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("한국은행 기준금리", f"{m_data['base_rate']}%")
c2.metric("국고채 5년물", f"{m_data['ktb_5y']}%")
c3.metric("신규취급 COFIX", f"{m_data['cofix']}%")
c4.metric("당국 모니터링", "주의", m_data['fss_headline'][:15])

st.sidebar.header("📋 내부 실적 수기입력")
annual_target = st.sidebar.number_input("연간 가계대출 목표 (억원)", value=135000, step=1000)
spent_so_far = st.sidebar.number_input("10월 누적 실행 실적 (억원)", value=127200, step=100)

oct_mortgage = st.sidebar.number_input("10월 주담대 취급액 (억)", value=920)
oct_policy = st.sidebar.number_input("10월 약관대출 취급액 (억)", value=460)
oct_credit = st.sidebar.number_input("10월 신용대출 취급액 (억)", value=100)

target_nov = st.sidebar.slider("11월 검토 총 배분액 (억원)", 800, 1600, 1200, step=50)

p_alloc = round(target_nov * 0.458)
m_alloc = round(target_nov * 0.458)
c_alloc = target_nov - p_alloc - m_alloc

st.divider()
st.subheader("🎯 11월 상품별 권고 배분안")

df = pd.DataFrame({
    "상품 구분": ["보험계약대출 (약관)", "주택담보대출 (아파트)", "기여고객 신용대출"],
    "10월 취급액": [f"{oct_policy}억", f"{oct_mortgage}억", f"{oct_credit}억"],
    "11월 권고 쿼터": [f"{p_alloc}억 (45.8%)", f"{m_alloc}억 (45.8%)", f"{c_alloc}억 (8.4%)"],
    "전략 방향": ["적극 확대 (DSR 예외, K-ICS 0%, NIM 2.35%)", "쿼터 긴축 (가산금리 +15bp, 일 25억 상한)", "건전성 유지 (1~2등급 최우량)"]
})
st.dataframe(df, use_container_width=True, hide_index=True)

burn_rate = ((spent_so_far + target_nov) / annual_target) * 100
st.metric("11월 실행 시 연간 소진율", f"{burn_rate:.1f}%")
if burn_rate > 99.5:
    st.error("⚠️ 연간 총량 초과 위험! 주담대 쿼터를 축소하세요.")
else:
    st.success("✓ 금감원 연간 경영목표 준수 범위 안착")

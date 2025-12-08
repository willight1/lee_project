"""
관세 데이터 대시보드
Streamlit 기반 tariff_data.db 시각화 애플리케이션 + AI 챗봇
"""

import streamlit as st
import sqlite3
import pandas as pd
import os
from dotenv import load_dotenv
from openai import OpenAI

# 환경 변수 로드
load_dotenv()

# 페이지 설정
st.set_page_config(
    page_title="관세 데이터 대시보드",
    page_icon="📊",
    layout="wide"
)

# CSS 스타일
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E3A5F;
        text-align: center;
        padding: 1rem 0;
        border-bottom: 3px solid #4A90D9;
        margin-bottom: 2rem;
    }
    .filter-section {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 10px;
        margin-bottom: 2rem;
    }
    .stSelectbox label, .stTextInput label {
        color: white !important;
        font-weight: 600;
    }
    .data-card {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 1rem;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #4A90D9;
    }
    .detail-header {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1E3A5F;
        border-left: 4px solid #4A90D9;
        padding-left: 0.5rem;
        margin-bottom: 1rem;
    }
    /* 챗봇 스타일 */
    .chat-message {
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 0.5rem;
    }
    .user-message {
        background-color: #e3f2fd;
        border-left: 4px solid #2196f3;
    }
    .assistant-message {
        background-color: #f5f5f5;
        border-left: 4px solid #4caf50;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_connection():
    """데이터베이스 연결"""
    return sqlite3.connect("tariff_data.db", check_same_thread=False)


@st.cache_resource
def get_openai_client():
    """OpenAI 클라이언트 초기화"""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


@st.cache_data
def get_unique_values(column: str) -> list:
    """특정 컬럼의 고유값 목록 조회"""
    conn = get_connection()
    query = f"SELECT DISTINCT {column} FROM tariff_items WHERE {column} IS NOT NULL ORDER BY {column}"
    df = pd.read_sql(query, conn)
    return ["All"] + df[column].tolist()


@st.cache_data
def get_db_summary() -> str:
    """데이터베이스 요약 정보"""
    conn = get_connection()
    
    # 총 항목 수
    total = pd.read_sql("SELECT COUNT(*) as cnt FROM tariff_items", conn)['cnt'].iloc[0]
    
    # 발급국가 목록
    issuing = pd.read_sql(
        "SELECT issuing_country, COUNT(*) as cnt FROM tariff_items GROUP BY issuing_country ORDER BY cnt DESC", 
        conn
    )
    
    # 대상국가 목록
    countries = pd.read_sql(
        "SELECT country, COUNT(*) as cnt FROM tariff_items WHERE country IS NOT NULL GROUP BY country ORDER BY cnt DESC LIMIT 10",
        conn
    )
    
    summary = f"""
데이터베이스 요약:
- 총 관세 항목: {total:,}건
- 발급국가: {', '.join([f"{row['issuing_country']}({row['cnt']}건)" for _, row in issuing.iterrows()])}
- 주요 대상국가 (상위 10개): {', '.join([f"{row['country']}({row['cnt']}건)" for _, row in countries.iterrows()])}

테이블 구조 (tariff_items):
- issuing_country: 관세 발급국 (USA, Malaysia 등)
- country: 대상국 (수출국)
- hs_code: HS 코드
- tariff_type: 관세 유형 (Antidumping, Countervailing)
- tariff_rate: 관세율 (%)
- company: 회사명
- case_number: 케이스 번호
- product_description: 제품 설명
- effective_date_from/to: 시행일
- basis_law: 법적 근거
"""
    return summary


def execute_sql_query(query: str) -> pd.DataFrame:
    """SQL 쿼리 실행 (SELECT만 허용)"""
    conn = get_connection()
    query_lower = query.strip().lower()
    
    # SELECT 쿼리만 허용
    if not query_lower.startswith("select"):
        return pd.DataFrame({"error": ["SELECT 쿼리만 허용됩니다."]})
    
    # 위험한 키워드 차단
    dangerous = ["drop", "delete", "update", "insert", "alter", "create", "truncate"]
    for word in dangerous:
        if word in query_lower:
            return pd.DataFrame({"error": [f"'{word}' 키워드는 사용할 수 없습니다."]})
    
    try:
        return pd.read_sql(query, conn)
    except Exception as e:
        return pd.DataFrame({"error": [str(e)]})


def chat_with_ai(user_message: str, chat_history: list) -> str:
    """AI 챗봇 응답 생성"""
    client = get_openai_client()
    if not client:
        return "⚠️ OpenAI API 키가 설정되지 않았습니다. `.env` 파일에 `OPENAI_API_KEY`를 설정하세요."
    
    db_summary = get_db_summary()
    
    system_prompt = f"""당신은 관세 데이터 분석 전문가입니다. 사용자의 질문에 친절하게 답변해주세요.

{db_summary}

**중요 규칙:**
1. 사용자가 데이터를 조회하고 싶어하면, SQL 쿼리를 생성해서 ```sql 블록으로 제공하세요.
2. 관세 관련 질문에는 데이터베이스 정보를 활용해 답변하세요.
3. 국가명은 정규화되어 있습니다: South Korea, China, Vietnam, Taiwan, EU, USA 등
4. 항상 한국어로 답변하세요.
5. SQL 쿼리 결과가 필요하면 쿼리를 제공하고 "이 쿼리를 실행해보세요"라고 안내하세요.

**SQL 쿼리 작성 시 주의:**
- 테이블명: tariff_items
- LIKE 사용 시: WHERE hs_code LIKE '72%'
- 정확한 컬럼명 사용
"""
    
    messages = [{"role": "system", "content": system_prompt}]
    
    # 최근 대화 내역 추가 (최대 10개)
    for msg in chat_history[-10:]:
        messages.append({"role": msg["role"], "content": msg["content"]})
    
    messages.append({"role": "user", "content": user_message})
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=1500
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ AI 응답 오류: {str(e)}"


def get_filtered_data(issuing_country: str, country: str, hs_code_prefix: str) -> pd.DataFrame:
    """필터 조건에 맞는 데이터 조회"""
    conn = get_connection()
    
    query = """
        SELECT 
            issuing_country AS "발급국가",
            country AS "대상국가",
            hs_code AS "HS코드",
            tariff_type AS "관세유형",
            tariff_rate AS "관세율(%)",
            company AS "회사명",
            case_number AS "케이스번호",
            product_description AS "제품설명",
            effective_date_from AS "시행일(시작)",
            effective_date_to AS "시행일(종료)",
            basis_law AS "법적근거",
            note AS "비고"
        FROM tariff_items 
        WHERE 1=1
    """
    
    params = []
    
    if issuing_country != "All":
        query += " AND issuing_country = ?"
        params.append(issuing_country)
    
    if country != "All":
        query += " AND country = ?"
        params.append(country)
    
    if hs_code_prefix:
        query += " AND hs_code LIKE ?"
        params.append(f"{hs_code_prefix}%")
    
    query += " ORDER BY issuing_country, country, hs_code"
    
    return pd.read_sql(query, conn, params=params)


def render_chatbot():
    """챗봇 사이드바 렌더링"""
    st.sidebar.markdown("## 🤖 AI 관세 어시스턴트")
    st.sidebar.markdown("---")
    
    # 대화 내역 초기화
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    
    # 대화 내역 표시
    chat_container = st.sidebar.container()
    with chat_container:
        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                st.markdown(f'<div class="chat-message user-message">👤 {msg["content"]}</div>', 
                           unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-message assistant-message">🤖 {msg["content"]}</div>', 
                           unsafe_allow_html=True)
    
    # 입력 폼
    with st.sidebar.form(key="chat_form", clear_on_submit=True):
        user_input = st.text_area(
            "질문을 입력하세요:",
            placeholder="예: 한국에 적용되는 반덤핑 관세율을 알려줘",
            height=80
        )
        col1, col2 = st.columns([1, 1])
        with col1:
            submit = st.form_submit_button("💬 전송", use_container_width=True)
        with col2:
            clear = st.form_submit_button("🗑️ 초기화", use_container_width=True)
    
    if submit and user_input.strip():
        # 사용자 메시지 추가
        st.session_state.chat_history.append({
            "role": "user", 
            "content": user_input.strip()
        })
        
        # AI 응답 생성
        with st.spinner("AI가 답변 중..."):
            response = chat_with_ai(user_input.strip(), st.session_state.chat_history)
        
        # AI 응답 추가
        st.session_state.chat_history.append({
            "role": "assistant",
            "content": response
        })
        
        st.rerun()
    
    if clear:
        st.session_state.chat_history = []
        st.rerun()
    
    # SQL 쿼리 실행 섹션
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📝 SQL 쿼리 실행")
    
    with st.sidebar.form(key="sql_form"):
        sql_input = st.text_area(
            "SQL 쿼리:",
            placeholder="SELECT * FROM tariff_items LIMIT 10",
            height=80
        )
        run_sql = st.form_submit_button("▶️ 실행", use_container_width=True)
    
    if run_sql and sql_input.strip():
        result = execute_sql_query(sql_input.strip())
        if "error" in result.columns:
            st.sidebar.error(result["error"].iloc[0])
        else:
            st.sidebar.success(f"✓ {len(result)}건 조회됨")
            st.sidebar.dataframe(result, height=200)


def main():
    # 챗봇 사이드바
    render_chatbot()
    
    # 헤더
    st.markdown('<div class="main-header">📊 관세 데이터 대시보드</div>', unsafe_allow_html=True)
    
    # session_state 초기화
    if "search_clicked" not in st.session_state:
        st.session_state.search_clicked = False
    
    # 필터 섹션
    st.markdown("### 🔍 데이터 필터")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        issuing_countries = get_unique_values("issuing_country")
        selected_issuing = st.selectbox(
            "📌 Issuing Country (발급국가)",
            options=issuing_countries,
            help="관세 조치를 발급한 국가를 선택하세요"
        )
    
    with col2:
        countries = get_unique_values("country")
        selected_country = st.selectbox(
            "🌍 Country (대상국가)",
            options=countries,
            help="관세 조치 대상 국가를 선택하세요"
        )
    
    with col3:
        hs_code_input = st.text_input(
            "📦 HS Code (앞 2자리 이상 입력)",
            placeholder="예: 72",
            help="HS 코드 앞자리를 입력하면 해당 코드로 시작하는 모든 데이터가 검색됩니다"
        )
    
    # 검색 버튼
    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
    with col_btn2:
        if st.button("🔍 검색", type="primary", use_container_width=True):
            st.session_state.search_clicked = True
    
    # 구분선
    st.divider()
    
    # 검색 버튼을 클릭하지 않은 경우 안내 메시지 표시
    if not st.session_state.search_clicked:
        st.info("👆 필터 조건을 선택하고 **검색** 버튼을 클릭하세요.")
        return
    
    # 데이터 조회
    df = get_filtered_data(selected_issuing, selected_country, hs_code_input)
    
    # 결과 통계
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("📊 검색 결과", f"{len(df):,}건")
    with col2:
        unique_hs = df["HS코드"].nunique() if not df.empty else 0
        st.metric("📦 HS 코드 수", f"{unique_hs:,}개")
    with col3:
        unique_companies = df["회사명"].nunique() if not df.empty else 0
        st.metric("🏢 회사 수", f"{unique_companies:,}개")
    with col4:
        avg_rate = df["관세율(%)"].mean() if not df.empty and df["관세율(%)"].notna().any() else 0
        st.metric("📈 평균 관세율", f"{avg_rate:.2f}%")
    
    st.divider()
    
    # 데이터 테이블
    if df.empty:
        st.warning("⚠️ 선택한 조건에 해당하는 데이터가 없습니다.")
    else:
        st.markdown("### 📋 관세 데이터 목록")
        
        # 데이터 테이블 표시
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            height=400
        )
        
        # 다운로드 버튼
        csv = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            label="📥 CSV 다운로드",
            data=csv,
            file_name="tariff_data_filtered.csv",
            mime="text/csv"
        )
        
        st.divider()
        
        # 상세 정보 섹션
        st.markdown("### 📑 상세 정보 보기")
        
        if len(df) > 0:
            # 선택 가능한 항목 생성
            df_display = df.copy()
            df_display["선택"] = df_display.apply(
                lambda x: f"{x['발급국가']} → {x['대상국가']} | {x['HS코드']} | {x['회사명'] or 'N/A'}", 
                axis=1
            )
            
            selected_item = st.selectbox(
                "상세 정보를 볼 항목을 선택하세요:",
                options=df_display["선택"].tolist()
            )
            
            if selected_item:
                idx = df_display[df_display["선택"] == selected_item].index[0]
                row = df.iloc[df.index.get_loc(idx)]
                
                # null/None/NaN 값을 빈 문자열로 변환하는 헬퍼 함수
                def format_value(val):
                    if val is None or (isinstance(val, float) and pd.isna(val)) or str(val).lower() == 'null':
                        return None
                    return val
                
                st.markdown("---")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### 🌐 국가 정보")
                    st.write(f"**발급국가:** {row['발급국가']}")
                    st.write(f"**대상국가:** {row['대상국가']}")
                    
                    st.markdown("#### 📦 제품 정보")
                    st.write(f"**HS 코드:** {row['HS코드']}")
                    if format_value(row['제품설명']):
                        st.write(f"**제품설명:** {row['제품설명']}")
                
                with col2:
                    st.markdown("#### 💰 관세 정보")
                    if format_value(row['관세유형']):
                        st.write(f"**관세유형:** {row['관세유형']}")
                    if format_value(row['관세율(%)']):
                        st.write(f"**관세율:** {row['관세율(%)']}%")
                    
                    st.markdown("#### 📅 기간 정보")
                    if format_value(row['시행일(시작)']):
                        st.write(f"**시행일(시작):** {row['시행일(시작)']}")
                    if format_value(row['시행일(종료)']):
                        st.write(f"**시행일(종료):** {row['시행일(종료)']}")
                
                # 추가 정보
                st.markdown("#### 📝 추가 정보")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if format_value(row['회사명']):
                        st.write(f"**회사명:** {row['회사명']}")
                with col2:
                    if format_value(row['케이스번호']):
                        st.write(f"**케이스번호:** {row['케이스번호']}")
                with col3:
                    if format_value(row['법적근거']):
                        st.write(f"**법적근거:** {row['법적근거']}")
                
                if format_value(row['비고']):
                    st.info(f"💡 **비고:** {row['비고']}")


if __name__ == "__main__":
    main()

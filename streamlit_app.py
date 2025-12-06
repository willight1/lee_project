"""
관세 데이터 대시보드
Streamlit 기반 tariff_data.db 시각화 애플리케이션
"""

import streamlit as st
import sqlite3
import pandas as pd

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
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_connection():
    """데이터베이스 연결"""
    return sqlite3.connect("tariff_data.db", check_same_thread=False)


@st.cache_data
def get_unique_values(column: str) -> list:
    """특정 컬럼의 고유값 목록 조회"""
    conn = get_connection()
    query = f"SELECT DISTINCT {column} FROM tariff_items WHERE {column} IS NOT NULL ORDER BY {column}"
    df = pd.read_sql(query, conn)
    return ["All"] + df[column].tolist()


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


def main():
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
                
                st.markdown("---")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### 🌐 국가 정보")
                    st.write(f"**발급국가:** {row['발급국가']}")
                    st.write(f"**대상국가:** {row['대상국가']}")
                    
                    st.markdown("#### 📦 제품 정보")
                    st.write(f"**HS 코드:** {row['HS코드']}")
                    st.write(f"**제품설명:** {row['제품설명'] or 'N/A'}")
                
                with col2:
                    st.markdown("#### 💰 관세 정보")
                    st.write(f"**관세유형:** {row['관세유형']}")
                    st.write(f"**관세율:** {row['관세율(%)']}%")
                    
                    st.markdown("#### 📅 기간 정보")
                    st.write(f"**시행일(시작):** {row['시행일(시작)'] or 'N/A'}")
                    st.write(f"**시행일(종료):** {row['시행일(종료)'] or 'N/A'}")
                
                # 추가 정보
                st.markdown("#### 📝 추가 정보")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.write(f"**회사명:** {row['회사명'] or 'N/A'}")
                with col2:
                    st.write(f"**케이스번호:** {row['케이스번호'] or 'N/A'}")
                with col3:
                    st.write(f"**법적근거:** {row['법적근거'] or 'N/A'}")
                
                if row['비고']:
                    st.info(f"💡 **비고:** {row['비고']}")


if __name__ == "__main__":
    main()

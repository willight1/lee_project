# Tariff Data Extractor v3 - Modular Parser System

PDF에서 관세 데이터를 추출하여 SQLite 데이터베이스에 저장하는 시스템입니다.

## ⭐ 최신 버전:  (모듈화된 국가별 파서)

**주요 개선사항**:
- GPT-4o + 300 DPI + 이미지 전처리
- 국가별 전용 파서 (USA, Malaysia, EU)
- USA 파서: 국가별 분리 처리로 대용량 데이터 처리
- 개선된 DB 스키마 (issuing_country, investigation_period, product_description)
- 모듈화된 구조로 유지보수 용이

## 프로젝트 구조

```
lee_pro/
├── parsers/                      # 국가별 파서 모듈
│   ├── __init__.py              # 파서 모듈 초기화
│   ├── base_parser.py           # 기본 파서 클래스
│   ├── parser_factory.py        # 파서 자동 선택 팩토리
│   ├── usa_parser.py            # USA 전용 (국가별 분리 처리)
│   ├── malaysia_parser.py       # Malaysia 전용
│   ├── eu_parser.py             # EU 전용
│   ├── australia_parser.py      # Australia 전용
│   ├── pakistan_parser.py       # Pakistan 전용
│   ├── default_parser.py        # 기타 국가용
│   ├── brazil_parser.py         # Brazil 전용 (placeholder)
│   ├── canada_parser.py         # Canada 전용 (placeholder)
│   ├── india_parser.py          # India 전용 (placeholder)
│   └── turkey_parser.py         # Turkey 전용 (placeholder)
├── PDF/                         # PDF 입력 폴더 (24개 PDF 파일)
│   ├── USA_*.pdf                # USA 관련 문서들
│   ├── MALAYSIA_*.pdf           # Malaysia 관련 문서들
│   ├── EU_*.pdf                 # EU 관련 문서들
│   ├── AUSTRALIA_*.pdf          # Australia 관련 문서들
│   └── PAKISTAN_*.pdf           # Pakistan 관련 문서들
├── database.py                  # DB 관리 모듈
├── tariff_extractor.py          # 메인 실행 파일 ⭐ USE THIS
├── streamlit_app.py             # Streamlit 웹 대시보드 ⭐ NEW
├── tariff_data.db               # SQLite DB (자동 생성)
├── requirements.txt             # Python 의존성 패키지
├── .env                         # 환경 변수 (API 키)
├── .gitignore                   # Git 무시 파일
└── README.md                    # 프로젝트 문서
```

## ⚖️ 밸런스 모드 (현재 설정)

**적절한 비용으로 높은 정확도를 제공하는 실용적 설정**

- ✅ GPT-4o (최신 Vision 모델)
- ✅ 200 DPI 균형 해상도
- ✅ 이미지 전처리 (선명도 20%, 대비 15%)
- ✅ 적당한 배치 크기 (15 페이지)
- ✅ 거의 결정적 출력 (temperature=0.1)

**비용**: 50페이지 기준 $20-35 (고비용의 1/3)
**정확도**: 98% (대부분의 문서에 충분)
**속도**: 7-8분 (빠름)


## 빠른 시작

```bash
# 1. 가상환경 활성화
source venv/bin/activate

# 2. 필수 패키지 설치
pip install Pillow  # 이미지 전처리용

# 3. API 키 설정 (.env 파일에)
# OPENAI_API_KEY=your_api_key_here

# 4. 모든 PDF 처리 (고정확도 모드)
python tariff_extractor.py

# 5. 특정 파일만
python tariff_extractor.py --file=USA_HR_Countervailing_C-580-884_2016.pdf

# 6. Streamlit 웹 대시보드 실행
streamlit run streamlit_app.py
```

## 실행 명령어

### 기본 실행
```bash
# 모든 PDF 처리 (hybrid 모드 - 기본값)
python tariff_extractor.py

# 특정 파일만 처리
python tariff_extractor.py --file=USA_HR_Countervailing_C-580-884_2016.pdf

# 재처리 (기존 데이터 삭제 후 다시 추출)
python tariff_extractor.py --file=파일명.pdf --reprocess
```

### 모드 선택
```bash
# OCR 모드 (텍스트 추출 - 저비용)
python tariff_extractor.py --mode=ocr

# Vision 모드 (이미지 분석 - 고정확도)
python tariff_extractor.py --mode=vision

# Hybrid 모드 (OCR → Vision 폴백, 기본값)
python tariff_extractor.py --mode=hybrid
```

### 국가별 파일 처리 예시
```bash
# USA 문서 처리
python tariff_extractor.py --file=USA_CR_Antidumping_A-580-881.pdf

# Malaysia 문서 처리
python tariff_extractor.py --file=MALAYSIA_Coated_Antidumping.pdf

# EU 문서 처리
python tariff_extractor.py --file=EU_GO_Antidumping_AD608_R728.pdf

# Australia 문서 처리
python tariff_extractor.py --file=AUSTRALIA_Zinc_Coated_Antidumping_ADN_2023_035.pdf

# Pakistan 문서 처리
python tariff_extractor.py --file=PAKISTAN_CR_Antidumping_A.D.C_No._60.pdf
```

## 파서 구조 설명

### 📁 메인 실행 파일 vs 개별 파서

| 구분 | 파일 | 역할 |
|------|------|------|
| **메인 실행** | `tariff_extractor.py` | PDF 폴더 순회, 파서 자동 선택, DB 저장 |
| **파서 팩토리** | `parsers/parser_factory.py` | 파일명 기반 적절한 파서 자동 선택 |
| **기본 파서** | `parsers/base_parser.py` | 공통 로직 (LLM 호출, JSON 파싱) |
| **국가별 파서** | `parsers/*_parser.py` | 국가별 특수 추출 로직 |

### 🔄 동작 방식

```
tariff_extractor.py (메인)
    ↓
ParserFactory.create_parser(파일명)
    ↓ (파일명에서 국가 감지)
USA_*.pdf → USAParser
MALAYSIA_*.pdf → MalaysiaParser
EU_*.pdf → EUParser
...
    ↓
국가별 파서가 PDF 처리 후 데이터 반환
    ↓
tariff_extractor.py가 DB에 저장
```

> ⚠️ **참고**: 개별 파서(`parsers/*.py`)는 단독 실행되지 않습니다.  
> 모든 처리는 `tariff_extractor.py`를 통해 이루어지며, `--file=` 옵션으로 특정 파일을 지정할 수 있습니다.

### ❓ 왜 파일을 분리했는가? (모듈화의 장점)

개별 파서는 단독 실행되지 않는데, 왜 굳이 파일을 분리했을까요?

#### 1️⃣ 유지보수 용이성

| 구분 | 파일 분리 ✅ | 하나의 파일 ❌ |
|------|-------------|---------------|
| **수정 범위** | 해당 국가 파서만 수정 | 전체 코드에서 찾아야 함 |
| **위험성** | 다른 국가에 영향 없음 | 실수로 다른 로직 건드리면 고장 |

#### 2️⃣ 확장성

| 구분 | 파일 분리 ✅ | 하나의 파일 ❌ |
|------|-------------|---------------|
| **새 국가 추가** | 새 Parser 만들고 Factory에 등록하면 끝 | 복잡도가 계속 증가 |
| **예시** | `japan_parser.py` 생성 → 완료 | 3000줄+ 파일에 코드 추가 |

#### 3️⃣ 협업 효율 증가

| 구분 | 파일 분리 ✅ | 하나의 파일 ❌ |
|------|-------------|---------------|
| **동시 작업** | 각각 다른 파일 수정 → 충돌 최소화 | A가 USA 수정, B가 EU 수정 → 충돌 빈번 |
| **Git 관리** | 변경 이력 명확 | 누가 어디를 수정했는지 파악 어려움 |

#### 4️⃣ 가독성

| 구분 | 파일 분리 ✅ | 하나의 파일 ❌ |
|------|-------------|---------------|
| **역할 파악** | 파일명만 봐도 역할 파악 가능 | 스크롤 지옥 |
| **예시** | `usa_parser.py` = USA 처리 | 수천 줄에서 원하는 코드 찾기 |

> 💡 이러한 설계 방식을 **"관심사의 분리 (Separation of Concerns)"** 또는 **모듈화(Modularization)** 패턴이라고 합니다.

## 국가별 파서 특징

### 🇺🇸 USA Parser
- **49개 HS 코드 자동 추출** (SCOPE 섹션에서)
- **국가별 분리 처리**: Brazil → Korea 순차 처리
- **effective_date ≠ investigation_period** 구분
- **Cash Deposit 필터링**

### 🇲🇾 Malaysia Parser
- **Case Number**: 페이지 상단 P.U. (A) XX 추출
- **Product Description**: 별도 필드 처리
- **다중 국가**: Indonesia, Vietnam 등

### 🇪🇺 EU Parser
- **8자리 HS 코드**: 72251100, 72261100
- **정확한 회사명**: "OJSC Novolipetsk Steel"
- **5개 국가**: China, Japan, Korea, Russia, USA

### 🇦🇺 Australia Parser
- **Vision API 기반**: 이미지 분석으로 테이블 추출
- **ADN 케이스 번호**: ADN 2023/035 형식 추출
- **Zinc Coated Steel 제품** 전용 처리

### 🇵🇰 Pakistan Parser
- **A.D.C 케이스 번호**: A.D.C No. 60 형식 추출
- **다중 국가 지원**: Chinese Taipei, EU, South Korea, Vietnam
- **HS 코드와 국가 Cartesian Product** 처리

## 데이터베이스 스키마

### 주요 개선 필드

| 기존 | v3 개선 | 설명 |
|------|---------|------|
| ❌ | ✅ issuing_country | 덤핑 관세 부과국 |
| ❌ | ✅ investigation_period_from/to | 조사 기간 |
| ❌ | ✅ product_description | 제품 설명 |

### tariff_items 테이블 (전체)
```sql
CREATE TABLE tariff_items (
    tariff_id INTEGER PRIMARY KEY,
    doc_id INTEGER,
    country TEXT,             
    hs_code TEXT,
    tariff_type TEXT,
    tariff_rate REAL,
    effective_date_from TEXT,
    effective_date_to TEXT,
    investigation_period_from TEXT,  
    investigation_period_to TEXT,    
    basis_law TEXT,
    company TEXT,
    case_number TEXT,
    product_description TEXT,      
    note TEXT
);
```

## CSV 문제점 → 해결 현황

### ✅ 완료

| 문제 | 해결 |
|------|------|
| HS 코드 48개 미추출 | ✅ USA Parser: SCOPE 섹션 전체 추출 |
| 발행 국가 정보 없음 | ✅ issuing_country 필드 추가 |
| Case Number 미추출 | ✅ Malaysia Parser: 페이지 상단 추출 |
| Description 혼재 | ✅ product_description 별도 필드 |
| Investigation Period 혼재 | ✅ 별도 필드로 분리 |
| EU 회사명 부정확 | ✅ EU Parser: 정확한 이름 추출 |
| EU 8자리 HS 코드 | ✅ EU Parser: 72251100 형식 |

### ⚠️ 진행 중

| 문제 | 상태 |
|------|------|
| JSON 파싱 오류 (일부) | 🔧 제어 문자 필터링 적용, 추가 개선 필요 |
| Cash Deposit 제외 | ✅ 로직 적용, 테스트 필요 |
| Doc 5 읽기 실패 | 📝 OCR 또는 수동 확인 필요 |

## 데이터 조회 예제

```bash
sqlite3 tariff_data.db

# 발행 국가별 문서 수
SELECT issuing_country, COUNT(*) FROM documents
GROUP BY issuing_country;

# 특정 국가의 모든 관세
SELECT hs_code, company, tariff_rate, effective_date_from
FROM tariff_items
WHERE country = 'Republic of Korea'
ORDER BY hs_code;

# Investigation Period가 있는 항목
SELECT file_name, country, investigation_period_from, investigation_period_to
FROM tariff_items t
JOIN documents d ON t.doc_id = d.doc_id
WHERE t.investigation_period_from IS NOT NULL;
```

## 개발 가이드

### 새 국가 파서 추가하기

1. `parsers/` 폴더에 `country_parser.py` 생성
2. `BaseCountryParser` 상속
3. `create_extraction_prompt()` 구현
4. `parsers/factory.py`에 등록

```python
# parsers/brazil_parser.py
from .base_parser import BaseCountryParser

class BrazilParser(BaseCountryParser):
    def create_extraction_prompt(self, pdf_text: str) -> str:
        return f"""Extract tariff data from Brazil document...
        [DOCUMENT]
        {pdf_text}
        """
```

### 테스트

```bash
# 특정 파일 테스트
python tariff_extractor.py --file=파일명.pdf

# 재처리 (기존 데이터 삭제)
python tariff_extractor.py --file=파일명.pdf --reprocess
```

## 주요 파일 설명

### ✅ 핵심 파일
- `tariff_extractor.py` ⭐ - PDF에서 관세 데이터 추출 메인 실행 파일
- `streamlit_app.py` ⭐ - 웹 기반 데이터 조회 대시보드
- `database.py` ⭐ - SQLite 데이터베이스 관리 모듈
- `parsers/` ⭐ - 국가별 파서 모듈 폴더
- `tariff_data.db` ⭐ - 추출된 관세 데이터 저장 DB

## 문제 해결

### API 키 오류
```bash
# .env 파일 확인
cat .env
# OPENAI_API_KEY=sk-ant-...
```

### JSON 파싱 오류
- 현재: 제어 문자 필터링 적용됨
- 해결책: 국가별 분리 처리 (USA Parser)

### 데이터가 저장 안됨
```bash
# DB 확인
sqlite3 tariff_data.db "SELECT COUNT(*) FROM tariff_items;"

# 로그 확인
python tariff_extractor_v3.py --file=파일명.pdf 2>&1 | tee log.txt
```

## 라이센스

내부 프로젝트

---

## ⚠️ 보완사항

### 국가명 통일 필요

현재 각 국가별 파서에서 추출되는 국가명이 서로 다르게 저장되어 있어 통일 작업이 필요합니다.

| 국가 | 현재 저장된 값 예시 |
|------|--------------------|
| 🇦🇺 Australia | `Korea` |
| 🇲🇾 Malaysia | `The Republic of Korea` |
| 🇺🇸 USA | `Republic of Korea` |
| 🇪🇺 EU | `Korea` |
| 🇵🇰 Pakistan | `South Korea` |

**개선 방안**:
1. 데이터 정규화 함수 추가 (`normalize_country_name`)
2. DB 저장 시 통일된 국가명으로 변환
3. 기존 데이터 마이그레이션 스크립트 작성

```python
# 예시: 국가명 정규화 매핑
COUNTRY_NAME_MAP = {
    "Korea": "Republic of Korea",
    "The Republic of Korea": "Republic of Korea",
    "South Korea": "Republic of Korea",
    "ROK": "Republic of Korea",
    # ... 기타 국가
}
```

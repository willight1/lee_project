# 📊 Tariff Data Extractor

PDF에서 관세(덤핑방지/상계관세) 데이터를 추출하여 SQLite 데이터베이스에 저장하고, 웹 대시보드로 조회하는 시스템입니다.

## 📌 프로젝트 개요

| 항목 | 내용 |
|------|------|
| **목적** | PDF 관세 문서에서 HS 코드, 관세율, 회사명 등 자동 추출 |
| **기술 스택** | Python, OpenAI GPT-4o, SQLite, Streamlit |
| **처리 문서** | 24개 PDF (USA, Malaysia, EU, Australia, Pakistan) |
| **추출 데이터** | 2,231건의 관세 항목 |

---

## 🗂️ 프로젝트 구조

```
lee_pro/
├── parsers/                      # 국가별 파서 모듈
│   ├── __init__.py              # 파서 모듈 초기화
│   ├── base_parser.py           # 기본 파서 클래스 (LLM 호출, JSON 파싱)
│   ├── parser_factory.py        # 파서 자동 선택 팩토리
│   ├── usa_parser.py            # 🇺🇸 USA 전용
│   ├── malaysia_parser.py       # 🇲🇾 Malaysia 전용
│   ├── eu_parser.py             # 🇪🇺 EU 전용
│   ├── australia_parser.py      # 🇦🇺 Australia 전용
│   ├── pakistan_parser.py       # 🇵🇰 Pakistan 전용
│   ├── default_parser.py        # 기타 국가용
│   ├── brazil_parser.py         # 🇧🇷 Brazil (placeholder)
│   ├── canada_parser.py         # 🇨🇦 Canada (placeholder)
│   ├── india_parser.py          # 🇮🇳 India (placeholder)
│   └── turkey_parser.py         # 🇹🇷 Turkey (placeholder)
├── PDF/                         # PDF 입력 폴더 (24개 파일)
├── database.py                  # SQLite DB 관리 모듈
├── tariff_extractor.py          # 메인 실행 파일 ⭐
├── streamlit_app.py             # 웹 대시보드 ⭐
├── tariff_data.db               # SQLite 데이터베이스
├── requirements.txt             # Python 의존성
├── .env                         # 환경 변수 (API 키)
└── README.md                    # 프로젝트 문서
```

---

## 🚀 빠른 시작

### 1. 환경 설정

```bash
# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# API 키 설정 (.env 파일)
echo "OPENAI_API_KEY=your_api_key_here" > .env
```

### 2. PDF 데이터 추출

```bash
# 모든 PDF 처리
python tariff_extractor.py

# 특정 파일만 처리
python tariff_extractor.py --file=USA_CR_Antidumping_A-580-881.pdf

# 재처리 (기존 데이터 삭제 후)
python tariff_extractor.py --file=파일명.pdf --reprocess
```

### 3. 웹 대시보드 실행

```bash
streamlit run streamlit_app.py
```

---

## 📋 실행 모드

| 모드 | 명령어 | 설명 |
|------|--------|------|
| **Hybrid** (기본) | `python tariff_extractor.py` | OCR 시도 → 실패 시 Vision 폴백 |
| **OCR** | `python tariff_extractor.py --mode=ocr` | 텍스트 추출 (저비용) |
| **Vision** | `python tariff_extractor.py --mode=vision` | 이미지 분석 (고정확도) |

---

## 🏗️ 시스템 아키텍처

### 동작 흐름

```
┌─────────────────────────────────────────────────────────────┐
│                    tariff_extractor.py                      │
│                      (메인 실행 파일)                         │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  ParserFactory.create_parser()              │
│                    (파일명 기반 파서 선택)                     │
└─────────────────────────┬───────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │USA Parser│    │EU Parser │    │ 기타...  │
    └────┬─────┘    └────┬─────┘    └────┬─────┘
         │               │               │
         └───────────────┴───────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     TariffDatabase                          │
│                   (SQLite 저장/조회)                         │
└─────────────────────────────────────────────────────────────┘
```

> ⚠️ **참고**: 개별 파서(`parsers/*.py`)는 단독 실행되지 않습니다.  
> 모든 처리는 `tariff_extractor.py`를 통해 이루어집니다.

---

## ❓ 왜 파일을 분리했는가? (모듈화의 장점)

| 항목 | 파일 분리 ✅ | 하나의 파일 ❌ |
|------|-------------|---------------|
| **유지보수** | 해당 국가 파서만 수정 | 실수로 다른 로직 건드리면 고장 |
| **확장성** | 새 Parser 만들고 Factory에 등록하면 끝 | 복잡도가 계속 증가 |
| **협업** | 각각 다른 파일 수정 → 충돌 최소화 | A가 USA, B가 EU 수정 → 충돌 빈번 |
| **가독성** | 파일명만 봐도 역할 파악 | 스크롤 지옥 |

> 💡 이러한 설계 방식을 **"관심사의 분리 (Separation of Concerns)"** 또는 **모듈화(Modularization)** 패턴이라고 합니다.

---

## 🌍 국가별 파서 특징

### 🇺🇸 USA Parser
- SCOPE 섹션에서 **49개 HS 코드 자동 추출**
- 국가별 분리 처리 (Brazil → Korea 순차)
- effective_date ≠ investigation_period 구분
- Cash Deposit Rate는 note 필드에 기록

### 🇲🇾 Malaysia Parser
- 페이지 상단에서 **P.U. (A) XX** 케이스 번호 추출
- Product Description 별도 필드 처리
- 다중 국가 지원: Indonesia, Vietnam 등

### 🇪🇺 EU Parser
- **8자리 HS 코드** 추출 (72251100 형식)
- 정확한 회사명 추출 ("OJSC Novolipetsk Steel")
- 5개 국가: China, Japan, Korea, Russia, USA

### 🇦🇺 Australia Parser
- Vision API 기반 테이블 추출
- **ADN 2023/035** 형식 케이스 번호 추출
- Zinc Coated Steel 제품 전용 처리

### 🇵🇰 Pakistan Parser
- **A.D.C No. 60** 형식 케이스 번호 추출
- 다중 국가: Chinese Taipei, EU, South Korea, Vietnam
- HS 코드 × 국가 Cartesian Product 처리

---

## 🗄️ 데이터베이스 스키마

### tariff_items 테이블

| 필드 | 타입 | 설명 |
|------|------|------|
| `tariff_id` | INTEGER | Primary Key |
| `doc_id` | INTEGER | 문서 ID (Foreign Key) |
| `issuing_country` | TEXT | 관세 부과국 (USA, Malaysia 등) |
| `country` | TEXT | 대상국 (수출국) |
| `hs_code` | TEXT | HS 코드 |
| `tariff_type` | TEXT | 관세 유형 (Antidumping, Countervailing) |
| `tariff_rate` | REAL | 관세율 (%) |
| `effective_date_from` | TEXT | 시행일 (시작) |
| `effective_date_to` | TEXT | 시행일 (종료) |
| `investigation_period_from` | TEXT | 조사기간 (시작) |
| `investigation_period_to` | TEXT | 조사기간 (종료) |
| `company` | TEXT | 회사명 |
| `case_number` | TEXT | 케이스 번호 |
| `product_description` | TEXT | 제품 설명 |
| `note` | TEXT | 비고 |

---

## 📊 데이터 조회 예제

```sql
-- 발급 국가별 문서 수
SELECT issuing_country, COUNT(*) FROM documents
GROUP BY issuing_country;

-- 특정 국가의 모든 관세
SELECT hs_code, company, tariff_rate, effective_date_from
FROM tariff_items
WHERE country = 'Republic of Korea'
ORDER BY hs_code;

-- HS 코드로 검색
SELECT * FROM tariff_items
WHERE hs_code LIKE '7225%';
```

---

## ✅ 해결된 문제들

| 문제 | 해결 방법 |
|------|----------|
| HS 코드 미추출 | USA Parser: SCOPE 섹션 전체 추출 |
| 발행 국가 정보 없음 | `issuing_country` 필드 추가 |
| Case Number 미추출 | Malaysia Parser: 페이지 상단 추출 |
| JSON 파싱 오류 | `try_repair_json` 함수로 잘린 JSON 복구 |
| EU 8자리 HS 코드 | EU Parser: 72251100 형식 지원 |
| Cash Deposit 처리 | USA Parser: note 필드에 기록 |

---

## 🛠️ 새 국가 파서 추가 방법

### 1. 파서 파일 생성
```python
# parsers/japan_parser.py
from .base_parser import TextBasedParser

class JapanTextParser(TextBasedParser):
    def create_extraction_prompt(self) -> str:
        return """Extract tariff data from Japan document...
        [Required fields: hs_code, country, tariff_rate, ...]
        """
```

### 2. Factory에 등록
```python
# parsers/parser_factory.py
from .japan_parser import JapanTextParser

# create_parser 메서드에 추가
elif 'JAPAN_' in file_name_upper:
    return JapanTextParser(client)
```

---

## ⚠️ 보완사항

### 국가명 통일 필요

현재 각 국가별 파서에서 추출되는 국가명이 서로 다르게 저장되어 있습니다.

| 파서 | 현재 저장된 값 |
|------|---------------|
| 🇦🇺 Australia | `Korea` |
| 🇲🇾 Malaysia | `The Republic of Korea` |
| 🇺🇸 USA | `Republic of Korea` |
| 🇪🇺 EU | `Korea` |
| 🇵🇰 Pakistan | `South Korea` |

**→ 통일해서 DB에 저장 필요**

**개선 방안**:
```python
COUNTRY_NAME_MAP = {
    "Korea": "Republic of Korea",
    "The Republic of Korea": "Republic of Korea", 
    "South Korea": "Republic of Korea",
    "ROK": "Republic of Korea",
}
```

---

## 📝 라이센스

내부 프로젝트

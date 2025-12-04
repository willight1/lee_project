# Tariff Data Extractor v3 - Modular Parser System

PDF에서 관세 데이터를 추출하여 SQLite 데이터베이스에 저장하는 시스템입니다.

## ⭐ 최신 버전: v3 (모듈화된 국가별 파서)

**주요 개선사항**:
- 🔥 **고비용 고정확도 모드** - GPT-4o + 300 DPI + 이미지 전처리
- 국가별 전용 파서 (USA, Malaysia, EU)
- USA 파서: 국가별 분리 처리로 대용량 데이터 처리
- 개선된 DB 스키마 (issuing_country, investigation_period, product_description)
- 모듈화된 구조로 유지보수 용이

## 프로젝트 구조

```
lee_test1/
├── parsers/                      # 국가별 파서 모듈 ⭐ NEW
│   ├── __init__.py
│   ├── base_parser.py           # 기본 파서 클래스
│   ├── usa_parser.py            # USA 전용 (국가별 분리 처리)
│   ├── malaysia_parser.py       # Malaysia 전용
│   ├── eu_parser.py             # EU 전용
│   ├── default_parser.py        # 기타 국가용
│   └── factory.py               # 파서 자동 선택
├── database.py                  # DB 관리 모듈 ⭐ NEW
├── tariff_extractor_v3.py       # 메인 실행 파일 ⭐ USE THIS
├── PDF/                         # PDF 입력 폴더
└── tariff_data.db              # SQLite DB (자동 생성)
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

📖 자세한 내용: [BALANCED_MODE.md](./BALANCED_MODE.md)
📖 더 높은 정확도 필요 시: [HIGH_ACCURACY_MODE.md](./HIGH_ACCURACY_MODE.md)

## 빠른 시작

```bash
# 1. 가상환경 활성화
source venv/bin/activate

# 2. 필수 패키지 설치
pip install Pillow  # 이미지 전처리용

# 3. API 키 설정 (.env 파일에)
# OPENAI_API_KEY=your_api_key_here

# 4. 모든 PDF 처리 (고정확도 모드)
python tariff_extractor_v3.py

# 5. 특정 파일만
python tariff_extractor_v3.py --file=USA_HR_Countervailing_C-580-884_2016.pdf
```

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
    country TEXT,                    -- 대상 국가 (수출국)
    hs_code TEXT,
    tariff_type TEXT,
    tariff_rate REAL,
    effective_date_from TEXT,
    effective_date_to TEXT,
    investigation_period_from TEXT,  -- ⭐ NEW
    investigation_period_to TEXT,    -- ⭐ NEW
    basis_law TEXT,
    company TEXT,
    case_number TEXT,
    product_description TEXT,        -- ⭐ NEW
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
python tariff_extractor_v3.py --file=파일명.pdf

# 재처리 (기존 데이터 삭제)
python tariff_extractor_v3.py --file=파일명.pdf --reprocess
```

## 파일 정리 (기존 버전)

### 🗑️ 삭제 예정
- `data_pdf.py` - v0 (초기 버전)
- `tariff_extractor.py` - v1
- `tariff_extractor_v2.py` - v2
- `trade_remedy.db` - 구 DB
- `tariff_data_old.db` - 백업

### ✅ 현재 사용
- `tariff_extractor_v3.py` ⭐
- `parsers/` 폴더 ⭐
- `database.py` ⭐
- `tariff_data.db` ⭐

## 문제 해결

### API 키 오류
```bash
# .env 파일 확인
cat .env
# ANTHROPIC_API_KEY=sk-ant-...
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

**Made with ❤️ using Claude Code & Modular Architecture**

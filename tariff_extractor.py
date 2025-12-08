"""
Tariff Information Extractor - 통합 버전

OCR(텍스트 추출) 및 Vision API 모드를 지원하는 통합 관세 정보 추출기

사용법:
    python tariff_extractor.py --mode=ocr                    # OCR 모드 (저비용)
    python tariff_extractor.py --mode=vision                 # Vision API 모드 (고정확도)
    python tariff_extractor.py --mode=ocr --file=파일명.pdf   # 특정 파일만
    python tariff_extractor.py --mode=vision --reprocess     # 재처리
"""

import os
import re
import argparse
import fitz  # PyMuPDF
from dotenv import load_dotenv
from openai import OpenAI

from database import TariffDatabase
from parsers import ParserFactory

# 환경 변수 로드
load_dotenv()

# 기본 설정
INPUT_FOLDER = "PDF"
DB_PATH = "tariff_data.db"


def extract_case_number_from_filename(file_name: str) -> str:
    """
    파일명에서 case_number 추출
    
    지원 패턴:
    - USA: A-580-881, C-580-882 등
    - Australia: ADN_2023_035
    - EU: AD608, R728
    - Malaysia: P.U.(A)_197, PUA225
    - Pakistan: A.D.C_No._60
    """
    patterns = [
        # USA: A-580-881, C-580-882
        (r'([AC]-\d{3}-\d{3})', None),
        # Australia: ADN_2023_035
        (r'(ADN[_\s]+\d{4}[_\s]+\d{3})', lambda m: m.replace('_', '/')),
        # EU: AD608, R728
        (r'(AD\d+)', None),
        (r'(R\d+)', None),
        # Malaysia: P.U.(A)_197, PUA225, P.U._(A)_23
        (r'P\.?U\.?\s*\(?A\)?\s*[_\s]*(\d+)', lambda m: f'P.U.(A) {m}'),
        (r'PUA(\d+)', lambda m: f'P.U.(A) {m}'),
        # Pakistan: A.D.C_No._60
        (r'A\.?D\.?C[_\s]*No\.?[_\s]*(\d+)', lambda m: f'A.D.C No. {m}'),
    ]
    
    for pattern, transform in patterns:
        match = re.search(pattern, file_name, re.IGNORECASE)
        if match:
            result = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
            if transform:
                result = transform(result)
            return result
    
    return None


# 국가명 정규화 매핑 테이블
COUNTRY_NAME_MAPPING = {
    # 한국
    "Republic of Korea": "South Korea",
    "The Republic of Korea": "South Korea",
    "Korea": "South Korea",
    "South Korea": "South Korea",
    "Rep. of Korea": "South Korea",
    "ROK": "South Korea",
    
    # 중국
    "People's Republic of China": "China",
    "The People's Republic of China": "China",
    "P.R.C": "China",
    "PRC": "China",
    "China": "China",
    
    # 베트남
    "The Socialist Republic of Viet Nam": "Vietnam",
    "Socialist Republic of Viet Nam": "Vietnam",
    "The Socialist Republic of Vietnam": "Vietnam",
    "Socialist Republic of Vietnam": "Vietnam",
    "Republik Sosialis Viet Nam": "Vietnam",
    "Viet Nam": "Vietnam",
    "Vietnam": "Vietnam",
    
    # 대만
    "Chinese Taipei": "Taiwan",
    "Republic of China": "Taiwan",
    "Taiwan": "Taiwan",
    
    # 태국
    "Kingdom of Thailand": "Thailand",
    "Thailand": "Thailand",
    
    # 인도네시아
    "Republic of Indonesia": "Indonesia",
    "Republik Indonesia": "Indonesia",
    "Indonesia": "Indonesia",
    
    # EU
    "European Union": "EU",
    "EU": "EU",
    
    # 터키
    "Republic of Turkey": "Turkey",
    "Türkiye": "Turkey",
    "Turkey": "Turkey",
    
    # 러시아
    "Russian Federation": "Russia",
    "Russia": "Russia",
    
    # 미국
    "United States of America": "USA",
    "United States": "USA",
    "USA": "USA",
    "U.S.A": "USA",
    
    # 일본
    "Japan": "Japan",
    
    # 인도
    "India": "India",
    "Republic of India": "India",
    
    # 브라질
    "Brazil": "Brazil",
    "Federative Republic of Brazil": "Brazil",
    
    # 호주
    "Australia": "Australia",
    "Commonwealth of Australia": "Australia",
    
    # 말레이시아
    "Malaysia": "Malaysia",
    
    # 영국
    "United Kingdom": "UK",
    "UK": "UK",
    "Great Britain": "UK",
    
    # 네덜란드
    "Netherlands": "Netherlands",
    "The Netherlands": "Netherlands",
    
    # 이탈리아
    "Italy": "Italy",
    
    # 스페인
    "Spain": "Spain",
}


def normalize_country_name(country: str) -> str:
    """
    국가명을 표준 형식으로 정규화
    
    예시:
    - "Republic of Korea" → "South Korea"
    - "People's Republic of China" → "China"
    - "The Socialist Republic of Viet Nam" → "Vietnam"
    """
    if not country:
        return country
    
    # 정확히 매칭되는 경우
    country_stripped = country.strip()
    if country_stripped in COUNTRY_NAME_MAPPING:
        return COUNTRY_NAME_MAPPING[country_stripped]
    
    # 대소문자 무시하고 매칭
    country_lower = country_stripped.lower()
    for key, value in COUNTRY_NAME_MAPPING.items():
        if key.lower() == country_lower:
            return value
    
    # 부분 매칭 시도 (예: "The People's Republic of China" 같은 변형)
    for key, value in COUNTRY_NAME_MAPPING.items():
        if key.lower() in country_lower or country_lower in key.lower():
            return value
    
    # 매칭 안되면 원본 반환
    return country_stripped


class TariffExtractor:
    """통합 Tariff Extractor (OCR + Vision)"""

    def __init__(self, db: TariffDatabase, mode: str = "ocr"):
        self.db = db
        self.mode = mode

        # OpenAI 클라이언트 초기화
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        self.client = OpenAI(api_key=api_key)

    def process_single_pdf(self, pdf_path: str) -> bool:
        """단일 PDF 처리"""
        file_name = os.path.basename(pdf_path)
        
        print(f"\n{'='*80}")
        print(f"Processing: {file_name}")
        print('='*80)

        # 발행국 추론
        issuing_country = ParserFactory.detect_issuing_country(file_name)
        print(f"  Issuing country: {issuing_country}")
        print(f"  Mode: {self.mode.upper()}")

        # 파일 정보
        file_size = os.path.getsize(pdf_path)

        # 파서 생성 (모드에 따라 OCR 또는 Vision)
        parser = ParserFactory.create_parser(file_name, self.client, self.mode)

        # 관세 정보 추출
        print(f"  Extracting tariff information...")
        items = parser.process(pdf_path)

        if not items:
            print(f"  ⚠ No tariff items found")
            return False

        # 파일명에서 case_number 추출 및 적용
        case_number = extract_case_number_from_filename(file_name)
        if case_number:
            print(f"  📋 Case number from filename: {case_number}")
            for item in items:
                if not item.get('case_number'):
                    item['case_number'] = case_number

        # 국가명 정규화
        normalized_count = 0
        for item in items:
            if item.get('country'):
                original = item['country']
                normalized = normalize_country_name(original)
                if original != normalized:
                    item['country'] = normalized
                    normalized_count += 1
        if normalized_count > 0:
            print(f"  🌍 Normalized {normalized_count} country names")

        # tariff_rate 정규화 (문자열인 경우 note로 이동)
        rate_normalized_count = 0
        for item in items:
            rate = item.get('tariff_rate')
            if rate is not None:
                # 이미 숫자인 경우 그대로 유지
                if isinstance(rate, (int, float)):
                    continue
                # 문자열인 경우 숫자로 변환 시도
                if isinstance(rate, str):
                    rate_str = rate.strip()
                    # 숫자만 추출 시도 (%, 공백 제거)
                    cleaned = rate_str.replace('%', '').replace(',', '.').strip()
                    try:
                        item['tariff_rate'] = float(cleaned)
                    except (ValueError, TypeError):
                        # 변환 실패 시 note로 이동
                        existing_note = item.get('note') or ''
                        if existing_note:
                            item['note'] = f"{existing_note}; Tariff: {rate_str}"
                        else:
                            item['note'] = f"Tariff: {rate_str}"
                        item['tariff_rate'] = None
                        rate_normalized_count += 1
        if rate_normalized_count > 0:
            print(f"  📊 Moved {rate_normalized_count} non-numeric tariff rates to note")

        # 페이지 수
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()


        processing_mode = f"{self.mode}_mode"
        doc_id = self.db.insert_document(
            file_name=file_name,
            file_path=pdf_path,
            issuing_country=issuing_country,
            total_pages=total_pages,
            file_size=file_size,
            processing_mode=processing_mode
        )

        if not doc_id:
            print(f"  ✗ Failed to insert document record")
            return False

        # tariff items 병합 삽입 (기존 데이터 보존, null 필드만 채움)
        stats = {'inserted': 0, 'merged': 0, 'skipped': 0, 'error': 0}
        for item in items:
            result = self.db.upsert_or_merge_tariff_item(doc_id, item, issuing_country)
            stats[result] = stats.get(result, 0) + 1

        print(f"  ✓ Extracted: {len(items)} | New: {stats['inserted']} | Merged: {stats['merged']} | Unchanged: {stats['skipped']}")

        # Null 값 채우기 (같은 case_number의 다른 문서에서)
        filled = self.fill_null_values_from_related_docs(doc_id, issuing_country)
        if filled > 0:
            print(f"  ✓ Filled {filled} null values from related documents")

        return True

    def fill_null_values_from_related_docs(self, doc_id: int, issuing_country: str) -> int:
        """
        같은 case_number를 가진 다른 문서에서 null 값 채우기
        
        채우는 필드들:
        - hs_code: HS 코드
        - tariff_rate: 관세율
        - tariff_type: 관세 유형
        - effective_date_from/to: 유효 기간
        - investigation_period_from/to: 조사 기간
        - basis_law: 근거 법률
        - product_description: 제품 설명

        예: USA_Plate_A-580-887_Pre_2023.pdf (HS 코드 없음)
            → USA_Plate_A-580-887_F_2022.pdf (HS 코드 있음)에서 복사
        """
        total_filled = 0
        
        # 상속 가능한 필드들 (company 포함)
        inheritable_fields = [
            'hs_code', 'tariff_type', 'tariff_rate', 'company',
            'effective_date_from', 'effective_date_to',
            'investigation_period_from', 'investigation_period_to',
            'basis_law', 'product_description'
        ]
        
        # 현재 문서에서 case_number가 있는 항목들 찾기
        self.db.cursor.execute("""
            SELECT DISTINCT case_number
            FROM tariff_items
            WHERE doc_id = ?
              AND case_number IS NOT NULL
        """, (doc_id,))
        
        case_numbers = [row['case_number'] for row in self.db.cursor.fetchall()]
        
        if not case_numbers:
            return 0
        
        for case_number in case_numbers:
            # 1. 현재 문서의 null 필드가 있는 항목들 가져오기
            self.db.cursor.execute("""
                SELECT *
                FROM tariff_items
                WHERE doc_id = ?
                  AND case_number = ?
            """, (doc_id, case_number))
            
            current_items = self.db.cursor.fetchall()
            
            if not current_items:
                continue
            
            # 2. 같은 case_number를 가진 다른 문서의 항목들에서 값 찾기
            self.db.cursor.execute("""
                SELECT *
                FROM tariff_items
                WHERE case_number = ?
                  AND doc_id != ?
                  AND issuing_country = ?
            """, (case_number, doc_id, issuing_country))
            
            related_items = self.db.cursor.fetchall()
            
            if not related_items:
                continue
            
            # 3. null 필드 채우기
            for current_item in current_items:
                tariff_id = current_item['tariff_id']
                company = current_item['company']
                country = current_item['country']
                updates = {}
                
                for field in inheritable_fields:
                    if current_item[field] is None:
                        # 같은 company와 country를 가진 관련 항목에서 먼저 찾기
                        value = None
                        
                        for related in related_items:
                            if related[field] is not None:
                                # 우선순위: 같은 company + country > 같은 company > 아무거나
                                if related['company'] == company and related['country'] == country:
                                    value = related[field]
                                    break
                                elif related['company'] == company and value is None:
                                    value = related[field]
                                elif value is None:
                                    value = related[field]
                        
                        if value is not None:
                            updates[field] = value
                
                # 업데이트 수행
                if updates:
                    set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
                    values = list(updates.values()) + [tariff_id]
                    
                    self.db.cursor.execute(f"""
                        UPDATE tariff_items
                        SET {set_clause}
                        WHERE tariff_id = ?
                    """, values)
                    
                    total_filled += len(updates)
            
            # 4. HS 코드가 null인 항목에 대해 여러 HS 코드 확장 (기존 로직 유지)
            self.db.cursor.execute("""
                SELECT tariff_id, country, company, tariff_rate
                FROM tariff_items
                WHERE doc_id = ?
                  AND case_number = ?
                  AND hs_code IS NULL
            """, (doc_id, case_number))
            
            null_hs_items = self.db.cursor.fetchall()
            
            if null_hs_items:
                # 관련 문서에서 HS 코드 목록 가져오기
                self.db.cursor.execute("""
                    SELECT DISTINCT hs_code
                    FROM tariff_items
                    WHERE case_number = ?
                      AND hs_code IS NOT NULL
                      AND issuing_country = ?
                """, (case_number, issuing_country))
                
                hs_codes = [row['hs_code'] for row in self.db.cursor.fetchall()]
                
                if hs_codes:
                    for null_item in null_hs_items:
                        tariff_id = null_item['tariff_id']
                        
                        # 첫 번째 HS 코드로 기존 항목 업데이트
                        self.db.cursor.execute("""
                            UPDATE tariff_items
                            SET hs_code = ?
                            WHERE tariff_id = ?
                        """, (hs_codes[0], tariff_id))
                        total_filled += 1
                        
                        # 나머지 HS 코드들은 새로운 항목으로 추가
                        for hs_code in hs_codes[1:]:
                            self.db.cursor.execute("""
                                INSERT INTO tariff_items (
                                    doc_id, issuing_country, country, hs_code,
                                    tariff_type, tariff_rate, company, case_number,
                                    effective_date_from, effective_date_to,
                                    investigation_period_from, investigation_period_to,
                                    basis_law, product_description, note
                                )
                                SELECT
                                    doc_id, issuing_country, country, ?,
                                    tariff_type, tariff_rate, company, case_number,
                                    effective_date_from, effective_date_to,
                                    investigation_period_from, investigation_period_to,
                                    basis_law, product_description, note
                                FROM tariff_items
                                WHERE tariff_id = ?
                            """, (hs_code, tariff_id))
                            total_filled += 1
        
        self.db.conn.commit()
        return total_filled

    def process_folder(self, input_folder: str):
        """폴더의 모든 PDF 처리"""
        if not os.path.exists(input_folder):
            print(f"✗ Input folder not found: {input_folder}")
            return

        pdf_files = sorted(
            [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]
        )

        if not pdf_files:
            print(f"✗ No PDF files found in {input_folder}")
            return

        print(f"\n{'='*80}")
        print(f"Found {len(pdf_files)} PDF files")
        print(f"Mode: {self.mode.upper()}")
        print(f"{'='*80}")

        successful = 0
        failed = []

        for i, pdf_file in enumerate(pdf_files, 1):
            print(f"\n[{i}/{len(pdf_files)}]")
            pdf_path = os.path.join(input_folder, pdf_file)
            try:
                if self.process_single_pdf(pdf_path):
                    successful += 1
                else:
                    failed.append(pdf_file)
            except Exception as e:
                print(f"  ✗ Error processing {pdf_file}: {e}")
                failed.append(pdf_file)

        print(f"\n{'='*80}")
        print(f"Processing Complete")
        print(f"{'='*80}")
        print(f"Successfully processed: {successful}/{len(pdf_files)} files")
        if failed:
            print(f"\nFailed files:")
            for f in failed:
                print(f"  - {f}")


def main():
    """메인 실행"""
    parser = argparse.ArgumentParser(
        description='Tariff Information Extractor - Unified Version (OCR + Vision)'
    )
    parser.add_argument(
        '--input',
        default=INPUT_FOLDER,
        help=f'Input folder containing PDF files (default: {INPUT_FOLDER})'
    )
    parser.add_argument(
        '--file',
        type=str,
        default=None,
        help='Process only this specific PDF file'
    )
    parser.add_argument(
        '--mode',
        type=str,
        choices=['ocr', 'vision', 'hybrid'],
        default='hybrid',
        help='Processing mode: ocr (low cost), vision (high accuracy), or hybrid (auto fallback, default)'
    )

    args = parser.parse_args()

    print("="*80)
    print("Tariff Information Extractor - Unified Version")
    print("="*80)
    print(f"\nMode: {args.mode.upper()} (Incremental - skips existing data)")
    if args.mode == "ocr":
        print("  - Text Extraction + Cheap LLM Parsing")
        print("  - Cost: $2-5 per 143 pages (10-15x cheaper than Vision)")
    else:
        print("  - Vision API + High-Quality Image Processing")
        print("  - Cost: $50-80 per 143 pages (highest accuracy)")
    print("="*80)

    # DB 초기화
    db = TariffDatabase(DB_PATH)

    # Extractor 생성
    try:
        extractor = TariffExtractor(db, mode=args.mode)
    except ValueError as e:
        print(f"\n✗ Error: {e}")
        print("\nPlease set OPENAI_API_KEY in .env file")
        return

    # PDF 처리
    if args.file:
        pdf_path = os.path.join(args.input, args.file)
        if not os.path.exists(pdf_path):
            print(f"✗ File not found: {pdf_path}")
            return

        extractor.process_single_pdf(pdf_path)
    else:
        extractor.process_folder(args.input)

    # 통계 출력
    stats = db.get_stats()
    print(f"\n{'='*80}")
    print("Database Statistics")
    print(f"{'='*80}")
    print(f"Total documents: {stats['total_documents']}")
    print(f"Total tariff items: {stats['total_tariff_items']}")

    if stats.get('by_issuing_country'):
        print(f"\nBy issuing country:")
        for country, count in stats['by_issuing_country'].items():
            print(f"  {country}: {count} documents")

    print(f"\nDatabase: {DB_PATH}")
    print(f"{'='*80}")

    db.close()


if __name__ == "__main__":
    main()

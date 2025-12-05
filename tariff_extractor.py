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

        # 페이지 수
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()

        # documents 테이블에 기록
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

        # 기존 아이템 삭제 후 새로 삽입
        self.db.delete_tariff_items_by_doc(doc_id)

        for item in items:
            self.db.insert_tariff_item(doc_id, item, issuing_country)

        print(f"  ✓ Successfully processed: {len(items)} tariff items")

        # HS 코드 상속 (같은 case_number의 다른 문서에서)
        if issuing_country == "United States":
            inherited = self.inherit_hs_codes_for_usa(doc_id)
            if inherited > 0:
                print(f"  ✓ Inherited {inherited} HS codes from related documents")

        return True

    def inherit_hs_codes_for_usa(self, doc_id: int) -> int:
        """
        미국 문서: 같은 case_number를 가진 문서에서 HS 코드 상속

        예: USA_Plate_A-580-887_Pre_2023.pdf (HS 코드 없음)
            → USA_Plate_A-580-887_F_2022.pdf (HS 코드 있음)에서 복사
        """
        # 현재 문서에서 null인 HS 코드가 있는 case_number 찾기
        self.db.cursor.execute("""
            SELECT DISTINCT case_number
            FROM tariff_items
            WHERE doc_id = ?
              AND case_number IS NOT NULL
              AND hs_code IS NULL
        """, (doc_id,))

        case_numbers = [row['case_number'] for row in self.db.cursor.fetchall()]

        if not case_numbers:
            return 0

        total_inherited = 0

        for case_number in case_numbers:
            # 같은 case_number를 가진 다른 문서에서 HS 코드 찾기
            self.db.cursor.execute("""
                SELECT DISTINCT hs_code
                FROM tariff_items
                WHERE case_number = ?
                  AND hs_code IS NOT NULL
                  AND issuing_country = 'United States'
            """, (case_number,))

            hs_codes = [row['hs_code'] for row in self.db.cursor.fetchall()]

            if not hs_codes:
                continue

            # 현재 문서의 null HS 코드 항목들 가져오기
            self.db.cursor.execute("""
                SELECT tariff_id, country, company, tariff_rate
                FROM tariff_items
                WHERE doc_id = ?
                  AND case_number = ?
                  AND hs_code IS NULL
            """, (doc_id, case_number))

            null_items = self.db.cursor.fetchall()

            # 각 HS 코드에 대해 새로운 항목 생성
            for null_item in null_items:
                # 기존 null 항목 정보
                tariff_id = null_item['tariff_id']
                country = null_item['country']
                company = null_item['company']
                tariff_rate = null_item['tariff_rate']

                # 첫 번째 HS 코드로 기존 항목 업데이트
                if hs_codes:
                    self.db.cursor.execute("""
                        UPDATE tariff_items
                        SET hs_code = ?
                        WHERE tariff_id = ?
                    """, (hs_codes[0], tariff_id))
                    total_inherited += 1

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
                        total_inherited += 1

        self.db.conn.commit()
        return total_inherited

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
    parser.add_argument(
        '--reprocess',
        action='store_true',
        help='Delete existing data before reprocessing'
    )

    args = parser.parse_args()

    print("="*80)
    print("Tariff Information Extractor - Unified Version")
    print("="*80)
    print(f"\nMode: {args.mode.upper()}")
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

        # 재처리 옵션
        if args.reprocess:
            db.cursor.execute(
                "SELECT doc_id FROM documents WHERE file_name = ?",
                (args.file,)
            )
            result = db.cursor.fetchone()
            if result:
                doc_id = result[0]
                print(f"\n✓ Deleting existing data for {args.file}")
                db.delete_tariff_items_by_doc(doc_id)
                db.cursor.execute(
                    "DELETE FROM documents WHERE doc_id = ?",
                    (doc_id,)
                )
                db.conn.commit()

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

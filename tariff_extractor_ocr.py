"""
Tariff Information Extractor - OCR 버전 (저비용)

Vision API 대신 텍스트 추출 + 저렴한 LLM 파싱으로 비용 절감
- 143페이지 Vision: $50-80
- 143페이지 OCR: $2-5 (10-15배 저렴!)

Usage:
    python tariff_extractor_ocr.py
    python tariff_extractor_ocr.py --file=파일명.pdf
"""

import os
import argparse
import fitz  # PyMuPDF
from dotenv import load_dotenv
from openai import OpenAI
from typing import Dict, List

from database import TariffDatabase
from parsers import ParserFactory

# 환경 변수 로드
load_dotenv()

# 기본 설정
INPUT_FOLDER = "PDF"
DB_PATH = "tariff_data.db"

# OCR 설정
MAX_PAGES_PER_BATCH = 50  # 한 번에 처리할 최대 페이지 수
TEXT_MODEL = "gpt-4o-mini"  # 저렴한 텍스트 모델


# ============================================================================
# TARIFF EXTRACTOR (OCR 버전)
# ============================================================================

class TariffExtractorOCR:
    """OCR 기반 저비용 Tariff Extractor"""

    def __init__(self, db: TariffDatabase):
        self.db = db

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

        # 파일 정보
        file_size = os.path.getsize(pdf_path)

        # 파서 생성
        parser = ParserFactory.create_parser(file_name, self.client)

        # 텍스트 추출 + LLM 파싱
        print(f"  Extracting tariff information with OCR + LLM...")
        items = parser.process(pdf_path)

        if not items:
            print(f"  ⚠ No tariff items found")
            return False

        # 페이지 수
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()

        # documents 테이블에 기록
        doc_id = self.db.insert_document(
            file_name=file_name,
            file_path=pdf_path,
            issuing_country=issuing_country,
            total_pages=total_pages,
            file_size=file_size,
            processing_mode="ocr_text_llm"
        )

        if not doc_id:
            print(f"  ✗ Failed to insert document record")
            return False

        # 기존 아이템 삭제 후 새로 삽입
        self.db.delete_tariff_items_by_doc(doc_id)

        for item in items:
            self.db.insert_tariff_item(doc_id, item, issuing_country)

        print(f"  ✓ Successfully processed: {len(items)} tariff items")
        return True

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


# ============================================================================
# MAIN
# ============================================================================

def main():
    """메인 실행"""
    parser = argparse.ArgumentParser(
        description='Tariff Information Extractor - OCR Version (Low Cost)'
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
        '--reprocess',
        action='store_true',
        help='Delete existing data before reprocessing'
    )

    args = parser.parse_args()

    print("="*80)
    print("Tariff Information Extractor - OCR Version (Low Cost)")
    print("Text Extraction + Cheap LLM Parsing")
    print("="*80)
    print("\n💰 Cost savings:")
    print("  - Vision API: $50-80 per 143 pages")
    print("  - OCR + LLM: $2-5 per 143 pages (10-15x cheaper!)")
    print("="*80)

    # DB 초기화
    db = TariffDatabase(DB_PATH)

    # Extractor 생성
    try:
        extractor = TariffExtractorOCR(db)
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

"""
Tariff Information Extractor with Database Storage

This script provides two modes:
1. RAW mode: Extract PDF text page-by-page and store in database
2. JSON mode: Extract structured tariff information and store in database

Usage:
    python tariff_extractor.py --mode=raw     # Extract raw text
    python tariff_extractor.py --mode=json    # Extract tariff data (default)
    python tariff_extractor.py --mode=both    # Both modes
"""

import os
import json
import sqlite3
import argparse
import fitz  # PyMuPDF
from anthropic import Anthropic
from typing import Dict, List
from dotenv import load_dotenv
from PIL import Image
import io

# Try to import pytesseract
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    print("Warning: pytesseract not installed. OCR functionality will be disabled.")

# Load environment variables
load_dotenv()

# Configuration
INPUT_FOLDER = "PDF"
DB_PATH = "tariff_data.db"
MODEL_NAME = "claude-sonnet-4-5-20250929"  # Claude Sonnet 4.5


# ============================================================================
# COUNTRY NAME NORMALIZATION
# ============================================================================

COUNTRY_NORMALIZATION = {
    # Korean names
    '대한민국': 'Republic of Korea',
    '한국': 'Republic of Korea',
    'korea': 'Republic of Korea',
    'south korea': 'Republic of Korea',

    # Chinese names
    '중국': "People's Republic of China",
    '중화인민공화국': "People's Republic of China",
    'china': "People's Republic of China",
    'prc': "People's Republic of China",

    # Japanese names
    '일본': 'Japan',

    # US names
    '미국': 'United States',
    'usa': 'United States',
    'united states of america': 'United States',
    'u.s.': 'United States',
    'u.s.a.': 'United States',

    # European Union
    'eu': 'European Union',
    '유럽연합': 'European Union',

    # Taiwan
    '대만': 'Taiwan',
    'chinese taipei': 'Taiwan',

    # Other countries
    '베트남': 'Vietnam',
    '태국': 'Thailand',
    '인도': 'India',
    '러시아': 'Russian Federation',
    'russia': 'Russian Federation',
    '브라질': 'Brazil',
    '말레이시아': 'Malaysia',
    '이탈리아': 'Italy',
    '스페인': 'Spain',
}


def normalize_country_name(country: str) -> str:
    """Normalize country name to standard English name"""
    if not country:
        return None

    # Convert to lowercase for matching
    country_lower = country.strip().lower()

    # Check if it's in the mapping
    if country_lower in COUNTRY_NORMALIZATION:
        return COUNTRY_NORMALIZATION[country_lower]

    # Return original if already in standard form
    return country.strip()


# ============================================================================
# DATABASE MANAGEMENT
# ============================================================================

class TariffDatabase:
    """Database management for tariff data"""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        """Create database tables"""

        # Documents table - PDF metadata
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL UNIQUE,
                file_path TEXT NOT NULL,
                total_pages INTEGER,
                file_size INTEGER,
                processing_mode TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Pages table - Raw text content (RAW mode)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                page_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                raw_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
                UNIQUE(doc_id, page_number)
            )
        """)

        # Tariff items table - Structured tariff data (JSON mode)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tariff_items (
                tariff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                country TEXT,
                hs_code TEXT,
                tariff_type TEXT,
                tariff_rate REAL,
                effective_date_from TEXT,
                effective_date_to TEXT,
                basis_law TEXT,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
            )
        """)

        # Create indexes
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tariff_hs_code ON tariff_items(hs_code)
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tariff_country ON tariff_items(country)
        """)

        self.conn.commit()
        print(f"✓ Database initialized: {self.db_path}")

    def insert_document(self, file_name: str, file_path: str, total_pages: int,
                       file_size: int, processing_mode: str) -> int:
        """Insert or update document record"""
        try:
            self.cursor.execute("""
                INSERT INTO documents (file_name, file_path, total_pages, file_size, processing_mode)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_name) DO UPDATE SET
                    file_path = excluded.file_path,
                    total_pages = excluded.total_pages,
                    file_size = excluded.file_size,
                    processing_mode = excluded.processing_mode,
                    created_at = CURRENT_TIMESTAMP
            """, (file_name, file_path, total_pages, file_size, processing_mode))

            self.conn.commit()

            # Get the doc_id
            self.cursor.execute("SELECT doc_id FROM documents WHERE file_name = ?", (file_name,))
            return self.cursor.fetchone()['doc_id']

        except Exception as e:
            print(f"  ✗ Error inserting document: {e}")
            self.conn.rollback()
            return None

    def insert_page(self, doc_id: int, page_number: int, raw_text: str):
        """Insert page raw text"""
        try:
            self.cursor.execute("""
                INSERT OR REPLACE INTO pages (doc_id, page_number, raw_text)
                VALUES (?, ?, ?)
            """, (doc_id, page_number, raw_text))
            self.conn.commit()
        except Exception as e:
            print(f"  ✗ Error inserting page {page_number}: {e}")
            self.conn.rollback()

    def insert_tariff_item(self, doc_id: int, item: Dict):
        """Insert tariff item with normalized country name"""
        try:
            # Normalize country name before inserting
            country = normalize_country_name(item.get('country'))

            self.cursor.execute("""
                INSERT INTO tariff_items (
                    doc_id, country, hs_code, tariff_type, tariff_rate,
                    effective_date_from, effective_date_to, basis_law, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc_id,
                country,
                item.get('hs_code'),
                item.get('tariff_type'),
                item.get('tariff_rate'),
                item.get('effective_date_from'),
                item.get('effective_date_to'),
                item.get('basis_law'),
                item.get('note')
            ))
            self.conn.commit()
        except Exception as e:
            print(f"  ✗ Error inserting tariff item: {e}")
            self.conn.rollback()

    def delete_pages_by_doc(self, doc_id: int):
        """Delete all pages for a document"""
        self.cursor.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
        self.conn.commit()

    def delete_tariff_items_by_doc(self, doc_id: int):
        """Delete all tariff items for a document"""
        self.cursor.execute("DELETE FROM tariff_items WHERE doc_id = ?", (doc_id,))
        self.conn.commit()

    def get_stats(self) -> Dict:
        """Get database statistics"""
        stats = {}

        self.cursor.execute("SELECT COUNT(*) as count FROM documents")
        stats['total_documents'] = self.cursor.fetchone()['count']

        self.cursor.execute("SELECT COUNT(*) as count FROM pages")
        stats['total_pages'] = self.cursor.fetchone()['count']

        self.cursor.execute("SELECT COUNT(*) as count FROM tariff_items")
        stats['total_tariff_items'] = self.cursor.fetchone()['count']

        return stats

    def close(self):
        """Close database connection"""
        self.conn.close()


# ============================================================================
# PROMPT TEMPLATES
# ============================================================================

def create_raw_text_extraction_prompt(pdf_text: str) -> str:
    """Create prompt for raw text extraction with page markers"""
    return f"""당신의 역할:
- 당신은 PDF에서 **원문 텍스트를 손실 없이 추출**하는 도구입니다.
- 요약, 번역, 설명, 재구성, 추론을 하지 말고 **PDF에 있는 텍스트를 가능한 한 그대로 출력**해야 합니다.

출력 규칙:

1. **삭제 금지**
   - PDF 안에 있는 텍스트는 의미 없어 보여도 절대로 임의로 생략하지 마세요.
   - 헤더/푸터, 페이지 번호, 각주, 참고문헌, 표 제목 등도 모두 포함합니다.

2. **페이지 구분 표시**
   - 각 페이지의 시작은 반드시 다음 형식으로 표시합니다.
     - `==== PAGE {{페이지번호}} START ====`
     - `==== PAGE {{페이지번호}} END ====`
   - 예: 첫 페이지 → `==== PAGE 1 START ====`, `==== PAGE 1 END ====`

3. **순서 보존**
   - PDF에서 사람이 읽는 순서대로 텍스트를 배치합니다.
   - 같은 페이지 안에서는 위에서 아래, 왼쪽에서 오른쪽 순서를 최대한 유지합니다.

4. **표 구조**
   - 표는 가능한 한 행/열 구조가 드러나도록 출력합니다.
   - 기본 형식:
     - 헤더 행과 데이터 행을 줄 단위로 나누고, 열은 `\\t` 또는 `|` 로 구분하세요.
     - 예: `HS코드\\t품명\\t관세율`
   - 표 안의 줄바꿈도 최대한 보존합니다.

5. **숫자/기호 보존**
   - 퍼센트(%), 하이픈(-), 마이너스(-), 콤마(,), 소수점(.) 등은 원문 그대로 유지합니다.
   - `0%`, `0 %`, `0퍼센트`처럼 애매한 표현은 절대 바꾸지 말고 그대로 적으세요.

6. **언어/표현 변경 금지**
   - 한국어는 한국어 그대로, 영어는 영어 그대로 둡니다.
   - 문장을 다듬거나 맞춤법을 고치지 마세요.
   - 단위, 날짜 형식 등도 절대 바꾸지 말고 원문 그대로 적습니다.
     - 예: `2025. 1. 1.`는 그대로 `2025. 1. 1.`로 둡니다.

7. **추가 텍스트 금지**
   - "다음은 추출한 텍스트입니다." 같은 설명 문장을 절대 쓰지 마세요.
   - **PDF 내용 외의 텍스트는 한 글자도 추가하지 마세요.**

출력 형식:
- 전체 출력은 순수 텍스트만 포함해야 합니다.
- 마크다운 문법(#, *, ``` 등)을 사용하지 마세요.
- 그대로 복사해서 다른 프로그램에 넣었을 때 원문을 최대한 재현할 수 있어야 합니다.

[PDF 원문]
{pdf_text}
"""


def create_tariff_extraction_prompt(pdf_text: str) -> str:
    """Create prompt for tariff information extraction"""
    return f"""당신의 역할:
- 당신은 PDF에서 관세 공시 정보를 추출하는 모델이다.
- 아래 텍스트에서 관세 관련 정보를 찾아 JSON으로만 출력한다.

[추출해야 할 필드]

- country: 국가명 **영문 표준명으로 통일**
  - 대한민국/한국 → "Republic of Korea"
  - 중국 → "People's Republic of China"
  - 미국 → "United States"
  - 일본 → "Japan"
  - 대만 → "Taiwan"
  - 기타 국가도 영문 공식 명칭 사용
- hs_code: HS 코드만 추출. **반드시 숫자로만 구성되거나 점/하이픈으로 구분된 숫자**
  - 올바른 예: "7208.51", "7208.51-0000", "8517.12", "7210.49.11"
  - 잘못된 예: "A-580-878", "C-580-888" (이건 케이스 번호이므로 절대 hs_code에 넣지 말것)
- tariff_type: 관세 유형 (예: "기본세율", "협정세율", "FTA 세율", "잠정세율", "Antidumping", "Countervailing")
- tariff_rate: 관세율 숫자 (퍼센트 기호 제거, 예: 8.0, 0.0, 15.5)
- effective_date_from: 적용 시작일, YYYY-MM-DD (예: "2025-01-01")
- effective_date_to: 적용 종료일, 없으면 null
- basis_law: 공고명/법령명 (없으면 null)
- note: 기타 주석/예외조건 (케이스 번호가 있으면 여기에 기록, 예: "Case A-580-878")

[출력 형식]

아래 JSON 형식 **만** 출력하라. 다른 설명 문장은 절대 쓰지 말 것.

{{
  "items": [
    {{
      "country": string | null,
      "hs_code": string,
      "tariff_type": string | null,
      "tariff_rate": number | null,
      "effective_date_from": string | null,
      "effective_date_to": string | null,
      "basis_law": string | null,
      "note": string | null
    }}
  ]
}}

규칙:
1. 여러 HS 코드/여러 국가가 있으면 각 조합마다 별도의 item을 만든다.
2. "무관세", "0%" 등은 tariff_rate = 0.0 으로 한다.
3. "5~8%" 같이 범위면 tariff_rate는 null, note에 원문 그대로 쓴다.
4. "2025. 1. 1." 형태 날짜는 "2025-01-01"로 변환한다.
5. 필요한 정보가 없으면 "items": [] 를 반환한다.
6. **중요**: A-XXX-XXX, C-XXX-XXX 형태는 케이스 번호이므로 hs_code에 절대 넣지 말 것. note 필드에 기록할 것.
7. hs_code는 반드시 숫자로 시작해야 함 (7XXX, 8XXX 등).
8. JSON 이외의 텍스트는 아무것도 출력하지 말라.

[분석할 텍스트]

============ PDF_TEXT_START ============
{pdf_text}
============ PDF_TEXT_END ============
"""


# ============================================================================
# TARIFF EXTRACTOR
# ============================================================================

class TariffExtractor:
    """Extract tariff information from PDF documents"""

    def __init__(self, db: TariffDatabase, mode: str = "json"):
        """Initialize extractor"""
        self.db = db
        self.mode = mode

        # Initialize Anthropic client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment variables")

        self.client = Anthropic(api_key=api_key)

    def extract_pages_from_pdf(self, pdf_path: str) -> List[tuple]:
        """Extract text from PDF page by page, with OCR fallback for scanned PDFs"""
        try:
            doc = fitz.open(pdf_path)
            pages = []

            for page_num, page in enumerate(doc, start=1):
                # Try text extraction first
                page_text = page.get_text()

                # If no text found and OCR is available, try OCR
                if len(page_text.strip()) < 50 and TESSERACT_AVAILABLE:
                    print(f"    Page {page_num}: No text found, trying OCR...")
                    try:
                        # Render page to image
                        pix = page.get_pixmap(dpi=300)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                        # Perform OCR
                        ocr_text = pytesseract.image_to_string(img, lang='eng')
                        if len(ocr_text.strip()) > len(page_text.strip()):
                            page_text = ocr_text
                            print(f"    Page {page_num}: OCR extracted {len(ocr_text)} chars")
                    except Exception as e:
                        print(f"    Page {page_num}: OCR failed - {e}")

                pages.append((page_num, page_text))

            doc.close()
            return pages

        except Exception as e:
            print(f"  ✗ Error extracting PDF: {e}")
            return []

    def call_claude_api(self, prompt: str) -> str:
        """Call Claude API with prompt"""
        try:
            message = self.client.messages.create(
                model=MODEL_NAME,
                max_tokens=16000,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text.strip()

            # Remove code block markers if present
            if response_text.startswith("```"):
                lines = response_text.split('\n')
                lines = lines[1:]  # Remove ```json or ```
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]  # Remove closing ```
                response_text = '\n'.join(lines).strip()

            return response_text

        except Exception as e:
            print(f"  ✗ Claude API error: {e}")
            return ""

    def process_raw_mode(self, doc_id: int, pdf_path: str):
        """Process PDF in RAW mode - extract and store raw text"""
        print(f"  → Extracting raw text page by page...")

        pages = self.extract_pages_from_pdf(pdf_path)
        if not pages:
            print(f"  ✗ No pages extracted")
            return False

        # Combine all pages for Claude to process
        full_text = "\n\n".join([f"==== PAGE {num} ====\n{text}"
                                  for num, text in pages])

        # Call Claude to format the text properly
        prompt = create_raw_text_extraction_prompt(full_text)
        formatted_text = self.call_claude_api(prompt)

        if not formatted_text:
            print(f"  ✗ No response from Claude API")
            return False

        # Parse the formatted text and split by pages
        page_texts = self.split_formatted_text_by_pages(formatted_text)

        # Store each page in database
        self.db.delete_pages_by_doc(doc_id)

        for page_num, page_text in page_texts.items():
            self.db.insert_page(doc_id, page_num, page_text)

        print(f"  ✓ Stored {len(page_texts)} pages in database")
        return True

    def split_formatted_text_by_pages(self, formatted_text: str) -> Dict[int, str]:
        """Split formatted text into individual pages"""
        import re

        pages = {}
        pattern = r'==== PAGE (\d+) START ====\s*(.*?)\s*==== PAGE \1 END ===='

        matches = re.finditer(pattern, formatted_text, re.DOTALL)

        for match in matches:
            page_num = int(match.group(1))
            page_text = match.group(2).strip()
            pages[page_num] = page_text

        # If no matches, store as single page
        if not pages:
            pages[1] = formatted_text

        return pages

    def process_json_mode(self, doc_id: int, pdf_path: str):
        """Process PDF in JSON mode - extract structured tariff data"""
        print(f"  → Extracting tariff information...")

        pages = self.extract_pages_from_pdf(pdf_path)
        if not pages:
            print(f"  ✗ No pages extracted")
            return False

        # Combine all pages
        full_text = "\n\n".join([text for _, text in pages])

        # Call Claude to extract tariff data
        prompt = create_tariff_extraction_prompt(full_text)
        response = self.call_claude_api(prompt)

        if not response:
            print(f"  ✗ No response from Claude API")
            return False

        # Parse JSON response
        try:
            data = json.loads(response)
            items = data.get('items', [])

            if not items:
                print(f"  ⚠ No tariff items found")
                return True

            # Store in database
            self.db.delete_tariff_items_by_doc(doc_id)

            for item in items:
                self.db.insert_tariff_item(doc_id, item)

            print(f"  ✓ Stored {len(items)} tariff items in database")
            return True

        except json.JSONDecodeError as e:
            print(f"  ✗ JSON parsing error: {e}")
            print(f"  Response: {response[:500]}")
            return False

    def process_single_pdf(self, pdf_path: str):
        """Process a single PDF file"""
        file_name = os.path.basename(pdf_path)
        print(f"\nProcessing: {file_name}")

        # Get file info
        file_size = os.path.getsize(pdf_path)
        pages = self.extract_pages_from_pdf(pdf_path)
        total_pages = len(pages)

        print(f"  • Pages: {total_pages}")
        print(f"  • Size: {file_size / 1024:.1f} KB")
        print(f"  • Mode: {self.mode.upper()}")

        # Insert/update document record
        doc_id = self.db.insert_document(
            file_name=file_name,
            file_path=pdf_path,
            total_pages=total_pages,
            file_size=file_size,
            processing_mode=self.mode
        )

        if not doc_id:
            print(f"  ✗ Failed to insert document record")
            return False

        # Process based on mode
        success = False

        if self.mode == "raw":
            success = self.process_raw_mode(doc_id, pdf_path)
        elif self.mode == "json":
            success = self.process_json_mode(doc_id, pdf_path)
        elif self.mode == "both":
            success_raw = self.process_raw_mode(doc_id, pdf_path)
            success_json = self.process_json_mode(doc_id, pdf_path)
            success = success_raw or success_json

        if success:
            print(f"  ✓ Successfully processed")
        else:
            print(f"  ✗ Processing failed")

        return success

    def process_folder(self, input_folder: str):
        """Process all PDF files in folder"""
        if not os.path.exists(input_folder):
            print(f"✗ Input folder not found: {input_folder}")
            return

        pdf_files = [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]

        if not pdf_files:
            print(f"✗ No PDF files found in {input_folder}")
            return

        print(f"\n{'='*60}")
        print(f"Processing {len(pdf_files)} PDF files")
        print(f"Mode: {self.mode.upper()}")
        print(f"{'='*60}")

        successful = 0
        for pdf_file in pdf_files:
            pdf_path = os.path.join(input_folder, pdf_file)
            if self.process_single_pdf(pdf_path):
                successful += 1

        print(f"\n{'='*60}")
        print(f"Processing Complete")
        print(f"Successfully processed: {successful}/{len(pdf_files)} files")
        print(f"{'='*60}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main execution"""
    parser = argparse.ArgumentParser(description='Tariff Information Extractor')
    parser.add_argument('--mode', choices=['raw', 'json', 'both'], default='json',
                       help='Processing mode: raw (text extraction), json (tariff data), both')
    parser.add_argument('--input', default=INPUT_FOLDER,
                       help=f'Input folder containing PDF files (default: {INPUT_FOLDER})')

    args = parser.parse_args()

    print("="*60)
    print("Tariff Information Extractor")
    print("="*60)

    # Initialize database
    db = TariffDatabase(DB_PATH)

    # Create extractor
    try:
        extractor = TariffExtractor(db, mode=args.mode)
    except ValueError as e:
        print(f"\n✗ Error: {e}")
        print("\nPlease set ANTHROPIC_API_KEY in .env file:")
        print("  ANTHROPIC_API_KEY=your_api_key_here")
        return

    # Process PDFs
    extractor.process_folder(args.input)

    # Show statistics
    stats = db.get_stats()
    print(f"\n{'='*60}")
    print("Database Statistics")
    print(f"{'='*60}")
    print(f"Total documents: {stats['total_documents']}")
    print(f"Total pages: {stats['total_pages']}")
    print(f"Total tariff items: {stats['total_tariff_items']}")
    print(f"\nDatabase: {DB_PATH}")
    print(f"{'='*60}")

    # Close database
    db.close()


if __name__ == "__main__":
    main()

"""
USA Tariff Parser
미국 관세 정보 파서 - OCR + Vision API 하이브리드 버전
"""

import re
from typing import Dict, List
from .default_parser import DefaultTextParser
from .base_parser import VisionBasedParser


def validate_usa_hs_code(hs_code) -> str:
    """
    미국 철강 제품 HS 코드 검증
    - 72XX, 73XX로 시작하는 코드만 유효
    - 텍스트나 잘못된 형식은 null 처리
    """
    if not hs_code or hs_code == "null":
        return None

    hs_code_str = str(hs_code).strip()

    # 알파벳이 포함되어 있으면 무효 (CORE, Truck and Bus 등)
    if re.search(r'[a-zA-Z]', hs_code_str):
        return None

    # 72 또는 73으로 시작하지 않으면 무효
    if not re.match(r'^7[23]', hs_code_str):
        return None

    # 유효한 형식인지 확인: XXXX.XX.XX 또는 XXXX.XX.XXXX
    if not re.match(r'^\d{4}\.\d{2}\.?\d{0,4}$', hs_code_str):
        return None

    return hs_code_str


# ============================================================================
# OCR 기반 미국 파서
# ============================================================================
class USATextParser(DefaultTextParser):
    """미국 특화 텍스트 파서"""

    def extract_hs_codes_from_pdf(self, pdf_path: str) -> set:
        """PDF에서 모든 HS Code를 직접 추출 (72XX, 73XX로 시작하는 것만)"""
        import fitz
        all_hs_codes = set()
        
        try:
            doc = fitz.open(pdf_path)
            for page in doc:
                text = page.get_text()
                # 72XX 또는 73XX로 시작하는 HS 코드 찾기
                hs_codes = re.findall(r'7[23]\d{2}\.\d{2}\.\d{2,4}', text)
                all_hs_codes.update(hs_codes)
            doc.close()
        except Exception as e:
            print(f"    ⚠ Error extracting HS codes from PDF: {e}")
        
        return all_hs_codes

    def extract_case_number_from_filename(self, pdf_path: str) -> str:
        """파일명에서 Case Number 추출 (A-XXX-XXX 또는 C-XXX-XXX)"""
        import os
        filename = os.path.basename(pdf_path)
        # A-580-881 또는 C-580-888 형태 찾기
        match = re.search(r'([AC]-\d{3}-\d{3})', filename)
        if match:
            return match.group(1)
        return None

    def extract_case_section(self, text: str, case_number: str) -> str:
        """텍스트에서 특정 Case Number 섹션만 추출"""
        if not case_number:
            return text
        
        # Case Number 패턴: A-580-881 등
        pattern = re.escape(case_number)
        
        # Case Number가 나타나는 위치 찾기
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            print(f"    ⚠ Case number {case_number} not found in text")
            return text
        
        # 해당 Case Number부터 시작
        start_pos = match.start()
        section_text = text[start_pos:]
        
        # 다음 다른 Case Number가 나타나면 거기까지만 추출
        # A-XXX-XXX 또는 C-XXX-XXX 형태의 다른 케이스 번호 찾기
        next_case_pattern = r'[AC]-\d{3}-\d{3}'
        for next_match in re.finditer(next_case_pattern, section_text[20:]):  # 처음 20자 이후부터 검색
            next_case = next_match.group()
            if next_case != case_number:
                end_pos = next_match.start() + 20
                section_text = section_text[:end_pos]
                print(f"    📑 Extracted section for {case_number} ({len(section_text):,} chars)")
                break
        
        return section_text

    def process(self, pdf_path: str) -> List[Dict]:
        """
        PDF 처리 후 모든 HS Code × 국가/회사 조합을 강제 생성
        """
        # 0. 파일명에서 Case Number 추출
        target_case_number = self.extract_case_number_from_filename(pdf_path)
        if target_case_number:
            print(f"  🔍 Target case number: {target_case_number}")
        
        # 1. PDF에서 모든 HS Code 직접 추출
        all_hs_codes = self.extract_hs_codes_from_pdf(pdf_path)
        print(f"  📊 Found {len(all_hs_codes)} unique HS codes in PDF")
        
        # 2. 기본 파서로 LLM 추출 실행
        items = super().process(pdf_path)
        
        if not items:
            return items
        
        # 3. PDF에서 직접 추출한 HS Code만 사용 (LLM 생성 HS Code는 무시)
        # PDF에 HTSUS 섹션이 없으면 HS Code 없이 회사 정보만 저장
        if not all_hs_codes:
            print(f"  📊 No HS codes in PDF, setting hs_code to null for all {len(items)} items")
            # HS 코드를 null로 설정
            for item in items:
                item['hs_code'] = None
            return self._deduplicate_items(items)
        
        # 5. 국가/회사별 정보 수집
        country_company_info = {}
        for item in items:
            country = item.get('country')
            company = item.get('company')
            
            if not country:
                continue
            
            key = (country, company)
            if key not in country_company_info:
                country_company_info[key] = {
                    'tariff_rate': item.get('tariff_rate'),
                    'tariff_type': item.get('tariff_type'),
                    'effective_date_from': item.get('effective_date_from'),
                    'effective_date_to': item.get('effective_date_to'),
                    'investigation_period_from': item.get('investigation_period_from'),
                    'investigation_period_to': item.get('investigation_period_to'),
                    'basis_law': item.get('basis_law'),
                    'case_number': item.get('case_number'),
                    'product_description': item.get('product_description'),
                    'note': item.get('note'),
                }
        
        print(f"  📊 Found {len(country_company_info)} unique country/company combinations")
        
        # 6. Cartesian product 생성: 모든 HS Code × 모든 국가/회사
        complete_items = []
        for hs_code in sorted(all_hs_codes):
            for (country, company), info in country_company_info.items():
                complete_items.append({
                    'country': country,
                    'company': company,
                    'hs_code': hs_code,
                    'tariff_type': info.get('tariff_type'),
                    'tariff_rate': info.get('tariff_rate'),
                    'effective_date_from': info.get('effective_date_from'),
                    'effective_date_to': info.get('effective_date_to'),
                    'investigation_period_from': info.get('investigation_period_from'),
                    'investigation_period_to': info.get('investigation_period_to'),
                    'basis_law': info.get('basis_law'),
                    'case_number': info.get('case_number'),
                    'product_description': info.get('product_description'),
                    'note': info.get('note'),
                })
        
        expected_count = len(all_hs_codes) * len(country_company_info)
        print(f"  ✓ Generated {len(complete_items)} items ({len(all_hs_codes)} HS codes × {len(country_company_info)} country/company = {expected_count})")
        
        return complete_items

    def _deduplicate_items(self, items: List[Dict]) -> List[Dict]:
        """중복 제거"""
        seen = set()
        unique_items = []
        for item in items:
            # 중복 판단 키: hs_code, country, company, tariff_rate
            key = (
                item.get('hs_code'),
                item.get('country'),
                item.get('company'),
                item.get('tariff_rate')
            )
            if key not in seen:
                seen.add(key)
                unique_items.append(item)
        
        if len(items) != len(unique_items):
            print(f"    ✓ Removed {len(items) - len(unique_items)} duplicate items")
        
        return unique_items

    def parse_response(self, response: str) -> List[Dict]:
        """JSON 파싱 + HS 코드 검증 + 중복 제거"""
        items = super().parse_response(response)

        # HS 코드 검증 및 정리
        invalid_count = 0
        for item in items:
            if 'hs_code' in item:
                original_hs = item['hs_code']
                validated_hs = validate_usa_hs_code(original_hs)
                if original_hs != validated_hs:
                    print(f"    ⚠ Invalid HS code filtered: '{original_hs}' → null")
                    invalid_count += 1
                item['hs_code'] = validated_hs

        if invalid_count > 0:
            print(f"    ✓ Filtered {invalid_count} invalid HS codes")

        return self._deduplicate_items(items)

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the US document text.

**CRITICAL INSTRUCTIONS:**

**DOCUMENT LAYOUT:**
- US documents have 3 columns, read from LEFT to RIGHT
- Within each column, read from TOP to BOTTOM
- Read Column 1 (leftmost) completely, then Column 2 (middle), then Column 3 (rightmost)

0. **IGNORE FOOTNOTES - VERY IMPORTANT:**
   - DO NOT read or extract data from footnotes
   - Footnotes are small text at the bottom of pages, often numbered (1, 2, 3...) or with symbols
   - ONLY read the main body text and tables
   - If a footnote contains company names, dates, or rates, IGNORE them

1. **CASE NUMBER SECTION PARSING - VERY IMPORTANT:**
   - The document may contain MULTIPLE case number sections
   - Parse ONLY the section that matches the case number you are looking for
   - Case numbers are in format: A-XXX-XXX or C-XXX-XXX (e.g., A-580-881, C-580-888)
   - Read from where the matching case number appears until the NEXT different case number begins
   - If case number A-580-881 is specified, read ONLY that section, NOT A-580-872 or others

2. **EXPORTER/MANUFACTURER TABLE - EXTRACT ALL COMPANIES INCLUDING "ALL OTHERS":**
   - Look for "Exporter/Manufacturer" or "Cash Deposit Rate" table
   - **YOU MUST EXTRACT EVERY SINGLE ROW including "All Others"**
   - **"All Others" IS A COMPANY - ALWAYS INCLUDE IT WITH ITS RATE**
   - Example table:
     | Exporter/Manufacturer | Rate |
     | Hyundai Steel | 5.00% |
     | POSCO | 7.50% |
     | **All Others** | **10.00%** | ← MUST EXTRACT THIS ROW!
   - Create a SEPARATE item for EACH company including "All Others"

3. **HS CODE EXTRACTION - VERY IMPORTANT:**
   - Find "Harmonized Tariff Schedule of the United States (HTSUS)" section
   - Extract ALL HS codes in format XXXX.XX.XXXX (e.g., 7210.49.0030, 7210.61.0000)
   - **HS codes MUST start with 72XX or 73XX for steel products**
   - Extract EVERY HS code listed, there may be 5-20+ HS codes
   - DO NOT extract codes starting with 25, 38, 21, etc.

4. **HS CODE × COMPANY MAPPING - CRITICAL:**
   - Each HS code applies to ALL companies in that section
   - If you find 10 HS codes and 3 companies (including All Others)
   - You should create 10 × 3 = 30 items total
   - Each item has ONE hs_code and ONE company

5. **HS Code vs Case Number - DO NOT CONFUSE:**
   - HS codes are NUMERIC ONLY: XXXX.XX.XXXX (e.g., 7210.49.0030)
   - Case numbers have LETTERS: A-XXX-XXX or C-XXX-XXX
   - **NEVER put case numbers in the hs_code field**

6. **Effective Date Extraction:**
   - Look for "Effective Date" or "Date: Effective ~"
   - Format as YYYY-MM-DD

OUTPUT JSON FORMAT:

{
  "items": [
    {
      "country": "Single country name ONLY",
      "hs_code": "Single HS code (XXXX.XX.XXXX) or null",
      "tariff_type": "Antidumping or Countervailing",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": null,
      "investigation_period_from": null,
      "investigation_period_to": null,
      "basis_law": "Legal basis",
      "company": "Company name (including 'All Others')",
      "case_number": "A-XXX-XXX or C-XXX-XXX",
      "product_description": "Product description",
      "note": "Final Results or Preliminary Results"
    }
  ]
}

**CHECKLIST BEFORE OUTPUT:**
- [ ] Did I extract ALL HS codes starting with 72XX or 73XX?
- [ ] Did I extract ALL companies including "All Others"?
- [ ] Did I create items for every HS code × company combination?

Output ONLY JSON.
"""


# ============================================================================
# Vision 기반 미국 파서
# ============================================================================
class USAVisionParser(VisionBasedParser):
    """미국 특화 Vision API 파서"""

    def parse_response(self, response: str) -> List[Dict]:
        """JSON 파싱 + HS 코드 검증"""
        items = super().parse_response(response)

        # HS 코드 검증 및 정리
        invalid_count = 0
        for item in items:
            if 'hs_code' in item:
                original_hs = item['hs_code']
                validated_hs = validate_usa_hs_code(original_hs)
                if original_hs != validated_hs:
                    print(f"    ⚠ Invalid HS code filtered: '{original_hs}' → null")
                    invalid_count += 1
                item['hs_code'] = validated_hs

        if invalid_count > 0:
            print(f"    ✓ Filtered {invalid_count} invalid HS codes")

        return items

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the US document images.

**CRITICAL INSTRUCTIONS:**

**DOCUMENT LAYOUT:**
- US documents have 3 columns, read from LEFT to RIGHT
- Within each column, read from TOP to BOTTOM
- Read Column 1 (leftmost) completely, then Column 2 (middle), then Column 3 (rightmost)

0. **IGNORE FOOTNOTES - VERY IMPORTANT:**
   - DO NOT read or extract data from footnotes
   - Footnotes are small text at the bottom of pages, often numbered (1, 2, 3...) or with symbols
   - ONLY read the main body text and tables
   - If a footnote contains company names, dates, or rates, IGNORE them

1. **DEPARTMENT OF COMMERCE Section Parsing:**
   - Read from where "DEPARTMENT OF COMMERCE" title appears until the next "DEPARTMENT OF COMMERCE"
   - Check if the section is "Final Results" or "Preliminary Results" after "DEPARTMENT OF COMMERCE"
   - Add "Final Results" or "Preliminary Results" to the note field

2. **Effective Date Extraction:**
   - Look for pattern "Date : Effective ~" or similar
   - The date after this pattern is the tariff effective start date (effective_date_from)
   - Format as YYYY-MM-DD

3. **Cash Deposit Rate:**
   - If "Cash Deposit Rate" is mentioned in the document, add it to the note field

4. **HS Code Extraction - VERY IMPORTANT:**
   - Some documents may NOT contain HS Code information
   - HS codes appear with "Harmonized Tariff Schedule of the United States (HTSUS)"
   - HS code format: XXXX.XX.XXXX or XXXX.XX.XX (e.g., 7210.49.0000, 7212.30.00)
   - **HS codes for steel products MUST start with 72XX or 73XX**
   - **ONLY extract HS codes starting with 72 or 73**
   - **DO NOT extract codes starting with 25, 38, 21, or other numbers**
   - Look carefully in tables and text for numeric HS codes starting with 72 or 73
   - If no HTSUS or valid HS code (72XX or 73XX) is found, set hs_code to null
   - Valid examples: "7210.49.00", "7212.30.00", "7209.15.0000"
   - Invalid examples: "2504.10.5000", "3801.10.5000", "21010"

5. **HS Code vs Case Number - DO NOT CONFUSE:**
   - HS codes are NUMERIC ONLY: XXXX.XX.XX or XXXX.XX (e.g., 7210.49.00, 7212.30.00)
   - Case numbers have LETTERS: A-XXX-XXX or C-XXX-XXX (e.g., A-580-878, C-580-888)
   - **NEVER put case numbers in the hs_code field**
   - Case numbers go in the "case_number" field ONLY
   - HS codes go in the "hs_code" field ONLY

6. **Court Number vs Case Number - CRITICAL:**
   - **Court Numbers (e.g., 22-00122, Court No. 23-XXXXX) are NOT case numbers**
   - **ONLY extract case numbers in format A-XXX-XXX or C-XXX-XXX**
   - Case numbers start with A (Antidumping) or C (Countervailing)
   - If you see "Court No." or numbers starting with digits (22-XXXXX), DO NOT extract as case_number
   - Example: "Court No. 22-00122" → case_number should be null (not a case number)

7. **HS Code Separation - MANDATORY:**
   - If multiple HS codes are listed, create SEPARATE items for EACH HS code
   - DO NOT combine multiple HS codes into one item

8. **Country Separation - MANDATORY:**
   - If multiple countries are listed, create SEPARATE items for EACH country
   - DO NOT combine multiple countries into one item

9. **Company Handling:**
   - If multiple companies are listed, create separate items for each company

10. **US-Specific Data:**
   - Extract case numbers (e.g., A-580-878, C-580-879) → put in "case_number" field
   - Extract investigation periods
   - Extract company-specific rates

OUTPUT JSON FORMAT:

{
  "items": [
    {
      "country": "Single country name ONLY",
      "hs_code": "Single HS code in numeric format (e.g., 7210.49.00) or null",
      "tariff_type": "Antidumping or Countervailing or Safeguard",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": "YYYY-MM-DD or null",
      "investigation_period_to": "YYYY-MM-DD or null",
      "basis_law": "Legal basis",
      "company": "Company name or null",
      "case_number": "Case number (e.g., A-580-878) or null",
      "product_description": "Product description",
      "note": "Notes or null"
    }
  ]
}

**REMEMBER:**
- Extract NUMERIC HS codes (XXXX.XX.XX), NOT product descriptions
- ONE hs_code per item
- ONE country per item
- Create ALL combinations: each HS code × each country × each company
- Use ONLY information visible in the images
- Output ONLY JSON, no explanatory text.
"""


# ============================================================================
# 하이브리드 파서 (텍스트 → 실패 시 Vision 폴백)
# ============================================================================
class USAHybridParser(DefaultTextParser):
    """미국 문서: 텍스트 파서 먼저 → 실패 시 Vision 폴백"""

    def __init__(self, client):
        super().__init__(client)
        self._vision = USAVisionParser(client)

    def parse_response(self, response: str) -> List[Dict]:
        """JSON 파싱 + HS 코드 검증"""
        items = super().parse_response(response)

        # HS 코드 검증 및 정리
        invalid_count = 0
        for item in items:
            if 'hs_code' in item:
                original_hs = item['hs_code']
                validated_hs = validate_usa_hs_code(original_hs)
                if original_hs != validated_hs:
                    print(f"    ⚠ Invalid HS code filtered: '{original_hs}' → null")
                    invalid_count += 1
                item['hs_code'] = validated_hs

        if invalid_count > 0:
            print(f"    ✓ Filtered {invalid_count} invalid HS codes")

        return items

    def process(self, pdf_path: str):
        print("  [Hybrid] Trying TEXT parser first...")
        try:
            text_items = super().process(pdf_path)
        except Exception as e:
            print(f"  ✗ TEXT parser crashed: {e}")
            text_items = []

        # 텍스트 파서 성공 시 그대로 반환
        if text_items:
            print(f"  ✓ TEXT parser success: {len(text_items)} items")
            return text_items

        # 실패 시 Vision 폴백
        print("  ⚠ TEXT parser failed → Switching to VISION parser...")
        try:
            vision_items = self._vision.process(pdf_path)
            print(f"  ✓ VISION parser success: {len(vision_items)} items")
            return vision_items
        except Exception as e:
            print(f"  ✗ Vision parser also failed: {e}")
            return []


# ============================================================================
# 외부에서 불러올 때 기본값: 하이브리드 파서
# ============================================================================
USAParser = USAHybridParser

"""
Australia Tariff Parser
호주 관세 정보 파서 - OCR 및 Vision API 버전
"""

import re
from typing import Dict, List
from .default_parser import DefaultTextParser, extract_text_from_pdf
from .base_parser import VisionBasedParser


# ============================================================================
# OCR (텍스트 추출) 버전
# ============================================================================

class AustraliaTextParser(DefaultTextParser):
    """호주 특화 파서 - OCR 버전 (MEASURES 섹션만 사용, 음수 비율 제거)"""

    def extract_measures_section(self, text: str) -> str:
        """10 MEASURES 섹션만 추출"""
        # "10 MEASURES" 또는 유사한 패턴 찾기 (숫자와 MEASURES 사이에 공백/점 가능)
        patterns = [
            r'10\s+MEASURES',
            r'10\.\s*MEASURES',
            r'10\s*\.\s*MEASURES',
            r'MEASURES\s+10\.1',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                measures_text = text[match.start():]
                # 너무 길면 자르기 (30000자 제한)
                if len(measures_text) > 30000:
                    measures_text = measures_text[:30000]
                print(f"    📝 Extracted MEASURES section ({len(measures_text):,} chars)")
                return measures_text
        
        print(f"    ⚠ MEASURES section not found, using last 30000 chars")
        return text[-30000:]  # 마지막 부분 사용

    def extract_hs_codes_from_section_34(self, text: str) -> List[str]:
        """3.4 Tariff Classification 섹션에서 8자리 HS Code 추출"""
        hs_codes = []
        
        # 8자리 HS 코드 패턴: XXXX.XX.XX
        pattern = r'\b(\d{4}\.\d{2}\.\d{2})\b'
        matches = re.findall(pattern, text)
        
        for code in matches:
            # 72XX 또는 73XX로 시작하는 철강 관련 코드만
            if code.startswith('72') or code.startswith('73'):
                if code not in hs_codes:
                    hs_codes.append(code)
        
        if hs_codes:
            print(f"    📝 Found {len(hs_codes)} unique HS codes: {hs_codes[:5]}...")
        
        return hs_codes

    def post_process_items(self, items: List[Dict]) -> List[Dict]:
        """후처리: 음수 비율 제거, HS Code 형식 검증"""
        processed = []
        negative_removed = 0
        invalid_hs_removed = 0
        
        for item in items:
            # 1. 음수 비율 제거
            rate = item.get('tariff_rate')
            if rate is not None:
                try:
                    rate_float = float(rate)
                    if rate_float < 0:
                        negative_removed += 1
                        continue  # 음수 비율은 건너뛰기
                except (ValueError, TypeError):
                    pass
            
            # 2. HS Code 형식 검증 (XXXX.XX.XX)
            hs_code = item.get('hs_code')
            if hs_code:
                hs_str = str(hs_code)
                # 8자리 형식 검증
                if not re.match(r'^\d{4}\.\d{2}\.\d{2}$', hs_str):
                    invalid_hs_removed += 1
                    continue  # 잘못된 형식은 건너뛰기
            
            processed.append(item)
        
        if negative_removed > 0:
            print(f"    ✓ Removed {negative_removed} items with negative rates")
        if invalid_hs_removed > 0:
            print(f"    ✓ Removed {invalid_hs_removed} items with invalid HS codes")
        
        return processed

    def process(self, pdf_path: str) -> List[Dict]:
        """PDF 처리: MEASURES 섹션만 추출 후 파싱"""
        # 1. 텍스트 추출
        text = extract_text_from_pdf(pdf_path)
        
        if not text or len(text) < 100:
            print(f"  💡 Text extraction failed, switching to Vision API")
            return self.process_image_pdf_with_vision(pdf_path)
        
        # 2. 전체 텍스트에서 HS Code 먼저 추출 (섹션 3.4에서)
        all_hs_codes = self.extract_hs_codes_from_section_34(text)
        
        # 3. MEASURES 섹션만 추출
        measures_text = self.extract_measures_section(text)
        
        # 4. LLM으로 파싱
        prompt = self.create_extraction_prompt()
        
        # HS Code 정보를 프롬프트에 추가
        if all_hs_codes:
            hs_list = ", ".join(all_hs_codes[:20])  # 최대 20개
            prompt += f"\n\n**EXTRACTED HS CODES (apply to all companies):**\n{hs_list}"
        
        print(f"  ▶ Processing MEASURES section ({len(measures_text):,} chars)...")
        response = self.parse_text_with_llm(measures_text, prompt)
        items = self.parse_response(response)
        
        # 5. 후처리 (음수 비율 제거)
        processed_items = self.post_process_items(items)
        
        # 6. HS Code × Company 조합 생성
        final_items = self.expand_hs_codes(processed_items, all_hs_codes)
        
        print(f"  ➜ Final items after HS code expansion: {len(final_items)}")
        return final_items

    def expand_hs_codes(self, items: List[Dict], hs_codes: List[str]) -> List[Dict]:
        """추출된 HS Code를 모든 회사에 적용하여 조합 생성"""
        if not hs_codes:
            return items
        
        expanded = []
        unique_companies = {}  # (country, company, rate) -> item template
        
        # 고유한 회사/국가/비율 조합 추출
        for item in items:
            key = (item.get('country'), item.get('company'), item.get('tariff_rate'))
            if key not in unique_companies:
                unique_companies[key] = item.copy()
        
        # 각 HS Code × 각 회사 조합 생성
        for hs_code in hs_codes:
            for key, template in unique_companies.items():
                new_item = template.copy()
                new_item['hs_code'] = hs_code
                expanded.append(new_item)
        
        print(f"    📊 Expanded: {len(unique_companies)} companies × {len(hs_codes)} HS codes = {len(expanded)} items")
        return expanded

    def create_extraction_prompt(self) -> str:
        """호주 관세 문서에 특화된 프롬프트"""
        return """Extract tariff/trade remedy information from the Australian Anti-Dumping MEASURES section.

**YOU ARE READING THE "10. MEASURES" SECTION ONLY.**

This section contains the FINAL anti-dumping duty rates. Extract:

1. **Company names** and their **tariff rates** (percentages)
2. **Countries** associated with each company
3. Apply the provided HS codes to ALL companies

**IMPORTANT RULES:**
- ONLY extract POSITIVE tariff rates (skip negative rates)
- Use the HS codes provided at the end of this prompt
- Create one item per (HS code × company) combination

**OUTPUT FORMAT:**

{
  "items": [
    {
      "country": "Country name (e.g., China, Korea, Taiwan)",
      "hs_code": "Use HS codes from the list provided",
      "tariff_type": "Antidumping",
      "tariff_rate": positive number ONLY,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": null,
      "investigation_period_from": null,
      "investigation_period_to": null,
      "basis_law": "Customs Act 1901",
      "company": "Company name",
      "case_number": "REP/ADN number",
      "product_description": "Steel products",
      "note": null
    }
  ]
}

Output ONLY valid JSON.
"""


# ============================================================================
# Vision API 버전
# ============================================================================

class AustraliaVisionParser(VisionBasedParser):
    """호주 특화 파서 - Vision API 버전"""

    def create_extraction_prompt(self) -> str:
        """호주 관세 문서에 특화된 프롬프트 (Vision)"""
        return """Extract tariff/trade remedy information from the Australian document images.

**CRITICAL INSTRUCTIONS:**

1. **HS Code Table Extraction - EXTREMELY IMPORTANT:**
   - Australian documents contain HS code tables that may span 10-20 pages
   - CAREFULLY examine ALL pages for tables containing HS codes
   - Tables have columns: "Tariff subheading", "Statistical code", "Description"
   - In the "Tariff subheading" column, there are:
     * Headers (4-digit): 7210, 7212, 7225, 7226 - NOT HS codes
     * Sub-headers (6-digit): 7210.4, 7225.9, 7226.9 - NOT HS codes
     * Actual HS codes (8-digit): 7210.49.00, 7212.30.00, 7225.92.00, 7226.99.00 - THESE ARE HS CODES!
   - Extract EVERY SINGLE 8-digit HS code (XXXX.XX.XX format) across all pages
   - DO NOT extract headers or sub-headers
   - DO NOT miss any 8-digit HS codes from any page

2. **HS Code Validation - VERY IMPORTANT:**
   - ONLY extract 8-digit HS codes in format XXXX.XX.XX (e.g., 7210.49.00)
   - DO NOT extract 4-digit headers like "7210", "7212", "7225", "7226"
   - DO NOT extract 6-digit sub-headers like "7210.4", "7225.9", "7226.9"
   - DO NOT extract 2-digit numbers from "Statistical code" column like "55", "56", "57", "58", "61", "38", "71"
   - Statistical codes are in a SEPARATE column and are NOT HS codes
   - Verify each HS code has EXACTLY the format XXXX.XX.XX before including it
   - If a section references goods but no 8-digit HS code is shown, set hs_code to null

3. **Complete Combinations - MANDATORY:**
   - For EACH HS code found in the tables, create items for EACH affected country
   - For EACH HS code found in the tables, create items for EACH affected company
   - Example: If you find 20 HS codes, 3 countries (China, Korea, Taiwan), and 5 companies,
     you should create 20 × 3 × 5 = 300 items (or appropriate combinations based on the data)
   - DO NOT create a single item with multiple HS codes - SEPARATE them
   - DO NOT create a single item with multiple countries - SEPARATE them

4. **Data Extraction from Tables:**
   - Look for product descriptions associated with each HS code
   - Extract company names and their specific rates
   - Note investigation periods and effective dates
   - Extract case numbers (ADN numbers)

5. **Australian Document Structure:**
   - First few pages: Introduction, background
   - Middle pages (typically 10-20 pages): HS code tables
   - Later pages: Company-specific information, rates, adjustments
   - Some sections may show changes without repeating all HS codes - in these cases,
     reference back to the HS codes found in earlier tables

OUTPUT JSON FORMAT:

{
  "items": [
    {
      "country": "Single country name ONLY (e.g., China, Korea, Taiwan)",
      "hs_code": "Single HS code in format XXXX.XX.XX or null",
      "tariff_type": "Antidumping or Countervailing or Safeguard",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": "YYYY-MM-DD or null",
      "investigation_period_to": "YYYY-MM-DD or null",
      "basis_law": "Legal basis",
      "company": "Company name or null",
      "case_number": "ADN number or null",
      "product_description": "Product description",
      "note": "Notes or null"
    }
  ]
}

**FINAL CHECKLIST:**
- [ ] Did I extract ALL HS codes from ALL pages of tables?
- [ ] Did I create separate items for each HS code?
- [ ] Did I create separate items for each country?
- [ ] Did I verify each HS code follows XXXX.XX.XX format?
- [ ] Did I create all necessary combinations?

**Output ONLY JSON, no explanatory text.**
"""


# ============================================================================
# 기본 export (하위 호환성)
# ============================================================================

# 기본적으로 OCR 버전 사용
AustraliaParser = AustraliaTextParser

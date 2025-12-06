"""
Australia Tariff Parser
호주 관세 정보 파서 - OCR 및 Vision API 버전
"""

from .default_parser import DefaultTextParser
from .base_parser import VisionBasedParser


# ============================================================================
# OCR (텍스트 추출) 버전
# ============================================================================

class AustraliaTextParser(DefaultTextParser):
    """호주 특화 파서 - OCR 버전"""

    def create_extraction_prompt(self) -> str:
        """호주 관세 문서에 특화된 프롬프트"""
        return """Extract tariff/trade remedy information from the Australian document text.

**CRITICAL INSTRUCTIONS:**

1. **HS Code Table Extraction - EXTREMELY IMPORTANT:**
   - Australian documents contain HS code tables that may span 10-20 pages
   - CAREFULLY examine the entire document text for ALL HS codes
   - HS codes are ONLY in 8-digit format: XXXX.XX.XX
   - Examples of actual HS codes: 7210.49.00, 7212.30.00, 7225.92.00, 7226.99.00
   - Extract EVERY SINGLE 8-digit HS code from the document
   - DO NOT miss any HS codes

2. **HS Code Validation - VERY IMPORTANT:**
   - ONLY extract 8-digit HS codes in format XXXX.XX.XX (e.g., 7210.49.00)
   - DO NOT extract 4-digit headers like "7210", "7212", "7225", "7226"
   - DO NOT extract 6-digit sub-headers like "7210.4", "7225.9", "7226.9"
   - DO NOT extract 2-digit Statistical codes like "55", "56", "57", "58", "61", "38", "71"
   - Statistical codes appear in a separate "Statistical code" column and are NOT HS codes
   - If a section references goods but no 8-digit HS code is shown, set hs_code to null

3. **Complete Combinations - MANDATORY:**
   - For EACH HS code found, create items for EACH affected country
   - For EACH HS code found, create items for EACH affected company
   - Example: If you find 20 HS codes, 3 countries (China, Korea, Taiwan), and 5 companies,
     you should create 20 × 3 × 5 = 300 items (or appropriate combinations based on the data)
   - DO NOT create a single item with multiple HS codes - SEPARATE them
   - DO NOT create a single item with multiple countries - SEPARATE them

4. **Data Extraction:**
   - Look for product descriptions associated with each HS code
   - Extract company names and their specific rates
   - Note investigation periods and effective dates
   - Extract case numbers (ADN numbers)

5. **Australian Document Structure:**
   - First section: Introduction, background
   - Middle section: HS code tables (most important!)
   - Later section: Company-specific information, rates, adjustments

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
- [ ] Did I extract ALL HS codes from the entire document?
- [ ] Did I create separate items for each HS code?
- [ ] Did I create separate items for each country?
- [ ] Did I verify each HS code follows XXXX.XX.XX format?
- [ ] Did I create all necessary combinations?

**Output ONLY JSON, no explanatory text.**
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

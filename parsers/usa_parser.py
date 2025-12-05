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
        return """Extract tariff/trade remedy information from the US document text.

**CRITICAL INSTRUCTIONS:**

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
- Output ONLY JSON, no explanatory text.
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

"""
USA Tariff Parser
미국 관세 정보 파서 - OCR 및 Vision API 버전
"""

from .default_parser import DefaultTextParser
from .base_parser import VisionBasedParser


# ============================================================================
# OCR (텍스트 추출) 버전
# ============================================================================

class USATextParser(DefaultTextParser):
    """미국 특화 파서 - OCR 버전"""
    pass  # 기본 파서 사용


# ============================================================================
# Vision API 버전
# ============================================================================

class USAVisionParser(VisionBasedParser):
    """미국 특화 파서 - Vision API 버전"""

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the US document images.

**CRITICAL INSTRUCTIONS:**

1. **HS Code Separation - MANDATORY:**
   - If multiple HS codes are listed, create SEPARATE items for EACH HS code
   - DO NOT combine multiple HS codes into one item

2. **Country Separation - MANDATORY:**
   - If multiple countries are listed, create SEPARATE items for EACH country
   - DO NOT combine multiple countries into one item

3. **Company Handling:**
   - If multiple companies are listed, create separate items for each company

4. **US-Specific Notes:**
   - Extract case numbers accurately (e.g., A-570-XXX, C-570-XXX)
   - Note investigation periods accurately
   - Extract company-specific rates

OUTPUT JSON FORMAT:

{
  "items": [
    {
      "country": "Single country name ONLY",
      "hs_code": "Single HS code ONLY",
      "tariff_type": "Antidumping or Countervailing or Safeguard",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": "YYYY-MM-DD or null",
      "investigation_period_to": "YYYY-MM-DD or null",
      "basis_law": "Legal basis",
      "company": "Company name or null",
      "case_number": "Case number or null",
      "product_description": "Product description",
      "note": "Notes or null"
    }
  ]
}

**REMEMBER:**
- ONE hs_code per item
- ONE country per item
- Create ALL combinations: each HS code × each country × each company
- Use ONLY information visible in the page images
- Output ONLY JSON, no explanatory text.
"""


# ============================================================================
# 기본 export (하위 호환성)
# ============================================================================

USAParser = USATextParser

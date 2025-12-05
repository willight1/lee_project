"""
EU Tariff Parser
유럽연합 관세 정보 파서 - OCR 및 Vision API 버전
"""

from .default_parser import DefaultTextParser
from .base_parser import VisionBasedParser


# ============================================================================
# OCR (텍스트 추출) 버전
# ============================================================================

class EUTextParser(DefaultTextParser):
    """유럽연합 특화 파서 - OCR 버전"""
    pass  # 기본 파서 사용


# ============================================================================
# Vision API 버전
# ============================================================================

class EUVisionParser(VisionBasedParser):
    """유럽연합 특화 파서 - Vision API 버전"""

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the EU document images.

**CRITICAL INSTRUCTIONS:**

1. **HS Code Separation - MANDATORY:**
   - If multiple HS codes are listed, create SEPARATE items for EACH HS code
   - DO NOT combine multiple HS codes into one item
   - EU may use 8-digit HS codes or TARIC codes

2. **Country Separation - MANDATORY:**
   - If multiple countries are listed, create SEPARATE items for EACH country
   - DO NOT combine multiple countries into one item

3. **Company Handling:**
   - If multiple companies are listed, create separate items for each company

4. **EU-Specific Notes:**
   - Extract TARIC codes if available
   - Note EU Regulation numbers
   - Extract company-specific duty rates

OUTPUT JSON FORMAT:

{
  "items": [
    {
      "country": "Single country name ONLY",
      "hs_code": "Single HS code ONLY (or TARIC code)",
      "tariff_type": "Antidumping or Countervailing or Safeguard",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": "YYYY-MM-DD or null",
      "investigation_period_to": "YYYY-MM-DD or null",
      "basis_law": "EU Regulation number",
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
# 하이브리드 파서 (텍스트 → 실패 시 Vision 폴백)
# ============================================================================
class EUHybridParser(DefaultTextParser):
    """EU 문서: 텍스트 파서 먼저 → 실패 시 Vision 폴백"""

    def __init__(self, client):
        super().__init__(client)
        self._vision = EUVisionParser(client)

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
# 기본 export (하위 호환성)
# ============================================================================

EUParser = EUHybridParser

"""
Malaysia Tariff Parser
말레이시아 관세 정보 파서 - OCR 및 Vision API 버전
"""

import re
from typing import Dict, List
from .default_parser import DefaultTextParser, extract_text_from_pdf
from .base_parser import VisionBasedParser


# ============================================================================
# OCR (텍스트 추출) 버전
# ============================================================================

class MalaysiaTextParser(DefaultTextParser):
    """말레이시아 특화 파서 - OCR 버전 (영어 섹션만 추출)"""

    def extract_english_section(self, text: str) -> str:
        """
        말레이시아 PDF에서 영어 섹션만 추출
        - 'SCHEDULE' 또는 'ANTI-DUMPING DUTIES' 이후 부분만 사용
        """
        # 영어 섹션 시작점 찾기
        markers = [
            r'SCHEDULE\s*\n',
            r'ANTI-DUMPING DUTIES',
            r'COUNTERVAILING DUTIES',
            r'SAFEGUARD DUTIES',
            r'\[English Text\]',
        ]
        
        for marker in markers:
            match = re.search(marker, text, re.IGNORECASE)
            if match:
                english_text = text[match.start():]
                print(f"    📝 Extracted English section starting from '{marker}' ({len(english_text):,} chars)")
                return english_text
        
        # 마커를 못 찾으면 전체 텍스트 반환
        print(f"    ⚠ No English marker found, using full text")
        return text

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the Malaysia document.

**CRITICAL INSTRUCTIONS:**

1. **Language**: This document contains English text. Extract information from the ENGLISH section only.

2. **Nil/Zero Rates**: 
   - If tariff rate is "Nil", "nil", "NIL", "0", "-" or empty, set tariff_rate to 0
   - These mean the company is EXEMPTED from anti-dumping duties

3. **HS Code Separation - MANDATORY:**
   - If multiple HS codes are listed, create SEPARATE items for EACH HS code
   - DO NOT combine multiple HS codes into one item

4. **Country Separation - MANDATORY:**
   - If multiple countries are listed, create SEPARATE items for EACH country
   - DO NOT combine multiple countries into one item

5. **Company Handling:**
   - If multiple companies are listed, create separate items for each company
   - "Others" or "Lain-lain" means all other companies not specifically listed

OUTPUT JSON FORMAT:

{
  "items": [
    {
      "country": "Single country name ONLY",
      "hs_code": "Single HS code ONLY",
      "tariff_type": "Antidumping or Countervailing or Safeguard",
      "tariff_rate": number (use 0 for Nil/exempt),
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": "YYYY-MM-DD or null",
      "investigation_period_to": "YYYY-MM-DD or null",
      "basis_law": "Legal basis (e.g., P.U. (A) 23/2018)",
      "company": "Company name or null",
      "case_number": "Case number or null",
      "product_description": "Product description in English",
      "note": "Notes or null"
    }
  ]
}

**REMEMBER:**
- ONE hs_code per item
- ONE country per item
- tariff_rate = 0 for Nil/exempt companies
- Create ALL combinations: each HS code × each country × each company
- Output ONLY JSON, no explanatory text.
"""

    def process(self, pdf_path: str) -> List[Dict]:
        """PDF에서 영어 섹션만 추출 후 LLM으로 파싱"""
        # 1. 텍스트 추출
        text = extract_text_from_pdf(pdf_path)

        # 2. 이미지 기반 PDF면 Vision API 사용
        if text is None or len(text) < 100:
            print(f"  💡 Switching to Vision API for image-based PDF")
            return self.process_image_pdf_with_vision(pdf_path)

        if not text:
            return []

        # 3. 영어 섹션만 추출
        english_text = self.extract_english_section(text)

        # 4. 텍스트가 너무 길면 배치로 나누기
        max_chars = 100000
        all_items = []

        if len(english_text) > max_chars:
            print(f"  📊 Text too long ({len(english_text):,} chars), splitting into batches...")
            pages = english_text.split("\n--- PAGE ")
            batch_text = ""
            batch_num = 1

            for page in pages:
                if not page.strip():
                    continue
                page_text = "--- PAGE " + page if batch_text else page
                if len(batch_text) + len(page_text) > max_chars:
                    print(f"  ▶ Processing batch {batch_num} ({len(batch_text):,} chars)...")
                    prompt = self.create_extraction_prompt()
                    response = self.parse_text_with_llm(batch_text, prompt)
                    items = self.parse_response(response)
                    all_items.extend(items)
                    print(f"  ✓ Batch {batch_num}: {len(items)} items")
                    batch_text = page_text
                    batch_num += 1
                else:
                    batch_text += "\n" + page_text

            if batch_text.strip():
                print(f"  ▶ Processing batch {batch_num} ({len(batch_text):,} chars)...")
                prompt = self.create_extraction_prompt()
                response = self.parse_text_with_llm(batch_text, prompt)
                items = self.parse_response(response)
                all_items.extend(items)
                print(f"  ✓ Batch {batch_num}: {len(items)} items")
        else:
            print(f"  ▶ Processing English section ({len(english_text):,} chars)...")
            prompt = self.create_extraction_prompt()
            response = self.parse_text_with_llm(english_text, prompt)
            all_items = self.parse_response(response)

        print(f"  ➜ Total items from all batches: {len(all_items)}")
        return all_items


# ============================================================================
# Vision API 버전
# ============================================================================

class MalaysiaVisionParser(VisionBasedParser):
    """말레이시아 특화 파서 - Vision API 버전"""

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the Malaysia document images.

**CRITICAL INSTRUCTIONS:**

1. **HS Code Separation - MANDATORY:**
   - If multiple HS codes are listed, create SEPARATE items for EACH HS code
   - DO NOT combine multiple HS codes into one item

2. **Country Separation - MANDATORY:**
   - If multiple countries are listed, create SEPARATE items for EACH country
   - DO NOT combine multiple countries into one item

3. **Company Handling:**
   - If multiple companies are listed, create separate items for each company

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
# 하이브리드 파서 (텍스트 → 실패 시 Vision 폴백)
# ============================================================================
class MalaysiaHybridParser(DefaultTextParser):
    """Malaysia 문서: 텍스트 파서 먼저 → 실패 시 Vision 폴백"""

    def __init__(self, client):
        super().__init__(client)
        self._vision = MalaysiaVisionParser(client)

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

MalaysiaParser = MalaysiaHybridParser

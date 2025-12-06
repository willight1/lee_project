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
    """말레이시아 특화 파서 - OCR 버전 (HS Code × Company 조합 자동 생성)"""

    def extract_english_section(self, text: str) -> str:
        """
        말레이시아 PDF에서 영어 섹션만 추출
        - 'SCHEDULE' 또는 'ANTI-DUMPING DUTIES' 이후 부분만 사용
        """
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
        
        print(f"    ⚠ No English marker found, using full text")
        return text

    def extract_hs_codes(self, text: str) -> List[str]:
        """텍스트에서 말레이시아 형식 HS Code 추출 (XXXX.XX.XX XX)"""
        hs_codes = []
        
        # 말레이시아 HS 코드 패턴: XXXX.XX.XX XX
        pattern = r'\b(\d{4}\.\d{2}\.\d{2}\s+\d{2})\b'
        matches = re.findall(pattern, text)
        
        for code in matches:
            # 72XX 또는 73XX로 시작하는 철강 관련 코드만
            if code.startswith('72') or code.startswith('73'):
                if code not in hs_codes:
                    hs_codes.append(code)
        
        if hs_codes:
            print(f"    📝 Found {len(hs_codes)} unique HS codes")
        
        return hs_codes

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

    def post_process_items(self, items: List[Dict]) -> List[Dict]:
        """후처리: Nil→0, 잘못된 회사명 제거"""
        processed = []
        
        for item in items:
            # Nil → 0
            rate = item.get('tariff_rate')
            if rate is None or (isinstance(rate, str) and rate.lower() == 'nil'):
                item['tariff_rate'] = 0
            
            # 테이블에 없는 잘못된 회사명 필터링 (영어가 아닌 경우 등)
            company = item.get('company', '')
            if company and any(char in company for char in ['的', '한', '가']):
                continue  # 비영어 회사명 제외
            
            processed.append(item)
        
        return processed

    def create_extraction_prompt(self) -> str:
        return """Extract company and tariff rate information from the Malaysia ANTI-DUMPING DUTIES table.

**FOCUS ON EXTRACTING:**
1. **Country** names
2. **Company** names - including "Others" or "Other producers"
3. **Tariff rates** (% or "Nil" = 0)

**COMPANY EXTRACTION RULES:**
- Roman numerals (i), (ii), (iii), (iv), (v) = SEPARATE companies
- "Others", "Other producers", "Lain-lain" = valid company, include it
- Alphabetical markers (A), (B), (C) = notes, NOT companies

**OUTPUT FORMAT:**
{
  "items": [
    {
      "country": "Country name",
      "hs_code": null,
      "tariff_type": "Antidumping",
      "tariff_rate": number (0 for Nil),
      "company": "Company name or Others",
      "note": "(A), (B), (C) conditions if any"
    }
  ]
}

**CHECKLIST:**
- [ ] Include ALL companies with (i), (ii), (iii), etc.
- [ ] Include "Others" as a company
- [ ] Convert "Nil" to 0

Output ONLY valid JSON.
"""

    def process(self, pdf_path: str) -> List[Dict]:
        """PDF 처리: HS Code 추출 + Company 파싱 + 조합 생성"""
        # 1. 텍스트 추출
        text = extract_text_from_pdf(pdf_path)

        if text is None or len(text) < 100:
            print(f"  💡 Switching to Vision API for image-based PDF")
            # MalaysiaVisionParser의 2단계 추출 사용
            vision_parser = MalaysiaVisionParser(self.client)
            return vision_parser.process(pdf_path)

        if not text:
            return []

        # 2. 전체 텍스트에서 HS Code 추출
        all_hs_codes = self.extract_hs_codes(text)

        # 3. 영어 섹션만 추출
        english_text = self.extract_english_section(text)

        # 4. LLM으로 회사/비율 파싱 (HS Code는 코드로 처리)
        max_chars = 50000
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

        print(f"  ➜ Total items from LLM: {len(all_items)}")

        # 5. 후처리
        processed_items = self.post_process_items(all_items)

        # 6. HS Code × Company 조합 생성
        final_items = self.expand_hs_codes(processed_items, all_hs_codes)

        print(f"  ➜ Final items after HS code expansion: {len(final_items)}")
        return final_items


# ============================================================================
# Vision API 버전
# ============================================================================

class MalaysiaVisionParser(VisionBasedParser):
    """말레이시아 특화 파서 - Vision API 버전 (HS Code × Company 조합 생성)"""

    def extract_hs_codes_from_vision_response(self, items: List[Dict]) -> List[str]:
        """Vision API 응답에서 고유 HS Code 추출"""
        hs_codes = []
        for item in items:
            hs = item.get('hs_code')
            if hs and hs not in hs_codes:
                # 72XX 또는 73XX 철강 코드만
                if str(hs).startswith('72') or str(hs).startswith('73'):
                    hs_codes.append(hs)
        return hs_codes

    def expand_hs_codes(self, items: List[Dict], hs_codes: List[str]) -> List[Dict]:
        """HS Code × Company 조합 생성"""
        if not hs_codes:
            return items
        
        expanded = []
        unique_companies = {}
        
        for item in items:
            key = (item.get('country'), item.get('company'), item.get('tariff_rate'))
            if key not in unique_companies:
                unique_companies[key] = item.copy()
        
        for hs_code in hs_codes:
            for key, template in unique_companies.items():
                new_item = template.copy()
                new_item['hs_code'] = hs_code
                expanded.append(new_item)
        
        print(f"    📊 Expanded: {len(unique_companies)} companies × {len(hs_codes)} HS codes = {len(expanded)} items")
        return expanded

    def process(self, pdf_path: str) -> List[Dict]:
        """Vision API 처리 - 2단계 추출 (HS Code 전용 + Company/Rate)"""
        print(f"  🖼️  Processing image-based PDF with Vision API (2-pass)...")
        
        # PDF를 이미지로 변환
        page_imgs = self.get_pdf_page_images(pdf_path)
        if not page_imgs:
            return []

        total_pages = len(page_imgs)
        BATCH_PAGE_LIMIT = 10
        
        # ============================================================
        # PASS 1: HS Code 전용 추출 (더 정확한 추출을 위해 분리)
        # ============================================================
        print(f"  [Pass 1] Extracting HS Codes...")
        all_hs_codes: List[str] = []
        hs_instruction = self._create_hs_code_only_prompt()
        
        for start in range(0, total_pages, BATCH_PAGE_LIMIT):
            end = min(start + BATCH_PAGE_LIMIT, total_pages)
            batch = page_imgs[start:end]
            batch_page_nums = [p for p, _ in batch]
            print(f"    ▶ Pages {batch_page_nums[0]}–{batch_page_nums[-1]}")

            b64_list = [b64 for _, b64 in batch]
            response = self.call_vision_api(hs_instruction, b64_list)
            
            # HS 코드 파싱
            parsed = self._parse_vision_response(response)
            batch_hs = parsed.get('hs_codes', [])
            
            for hs in batch_hs:
                if hs and hs not in all_hs_codes:
                    # 72XX 또는 73XX 철강 코드만
                    if str(hs).startswith('72') or str(hs).startswith('73'):
                        all_hs_codes.append(hs)
            
            print(f"    ✓ Found {len(batch_hs)} HS codes in this batch")
        
        print(f"  ➜ Pass 1 complete: {len(all_hs_codes)} unique HS codes")
        if all_hs_codes:
            print(f"    📝 {all_hs_codes}")
        
        # ============================================================
        # PASS 2: Company/Rate 추출
        # ============================================================
        print(f"  [Pass 2] Extracting Companies and Rates...")
        all_items: List[Dict] = []
        company_instruction = self.create_extraction_prompt()
        
        for start in range(0, total_pages, BATCH_PAGE_LIMIT):
            end = min(start + BATCH_PAGE_LIMIT, total_pages)
            batch = page_imgs[start:end]
            batch_page_nums = [p for p, _ in batch]
            print(f"    ▶ Pages {batch_page_nums[0]}–{batch_page_nums[-1]}")

            b64_list = [b64 for _, b64 in batch]
            response = self.call_vision_api(company_instruction, b64_list)
            
            # Items 파싱
            parsed = self._parse_vision_response(response)
            items = parsed.get('items', [])
            all_items.extend(items)
            
            # 혹시 Pass 1에서 못 찾은 HS 코드가 있으면 추가
            extra_hs = parsed.get('hs_codes', [])
            for hs in extra_hs:
                if hs and hs not in all_hs_codes:
                    if str(hs).startswith('72') or str(hs).startswith('73'):
                        all_hs_codes.append(hs)
            
            print(f"    ✓ Found {len(items)} items in this batch")

        print(f"  ➜ Pass 2 complete: {len(all_items)} items")
        print(f"  ➜ Total HS codes: {len(all_hs_codes)}")
        
        # HS Code × Company 조합 생성
        if all_hs_codes:
            expanded_items = self.expand_hs_codes(all_items, all_hs_codes)
            return expanded_items
        
        # Fallback: items에서 HS 코드 추출
        fallback_hs = self.extract_hs_codes_from_vision_response(all_items)
        if fallback_hs:
            print(f"    📝 Found {len(fallback_hs)} HS codes from items (fallback)")
            return self.expand_hs_codes(all_items, fallback_hs)
        
        return all_items
    
    def _create_hs_code_only_prompt(self) -> str:
        """HS 코드만 전용 추출하는 프롬프트"""
        return """Extract ALL HS codes from this Malaysia tariff document.

**YOUR ONLY TASK: Find and list ALL HS codes.**

LOOK FOR:
- The table column "(1) Heading/Subheading Number according to H.S. Code"
- HS codes look like: XXXX.XX.XX XX (e.g., 7210.49.11 00, 7212.30.11 00)
- They are steel product codes starting with 72 or 73

SCAN EVERY visible HS code in the document images.
There are typically 15-20 different HS codes.

OUTPUT FORMAT:
{
  "hs_codes": [
    "7210.49.11 00",
    "7210.49.12 00",
    "7210.49.19 00",
    "7210.61.11 00",
    "7210.61.12 00",
    "7212.30.11 00",
    "7212.30.12 00"
  ],
  "items": []
}

IMPORTANT:
- List EVERY unique HS code you can see
- Include the 2-digit suffix after space (e.g., "00" or "10")  
- Do NOT skip any codes
- Output ONLY valid JSON"""

    def _parse_vision_response(self, response: str) -> Dict:
        """Vision API 응답 파싱 - hs_codes와 items 둘 다 추출"""
        import re
        import json
        
        if not response:
            return {'hs_codes': [], 'items': []}

        # 제어 문자 제거
        response = ''.join(
            char for char in response
            if ord(char) >= 32 or char in '\n\t\r'
        )

        # ```json 블럭 처리
        if '```' in response:
            json_match = re.search(
                r'```(?:json)?\s*\n(.*?)\n```',
                response,
                re.DOTALL
            )
            if json_match:
                response = json_match.group(1)

        # 앞뒤 정리
        response = response.strip()
        if not response.startswith('{'):
            first_brace = response.find('{')
            if first_brace != -1:
                response = response[first_brace:]

        # 콤마 정리
        response = re.sub(r',(\s*[}\]])', r'\1', response)

        # 중괄호 짝 맞추기
        if not response.rstrip().endswith('}'):
            open_braces = response.count('{')
            close_braces = response.count('}')
            open_brackets = response.count('[')
            close_brackets = response.count(']')

            if close_brackets < open_brackets:
                response += ']' * (open_brackets - close_brackets)
            if close_braces < open_braces:
                response += '}' * (open_braces - close_braces)

        try:
            data = json.loads(response)
            hs_codes = data.get('hs_codes', [])
            items = data.get('items', [])
            print(f"    ✓ Parsed {len(items)} items, {len(hs_codes)} HS codes")
            return {'hs_codes': hs_codes, 'items': items}
        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON decode error: {e}")
            return {'hs_codes': [], 'items': []}

    def create_extraction_prompt(self) -> str:
        return """Extract ALL tariff information from the Malaysia document images.

**CRITICAL - READ CAREFULLY:**

This document has a TABLE structure where:
- HS Codes appear in COLUMN HEADERS (column 1: "Heading/Subheading Number according to H.S. Code")
- Companies and tariff rates appear in OTHER COLUMNS

**STEP 1: FIRST, extract ALL HS Codes from the table header column**
Look for codes like: XXXX.XX.XX XX (e.g., 7210.49.11 00, 7210.61.12 00)
These appear in "(1) Heading/Subheading Number according to H.S. Code" column.

**STEP 2: For EACH row, extract:**
- Country (from column 2)
- Company name (from column 4 - look for Roman numerals (i), (ii), (iii), (iv))
- Tariff rate (from column 5)
- Notes like (A), (B), (C) conditions

**COMPANY EXTRACTION RULES:**
- (i), (ii), (iii), (iv) = SEPARATE companies, each must be extracted
- "Others", "Other producers", "Other producer or exporter" = valid company, MUST include
- Alphabetical markers (A), (B), (C) = notes/conditions, NOT company names

**OUTPUT FORMAT:**
{
  "hs_codes": [
    "7210.49.11 00",
    "7210.49.12 00",
    "7210.61.11 00"
  ],
  "items": [
    {
      "country": "Country name",
      "hs_code": null,
      "tariff_type": "Antidumping",
      "tariff_rate": number (0 for Nil),
      "company": "Company name",
      "note": "(A), (B), (C) conditions if any"
    }
  ]
}

**IMPORTANT CHECKLIST:**
- [ ] Extract EVERY HS code visible in the table (usually 10-20 codes)
- [ ] Extract EVERY company including "Others" or "Other producer or exporter"
- [ ] Keep hs_code as null in items - we will combine them later
- [ ] Convert "Nil" tariff rates to 0

Output ONLY valid JSON."""


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

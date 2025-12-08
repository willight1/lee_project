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
        """10 MEASURES 섹션의 첫 번째 표만 추출 (목차가 아닌 본문에서)"""
        # 본문의 10 MEASURES를 찾기 위해 "10.1 Recommendations" 패턴 사용
        # 목차에는 페이지 번호가 붙어있고 본문에는 없음
        patterns = [
            r'10\.1\s+Recommendations\s*\n',  # 본문의 10.1 섹션
            r'10\s+MEASURES\s*\n10\.1',       # "10 MEASURES" 다음에 바로 "10.1"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # 10.1 이전의 "10 MEASURES" 헤더도 포함하기 위해 조금 앞에서 시작
                start_pos = max(0, match.start() - 200)
                measures_text = text[start_pos:]
                
                # 20,000자만 추출
                measures_text = measures_text[:20000]
                    
                print(f"    📝 Extracted MEASURES section ({len(measures_text):,} chars)")
                return measures_text
        
        # 폴백: 일반 패턴 사용
        simple_patterns = [r'10\s+MEASURES', r'10\.\s*MEASURES']
        for pattern in simple_patterns:
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            if len(matches) >= 2:
                # 두 번째 매치 사용 (첫 번째는 목차일 가능성 높음)
                match = matches[1]
            elif matches:
                match = matches[0]
            else:
                continue
                
            measures_text = text[match.start():][:20000]
            print(f"    📝 Extracted MEASURES section ({len(measures_text):,} chars)")
            return measures_text
        
        print(f"    ⚠ MEASURES section not found, using last 20000 chars")
        return text[-20000:]

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
        """후처리: 음수 비율만 제거 (HS Code는 expand에서 처리)"""
        processed = []
        negative_removed = 0
        
        for item in items:
            # 1. 음수 비율만 제거 (null이나 0은 허용)
            rate = item.get('tariff_rate')
            if rate is not None:
                try:
                    rate_float = float(rate)
                    if rate_float < 0:
                        negative_removed += 1
                        continue  # 음수 비율만 건너뛰기
                except (ValueError, TypeError):
                    # 숫자가 아닌 경우는 그대로 유지 (note로 이동됨)
                    pass
            
            # HS Code 검증 제거 - expand_hs_codes에서 올바른 HS 코드로 대체됨
            processed.append(item)
        
        if negative_removed > 0:
            print(f"    ✓ Removed {negative_removed} items with negative rates")
        
        return processed

    def extract_inquiry_period(self, text: str) -> tuple:
        """Introduction에서 Inquiry period 추출 (조사기간)"""
        # 패턴: "Inquiry period  1 July 2021 to 30 June 2022" 형태
        patterns = [
            r'Inquiry\s+period\s+(\d{1,2}\s+\w+\s+\d{4})\s+to\s+(\d{1,2}\s+\w+\s+\d{4})',
            r'investigation\s+period\s+(\d{1,2}\s+\w+\s+\d{4})\s+to\s+(\d{1,2}\s+\w+\s+\d{4})',
            r'inquiry\s+period[:\s]+(\d{1,2}\s+\w+\s+\d{4})\s*[-–to]+\s*(\d{1,2}\s+\w+\s+\d{4})',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                from_date_str = match.group(1)
                to_date_str = match.group(2)
                
                # 날짜 형식 변환 (1 July 2021 -> 2021-07-01)
                try:
                    from datetime import datetime
                    from_date = datetime.strptime(from_date_str, "%d %B %Y").strftime("%Y-%m-%d")
                    to_date = datetime.strptime(to_date_str, "%d %B %Y").strftime("%Y-%m-%d")
                    print(f"    📅 Found Inquiry period: {from_date} to {to_date}")
                    return (from_date, to_date)
                except ValueError:
                    # 날짜 파싱 실패 시 원본 문자열 반환
                    print(f"    📅 Found Inquiry period (raw): {from_date_str} to {to_date_str}")
                    return (from_date_str, to_date_str)
        
        return (None, None)

    def process(self, pdf_path: str) -> List[Dict]:
        """PDF 처리: MEASURES 섹션만 추출 후 파싱"""
        # 1. 텍스트 추출
        text = extract_text_from_pdf(pdf_path)
        
        if not text or len(text) < 100:
            print(f"  💡 Text extraction failed, switching to Vision API")
            return self.process_image_pdf_with_vision(pdf_path)
        
        # 2. 전체 텍스트에서 HS Code 먼저 추출 (섹션 3.4에서)
        all_hs_codes = self.extract_hs_codes_from_section_34(text)
        
        # 2.5. Introduction에서 Inquiry period 추출
        inquiry_from, inquiry_to = self.extract_inquiry_period(text)
        
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
        
        # 7. Inquiry period 적용
        if inquiry_from or inquiry_to:
            for item in final_items:
                item['investigation_period_from'] = inquiry_from
                item['investigation_period_to'] = inquiry_to
        
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
        
        # 디버깅: 추출된 회사 목록 출력
        print(f"    🔍 Unique companies extracted: {[k[1] for k in unique_companies.keys()]}")
        
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
        return """Extract tariff data from the FIRST TABLE immediately after "10 MEASURES" heading.

**⚠️ CRITICAL: ONLY THE FIRST TABLE AFTER "10 MEASURES" ⚠️**

**TABLE STRUCTURE:**
The table has these columns:
- Country
- Exporter (company name)
- Measure (IDD, ICD, or "IDD and ICD")
- Measure type (Floor price, Combination, etc.)
- Effective rate of duty (percentage)

**MAPPING RULES:**
1. **Measure → tariff_type:**
   - If Measure = "IDD" → tariff_type = "Antidumping"
   - If Measure = "ICD" → tariff_type = "Countervailing"
   - If Measure = "IDD and ICD" → tariff_type = "Antidumping and Countervailing"

2. **Measure type → note:**
   - Store the Measure type value (e.g., "Floor price", "Combination") in the note field

**WHAT TO EXTRACT:**
- Every row from the table
- Each row = one JSON item
- Include rows with 0%, N/A, or "nil" duty

**OUTPUT FORMAT:**
{
  "items": [
    {
      "country": "Country name",
      "hs_code": null,
      "tariff_type": "Antidumping or Countervailing",
      "tariff_rate": number or null (for N/A),
      "effective_date_from": null,
      "effective_date_to": null,
      "investigation_period_from": null,
      "investigation_period_to": null,
      "basis_law": "Customs Act 1901",
      "company": "Company/Exporter name from table row",
      "case_number": null,
      "product_description": null,
      "note": "Measure type value (Floor price, Combination, etc.)"
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
        return """Extract tariff/trade remedy information from Australian Anti-Dumping document.

**⚠️⚠️⚠️ EXTREMELY IMPORTANT ⚠️⚠️⚠️**

**STEP 1: FIND THE PAGE WITH "10 MEASURES" OR "10. MEASURES" HEADING**
- Scroll/look through the document until you find the section titled "10 MEASURES"
- This is usually on page 30+ of the document

**STEP 2: EXTRACT DATA FROM THE TABLE(S) THAT APPEAR AFTER "10 MEASURES" HEADING**
- The table(s) you need are IMMEDIATELY AFTER the "10 MEASURES" heading
- These tables show the FINAL duty rates

**❌ DO NOT EXTRACT FROM THESE (WRONG TABLES):**
- Tables showing "Hong Shun", "Chung Hung", "Sheng Yu Steel"
- Tables at the beginning or middle of the document
- Any table that appears BEFORE the "10 MEASURES" heading
- Exporter/Producer summary tables from earlier sections

**✅ EXTRACT ONLY FROM THE TABLE AFTER "10 MEASURES" HEADING:**
- This table contains columns like: Exporter, Manufacturer, Dumping Margin, Duty Rate
- Look for the FINAL anti-dumping duty percentages
- Countries: China, Korea, Taiwan, Vietnam, etc.
- Company names with their specific duty rates

**WHAT TO EXTRACT:**
1. Company names from the "10 MEASURES" table
2. Duty rates (percentages) from that table
3. Countries associated with each company
4. HS Codes (if shown) - format XXXX.XX.XX
5. Case numbers (ADN 20XX/XXX)

**OUTPUT JSON FORMAT:**
{
  "items": [
    {
      "country": "Country name",
      "hs_code": "XXXX.XX.XX or null",
      "tariff_type": "Antidumping",
      "tariff_rate": number or null,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": null,
      "investigation_period_from": null,
      "investigation_period_to": null,
      "basis_law": "Customs Act 1901",
      "company": "Company name",
      "case_number": "ADN 20XX/XXX or null",
      "product_description": null,
      "note": null
    }
  ]
}

**Output ONLY valid JSON.**
"""


# ============================================================================
# 기본 export (하위 호환성)
# ============================================================================

# 기본적으로 OCR 버전 사용
AustraliaParser = AustraliaTextParser

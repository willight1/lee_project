"""
EU Tariff Parser
유럽연합 관세 정보 파서 - OCR 및 Vision API 버전
"""

import re
from datetime import datetime
from typing import List, Dict, Optional
from .default_parser import DefaultTextParser
from .base_parser import VisionBasedParser


# ============================================================================
# OCR (텍스트 추출) 버전
# ============================================================================

class EUTextParser(DefaultTextParser):
    """유럽연합 특화 파서 - OCR 버전 (ANTI-DUMPING MEASURES 섹션만 사용, MIP 처리)"""

    def extract_measures_section(self, text: str) -> str:
        """7. ANTI-DUMPING MEASURES 섹션만 추출"""
        patterns = [
            r'7\.?\s*ANTI-DUMPING\s+MEASURES',
            r'DEFINITIVE\s+ANTI-DUMPING\s+MEASURES',
            r'Article\s+1\s*\n',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                measures_text = text[match.start():]
                # 30000자 제한
                if len(measures_text) > 30000:
                    measures_text = measures_text[:30000]
                print(f"    📝 Extracted MEASURES section ({len(measures_text):,} chars)")
                return measures_text
        
        print(f"    ⚠ ANTI-DUMPING MEASURES section not found, using last 30000 chars")
        return text[-30000:]

    def extract_mip_info(self, text: str) -> Optional[str]:
        """Minimum Import Price 정보 추출"""
        mip_patterns = [
            r'MIPs?\s+(?:currently\s+)?(?:in\s+force\s+)?(?:range\s+)?(?:between\s+)?[\d,\s]+EUR[^.]*',
            r'minimum\s+import\s+price[s]?\s*(?:of)?\s*[\d,\s]+EUR[^.]*',
            r'MIP\s*\([^)]*EUR[^)]*\)',
        ]
        
        for pattern in mip_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                mip_text = match.group().strip()
                # 너무 길면 자르기
                if len(mip_text) > 150:
                    mip_text = mip_text[:150] + "..."
                return mip_text
        return None

    def normalize_hs_code(self, hs_code: str) -> str:
        """HS 코드를 XXXX.XX.XX 형식으로 정규화 (ex 제거, 공백 제거)"""
        if not hs_code:
            return None
        
        # 문자열로 변환
        hs_str = str(hs_code)
        
        # ex 접두어 제거
        hs_str = re.sub(r'^ex\s*', '', hs_str, flags=re.IGNORECASE)
        
        # 숫자만 추출 (공백, 점 등 제거)
        digits = re.sub(r'[^\d]', '', hs_str)
        
        # 8자리가 아니면 None 반환 (10자리 무시)
        if len(digits) != 8:
            return None
        
        # XXXX.XX.XX 형식으로 포맷
        formatted = f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}"
        return formatted

    def post_process_items(self, items: List[Dict], mip_info: str = None) -> List[Dict]:
        """추출된 아이템들에 대한 HS 코드 후처리 및 MIP 정보 추가"""
        processed_items = []
        
        for item in items:
            # HS 코드 정규화
            hs_code = item.get('hs_code')
            if hs_code:
                normalized_hs = self.normalize_hs_code(hs_code)
                if normalized_hs:
                    item['hs_code'] = normalized_hs
                else:
                    # 8자리가 아니면 아이템 제외
                    print(f"    ⚠ Skipping invalid HS code: {hs_code}")
                    continue
            
            # MIP 정보 추가 (note가 비어있는 경우에만)
            if mip_info and not item.get('note'):
                item['note'] = f"MIP: {mip_info}"
            
            processed_items.append(item)
        
        return processed_items

    def process(self, pdf_path: str) -> List[Dict]:
        """PDF 처리: ANTI-DUMPING MEASURES 섹션만 추출 후 파싱"""
        from .default_parser import extract_text_from_pdf
        
        # 1. 텍스트 추출
        text = extract_text_from_pdf(pdf_path)
        
        if not text or len(text) < 100:
            print(f"  💡 Text extraction failed, switching to Vision API")
            return self.process_image_pdf_with_vision(pdf_path)
        
        # 2. MIP 정보 추출 (전체 텍스트에서)
        mip_info = self.extract_mip_info(text)
        if mip_info:
            print(f"    📝 Found MIP: {mip_info[:80]}...")
        
        # 3. MEASURES 섹션만 추출
        measures_text = self.extract_measures_section(text)
        
        # 4. 텍스트가 너무 길면 배치로 나누기
        max_chars = 100000
        all_items = []

        if len(measures_text) > max_chars:
            print(f"  📊 Text too long ({len(measures_text):,} chars), splitting into batches...")
            pages = measures_text.split("\n--- PAGE ")
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
            print(f"  ▶ Processing MEASURES section ({len(measures_text):,} chars)...")
            prompt = self.create_extraction_prompt()
            response = self.parse_text_with_llm(measures_text, prompt)
            all_items = self.parse_response(response)

        print(f"  ➜ Total items from all batches: {len(all_items)}")
        
        # 5. 후처리 (HS 코드 정규화, MIP 추가)
        processed_items = self.post_process_items(all_items, mip_info)
        
        print(f"  📝 After post-processing: {len(processed_items)} items")
        return processed_items


# ============================================================================
# Vision API 버전
# ============================================================================

class EUVisionParser(VisionBasedParser):
    """유럽연합 특화 파서 - Vision API 버전"""

    def __init__(self, client):
        super().__init__(client)
        self.model_name = "gpt-4.1"  # Vision 모델

    def normalize_hs_code(self, hs_code: str) -> str:
        """HS 코드를 XXXX.XX.XX 형식으로 정규화 (ex 제거, 공백 제거)"""
        if not hs_code:
            return None
        
        # 문자열로 변환
        hs_str = str(hs_code)
        
        # ex 접두어 제거
        hs_str = re.sub(r'^ex\s+', '', hs_str, flags=re.IGNORECASE)
        
        # 숫자만 추출 (공백, 점 등 제거)
        digits = re.sub(r'[^\d]', '', hs_str)
        
        # 8자리가 아니면 None 반환 (10자리 무시)
        if len(digits) != 8:
            return None
        
        # XXXX.XX.XX 형식으로 포맷
        formatted = f"{digits[:4]}.{digits[4:6]}.{digits[6:8]}"
        return formatted

    def clean_company_name(self, company: str) -> str:
        """회사명에서 첫 번째 콤마 앞만 추출"""
        if not company:
            return None
        
        # 첫 번째 콤마 앞만 추출
        if ',' in company:
            company = company.split(',')[0].strip()
        
        return company

    def normalize_date(self, date_str: str) -> Optional[str]:
        """날짜를 YYYY-MM-DD 형식으로 변환"""
        if not date_str:
            return None
        
        date_str = str(date_str).strip()
        
        # 이미 YYYY-MM-DD 형식인지 확인
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            return date_str
        
        # "day month year" 형식 파싱 (예: "1 July 2019", "30 June 2020")
        month_map = {
            'january': '01', 'jan': '01',
            'february': '02', 'feb': '02',
            'march': '03', 'mar': '03',
            'april': '04', 'apr': '04',
            'may': '05',
            'june': '06', 'jun': '06',
            'july': '07', 'jul': '07',
            'august': '08', 'aug': '08',
            'september': '09', 'sep': '09', 'sept': '09',
            'october': '10', 'oct': '10',
            'november': '11', 'nov': '11',
            'december': '12', 'dec': '12'
        }
        
        # "day month year" 패턴 찾기
        pattern = r'(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})'
        match = re.search(pattern, date_str, re.IGNORECASE)
        if match:
            day = match.group(1).zfill(2)
            month_name = match.group(2).lower()
            year = match.group(3)
            
            month = month_map.get(month_name)
            if month:
                return f"{year}-{month}-{day}"
        
        # 다른 형식 시도 (예: "2019-07-01", "01/07/2019" 등)
        try:
            # 다양한 형식 시도
            for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%Y/%m/%d']:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime('%Y-%m-%d')
                except ValueError:
                    continue
        except Exception:
            pass
        
        # 변환 실패 시 원본 반환 (나중에 수동 확인 가능)
        return date_str

    def post_process_items(self, items: List[Dict]) -> List[Dict]:
        """추출된 아이템들에 대한 후처리"""
        processed_items = []
        
        # 모든 아이템에서 investigation_period 찾기 (첫 번째로 발견된 값 사용)
        investigation_period_from = None
        investigation_period_to = None
        
        for item in items:
            if item.get('investigation_period_from'):
                investigation_period_from = item.get('investigation_period_from')
            if item.get('investigation_period_to'):
                investigation_period_to = item.get('investigation_period_to')
        
        # investigation_period 날짜 정규화
        if investigation_period_from:
            investigation_period_from = self.normalize_date(investigation_period_from)
        if investigation_period_to:
            investigation_period_to = self.normalize_date(investigation_period_to)
        
        for item in items:
            # 1. issuing_country 설정
            if not item.get('issuing_country'):
                item['issuing_country'] = 'European Union'
            
            # 2. HS 코드 정규화
            hs_code = item.get('hs_code')
            if hs_code:
                # 이미 포맷된 경우 (7225.11.00)도 처리
                hs_str = str(hs_code).replace('.', '').replace(' ', '')
                normalized_hs = self.normalize_hs_code(hs_str)
                if normalized_hs:
                    item['hs_code'] = normalized_hs
                else:
                    # 8자리가 아니면 아이템 제외
                    continue
            
            # 3. 날짜 필드 정규화
            for date_field in ['effective_date_from', 'effective_date_to', 'investigation_period_from', 'investigation_period_to']:
                if item.get(date_field):
                    normalized_date = self.normalize_date(item[date_field])
                    item[date_field] = normalized_date
            
            # 4. investigation_period를 모든 아이템에 적용 (공통 값)
            if investigation_period_from:
                item['investigation_period_from'] = investigation_period_from
            if investigation_period_to:
                item['investigation_period_to'] = investigation_period_to
            
            # 5. 세미콜론으로 구분된 회사 분리
            company = item.get('company')
            if company and ';' in company:
                # 세미콜론으로 분리
                company_parts = [part.strip() for part in company.split(';')]
                
                # 각 회사에 대해 새 아이템 생성
                for part in company_parts:
                    # 첫 번째 콤마 앞만 회사명으로 사용
                    company_name = self.clean_company_name(part)
                    
                    # 새 아이템 생성 (회사명만 변경, 나머지는 복제)
                    new_item = item.copy()
                    new_item['company'] = company_name
                    processed_items.append(new_item)
            else:
                # 세미콜론이 없으면 회사명만 정리
                if company:
                    item['company'] = self.clean_company_name(company)
                processed_items.append(item)
        
        return processed_items

    def process(self, pdf_path: str) -> List[Dict]:
        """PDF 처리 및 후처리"""
        # 부모 클래스의 process 호출
        items = super().process(pdf_path)
        
        # 후처리 적용
        processed_items = self.post_process_items(items)
        
        return processed_items

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the EU anti-dumping Implementing Regulation PDF.

**CORE RULES (MUST FOLLOW):**

- Use ONLY the definitive anti-dumping measures under the section titled "ANTI-DUMPING MEASURES" (typically section 7) and in particular Article 1 imposing the definitive duty. Ignore historical explanations and provisional measures.
- ONE hs_code per item, ONE country per item, ONE company per item.
- HS/CN/TARIC 코드는 문서에 기재된 8자리 숫자를 그대로 추출한다. 'ex' 앞단어는 제거하되, 숫자는 변형하지 않는다. 10자리 코드는 무시한다.
- The issuing_country field must always be set to 'European Union'.
- For ad valorem duties, tariff_rate is the percentage value. For pure MIP duties, tariff_rate is the string 'MIP' and the full MIP text with numeric value and unit goes into note.
- Always extract the case_number from the first page title (e.g., (EU) 2022/58).
- **IMPORTANT**: Before extracting tariff items, search the ENTIRE document (especially early pages) for the section titled "Review investigation period and period considered" to extract investigation_period_from and investigation_period_to. This information should be applied to ALL items.

**DETAILED INSTRUCTIONS:**

1. **APPLICATION SCOPE (Final Results Only):**

   EU documents contain lengthy descriptions of the entire investigation process (background, investigation, analysis), but we only need information about the final measures (final anti-dumping measures).

   Always use ONLY what appears after "ANTI-DUMPING MEASURES" (e.g., "7. ANTI-DUMPING MEASURES") - specifically Article 1 that states "imposing a definitive anti-dumping duty..." and the tables below it that actually impose the definitive duty.

   IGNORE everything that appears before the final measures:
   - Descriptions of previously existing MIPs
   - Provisional duties
   - Historical measures (history)

   In summary, extract items ONLY from the final Article 1 (and Article 2 if applicable, where actual rates/methods are specified) tables and text. Do not use any information from earlier sections.

2. **HS CODE PROCESSING RULES:**

   문서에 적힌 그대로의 8자리 HS 코드 숫자만 추출한다.

   예: "72251100" → 그대로 "72251100" 저장
   예: "72261100" → "72261100" 저장

   앞에 'ex'가 붙어 있어도:
   - ex는 제거하고
   - 바로 뒤의 숫자 8자리만 추출한다.
   - 예: "ex 7225 11 00" → "72251100"

   **MULTIPLE CN CODES IN ONE SENTENCE:**
   
   If the product definition refers to multiple 8-digit CN codes such as 'CN codes ex 7225 11 00 (...) and ex 7226 11 00 (...)', you must extract ALL 8-digit codes after 'ex' (e.g. 72251100 and 72261100). 
   
   **CRITICAL: Each HS code applies to ALL countries and producers in the table:**
   
   When multiple HS codes (e.g., 72251100 and 72261100) are listed for the same regulation, EACH HS code must be applied to EVERY country/producer combination found in the duty table. This means:
   - If the table has 5 countries and 3 companies, and there are 2 HS codes, you should create 2 × 5 × 3 = 30 items (or appropriate combinations)
   - Each HS code gets its own set of items covering all countries and producers
   - Example: If HS codes 72251100 and 72261100 both apply, and the table shows:
     * Country A, Company X, Rate: 10%
     * Country A, Company Y, Rate: 15%
     * Country B, Company X, Rate: 20%
     Then create:
     * 72251100, Country A, Company X, Rate: 10%
     * 72251100, Country A, Company Y, Rate: 15%
     * 72251100, Country B, Company X, Rate: 20%
     * 72261100, Country A, Company X, Rate: 10%
     * 72261100, Country A, Company Y, Rate: 15%
     * 72261100, Country B, Company X, Rate: 20%
   
   Because each item may only contain ONE hs_code, you must create separate items for each hs_code × country × company combination.
   
   General rule for "ex 0000 00 00" pattern:
   - Remove "ex" prefix
   - Collect the digits and spaces after it, then form an 8-digit number as-is for hs_code
   - Example: "ex 7225 11 00" → "72251100"
   - If multiple "ex 0000 00 00" patterns appear in the same sentence, extract each one separately

   10자리 코드는 무시한다.
   - 예: "7225110011" 같은 10자리 형태는 저장하지 않는다.
   - TARIC codes like "7225 11 00 11", "7225 11 00 15" (10-digit) should be completely ignored and not used as hs_code

   포맷 변경을 절대 하지 않는다.
   - 점(.) 추가하지 않기
   - 공백 제거 이후 숫자만 이어붙이는 정도만 허용
   - 재배열/그룹화 하지 않기

   - ONE hs_code per item - MANDATORY
   - Only 8-digit codes are valid
   - If multiple CN codes are listed for the same regulation/tariff condition, create separate items for EACH hs_code × EACH country × EACH company combination
   - Each HS code must be applied to ALL countries and producers found in the duty/MIP tables

3. **MIP vs AD VALOREM DUTY PROCESSING:**

   EU documents may use two types of duties in the final measures:

   **Ad Valorem Duty (Percentage-based tariff):**
   - Found in Article 1 table under columns like "Rate of duty (%)", "Ad valorem duty", "Duty (%)"
   - Format: "X %" (e.g., "35.6 %")
   - This is the PRIMARY value to read when available
   - Extract as:
     * tariff_type: "Antidumping"
     * tariff_rate: numeric value only (e.g., 35.6)
     * note: null or brief comment like "Ad valorem duty" (optional)

   **MIP (Minimum Import Price):**
   - Found when the document/table mentions "Minimum import price", "MIP", "EUR/tonne"
   - Or when Article 1 states "duty shall be the difference between the MIP of X EUR/tonne and the CIF Union frontier price"
   - For pure MIP cases, set tariff_type = 'Antidumping', tariff_rate = 'MIP', and store the exact MIP text including the numeric value and unit (e.g. 'MIP: 2 043 EUR/tonne') in the note field.
   - Extract as:
     * tariff_type: "Antidumping"
     * tariff_rate: "MIP" (string value)
     * note: Full MIP text as written in the document, including numeric value and unit (e.g., "MIP: 2 043 EUR/tonne" or "MIP: 1 536 EUR/tonne (see Article 1(3))")
   - If a company has both ad valorem duty and MIP mentioned, but Article 1 only imposes one type in the final measures, use ONLY what Article 1 actually imposes (i.e., what is stated in "definitive anti-dumping duty shall be...").
   
   **MIP TABLE CELL MERGING HANDLING:**
   
   When reading MIP (Minimum Import Price) values from tables, if a cell in the MIP column is visually empty because of merged cells, you MUST treat it as having the same MIP value as the last non-empty cell above in the same column. In other words, empty MIP cells should be forward-filled from the previous row.
   
   If the MIP cell in a table row is empty due to merged cells, use the same MIP value as in the last non-empty row above.
   
   **PRODUCT RANGE COLUMN HANDLING:**
   
   In the final duty and MIP tables, if there is a column titled 'Product range' (or very similar wording), you MUST use the text in that column as the product_description for that row. For example, values like 'Products with a maximum core loss not higher than 0,90 W/kg' should be copied directly into product_description. Only if there is no 'Product range' column at all, fall back to using the general product definition from Article 1.
   
   When reading the 'Product range' column in tables, if a cell appears empty due to merged cells, you MUST treat it as having the same value as the last non-empty cell above in the same column. Use this filled value as product_description.
   
   **CRITICAL: MIP TABLE STRUCTURE (especially pages 56-57):**
   
   MIP tables typically span multiple pages (e.g., pages 56-57) and have a specific structure:
   - Column 1: "Product range" (or similar) - contains product descriptions
   - Column 2: "Minimum import price (EUR/tonne)" (or "MIP") - contains numeric values with spaces (e.g., "1 873", "2 043")
   - Additional columns: Company, Country, etc.
   
   When reading MIP tables:
   1. **Product range column**: Read the EXACT text from each row's "Product range" cell. If empty due to merged cells, use the value from the row above.
   2. **MIP price column**: Read the EXACT numeric value including spaces (e.g., "1 873" not "1873", "2 043" not "2043"). Preserve the space formatting as written in the document.
   3. **Note field**: Store as "MIP: [exact value with spaces] EUR/tonne" (e.g., "MIP: 1 873 EUR/tonne", "MIP: 2 043 EUR/tonne")
   4. **Product description**: MUST come from the "Product range" column, NOT from Article 1 or other sections when this column exists in the table.
   
   Pay special attention to tables that span pages 56-57 or similar page ranges, as these often contain the definitive MIP information with Product range details.

4. **COMPANY / COUNTRY SEPARATION RULES:**

   The final duty table under Article 1 typically has columns:
   - "Company" or "Exporting producer"
   - "Country"
   - "TARIC additional code"
   - "Rate of duty (%)" or "Minimum import price (EUR/tonne)" etc.

   Extract based on this table:

   **Basic rules (comma/region/country separation):**

   **company field:**
   - For formats like "CompanyName, City; Country" or "CompanyName, City ,Country", use only the part before the first comma as the company name
   - Example: "Baoshan Iron & Steel Co., Ltd, Shanghai, People's Republic of China"
     → company = "Baoshan Iron & Steel Co., Ltd"
   - Remove city names and country names from the company field
   - Keep only the company/group name

   **country field:**
   - Extract the country name from the same row's "Country" column or from the end of the Company cell
   - Examples: "People's Republic of China", "Japan", "Republic of Korea", "Russian Federation", "United States of America"
   - Put the country name ONLY in the country field, not in the company field
   - ONE country per item - MANDATORY

   **Multiple companies in one cell (semicolon-separated):**

   If the Company cell contains multiple producers separated by ';', you must create one item per producer. For each producer, take the part before the first comma as the company name, and use the same country name for all of them.

   Example:
   "OJSC Novolipetsk Steel, Lipetsk; VIZ Steel, Ekaterinburg, Russian Federation"
   → Create two items:
     * company = "OJSC Novolipetsk Steel", country = "Russian Federation"
     * company = "VIZ Steel", country = "Russian Federation"

   Common rules:
   - For each semicolon-separated chunk, the part before the first comma = company name
   - The country name at the end applies to all companies (e.g., Russian Federation)
   - Split by semicolon → create separate items for each producer
   - Copy the same hs_code, tariff_rate, case_number, etc. for all items (only company differs)

5. **CASE NUMBER / BASIS_LAW PROCESSING:**

   The document title on page 1 always contains:
   "COMMISSION IMPLEMENTING REGULATION (EU) 2022/58 ..."
   (the numbers will vary by document)

   **case_number field:**
   - Extract the regulation number in format "(EU) 2022/58"
   - Pattern: Always "(EU) YYYY/NN" format
   - Store exactly as it appears (e.g., "(EU) 2022/58")

   **basis_law field:**
   - Extract the full regulation name
   - Format: "Commission Implementing Regulation (EU) 2022/58"
   - Use the complete name of the Implementing Regulation

6. **DATES:**

   **effective_date_from / effective_date_to:**
   - effective_date_from: Date when the measure comes into force (from Article 1 or final section)
   - effective_date_to: Expiry date if mentioned (often null for indefinite measures)

   **investigation_period_from / investigation_period_to:**
   
   **CRITICAL**: This information is typically found in the EARLY PAGES of the document (usually within the first 20 pages), often in a section numbered like "1.4." or similar. You MUST search ALL pages for this section.
   
   Find the section whose heading text contains "Review investigation period and period considered" (ignore the numeric prefix like "1.4.", "2.3.", etc.). The heading number may vary across different EU documents, so always search for the exact heading text (case-insensitive). Look for variations like:
   - "Review investigation period and period considered"
   - "Review investigation period"
   - "Investigation period and period considered"
   
   In the first paragraph under this heading, locate the sentence that mentions the investigation period. Common patterns:
   - "The investigation ... covered the period from [DATE1] to [DATE2]"
   - "The review investigation period covered [DATE1] to [DATE2]"
   - "The period of investigation was from [DATE1] to [DATE2]"
   - "covered the period from [DATE1] to [DATE2] ('the review investigation period' or 'RIP')"
   
   Example sentence: "The investigation of a likelihood of continuation or recurrence of dumping covered the period from 1 July 2019 to 30 June 2020 ('the review investigation period' or 'RIP')."
   
   Extract:
   - investigation_period_from = DATE1 (convert to YYYY-MM-DD format)
   - investigation_period_to = DATE2 (convert to YYYY-MM-DD format)
   
   Date format conversion:
   - Documents typically use "day month year" format (e.g., "1 July 2019", "30 June 2020")
   - Always convert to YYYY-MM-DD format for output
   - Examples: "1 July 2019" → "2019-07-01", "30 June 2020" → "2020-06-30"
   - Month names: January=01, February=02, March=03, April=04, May=05, June=06, July=07, August=08, September=09, October=10, November=11, December=12
   
   **APPLY TO ALL ITEMS**: Once you find the investigation period, apply the same investigation_period_from and investigation_period_to values to ALL tariff items extracted from this document.
   
   If the heading "Review investigation period and period considered" (or similar variations) or the period sentence is not found anywhere in the document:
   - investigation_period_from = null
   - investigation_period_to = null

**OUTPUT JSON FORMAT:**

{
  "items": [
    {
      "issuing_country": "Always 'European Union'",
      "country": "Single country name ONLY (e.g. People's Republic of China, Japan, Republic of Korea, Russian Federation, United States of America)",
      "hs_code": "Document-origin 8-digit HS/CN/TARIC code ONLY (e.g. 72251100, 72261100). Remove 'ex', keep only 8-digit numbers, ignore 10-digit TARIC codes. If multiple 'ex 0000 00 00' codes are listed (e.g. ex 7225 11 00 and ex 7226 11 00), create separate items for EACH hs_code × EACH country × EACH company combination. Each HS code must be applied to ALL countries and producers in the table.",
      "tariff_type": "Antidumping or Countervailing or Safeguard",
      "tariff_rate": "number for ad valorem duty (percentage) or the string 'MIP' for minimum import price cases",
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": "Start date of the review investigation period, parsed from the section titled 'Review investigation period and period considered' (format: YYYY-MM-DD) or null if not available",
      "investigation_period_to": "End date of the review investigation period, parsed from the same section (format: YYYY-MM-DD) or null if not available",
      "basis_law": "Full name of EU Regulation (e.g. Commission Implementing Regulation (EU) 2022/58)",
      "company": "Single exporting producer / company name (if multiple producers are listed in one cell, split into multiple items)",
      "case_number": "Regulation number such as (EU) 2022/58",
      "product_description": "Prefer the 'Product range' text from the final duty/MIP tables (with forward-filled values for merged cells). If no 'Product range' column exists, use a short description of the product under measures from the main product definition (e.g. Article 1).",
      "note": "For MIP cases, store the exact MIP value and unit here (e.g. 'MIP: 1 873 EUR/tonne', 'MIP: 2 043 EUR/tonne'). Preserve spaces in numbers as written (e.g., '1 873' not '1873'). If the MIP cell in a table row is empty due to merged cells, use the same MIP value as in the last non-empty row above. For ad valorem duty, you may leave this null or add short comments."
    }
  ]
}

**FINAL REMINDERS:**
- Extract ONLY from the definitive anti-dumping measures section (Article 1 and related tables)
- Ignore all historical explanations, provisional measures, and past MIP descriptions
- ONE hs_code per item, ONE country per item, ONE company per item
- HS codes: Extract 8-digit codes as-is from document (remove 'ex' prefix, remove spaces, but do not add dots or reformat). Ignore 10-digit codes. If multiple 'ex 0000 00 00' patterns appear in one sentence, extract all 8-digit codes and create separate items for EACH hs_code × EACH country × EACH company combination. Each HS code applies to ALL countries and producers in the duty/MIP tables.
- issuing_country = Always "European Union"
- If multiple companies are separated by semicolon in one cell, create multiple items (one per company)
- Ad valorem duty: tariff_rate = percentage number, note = null or brief comment
- Pure MIP: tariff_rate = "MIP" (string), note = full MIP text with numeric value and unit (preserve spaces in numbers, e.g., "MIP: 1 873 EUR/tonne"). If MIP cell is empty due to merged cells, use the MIP value from the last non-empty row above. Product description MUST come from "Product range" column when available in MIP tables.
- Extract case_number from first page title as "(EU) YYYY/NN"
- Extract basis_law as full regulation name
- Output ONLY valid JSON, no explanatory text or markdown
"""


# ============================================================================
# 기본 export (하위 호환성)
# ============================================================================

EUParser = EUTextParser

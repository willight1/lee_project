"""
Tariff Information Extractor v3 - Vision API 버전 (배치 처리)

통합된 국가별 파서 시스템으로 PDF에서 관세 데이터를 추출합니다.
이 버전은 PDF 페이지를 이미지로 만들어 OpenAI Vision 모델에 직접 전달하고,
페이지 수가 많을 경우 여러 번(배치)으로 나눠서 Vision API를 호출합니다.

주요 기능:
- USA 파서: 국가별 분리 처리로 JSON 파싱 오류 해결
- Malaysia 파서: Case Number, Product Description 정확히 추출
- EU 파서: 8자리 HS 코드, 정확한 회사명
- 개선된 데이터베이스 스키마 (issuing_country, investigation_period, product_description)

Usage:
    python tariff_extractor_v3_vision.py                          # 모든 PDF 처리
    python tariff_extractor_v3_vision.py --file=파일명.pdf         # 특정 파일만
    python tariff_extractor_v3_vision.py --file=파일명.pdf --reprocess  # 재처리
"""

import os
import argparse
import json
import re
import base64
import fitz  # PyMuPDF
from dotenv import load_dotenv
from openai import OpenAI
from typing import Dict, List, Tuple
from PIL import Image, ImageEnhance, ImageFilter
import io

from database import TariffDatabase

# 환경 변수 로드
load_dotenv()

# 기본 설정
INPUT_FOLDER = "PDF"
DB_PATH = "tariff_data.db"

# ⭐ 적절한 밸런스 모드 (비용 vs 정확도 균형)
BATCH_PAGE_LIMIT = 10  # 적당한 배치 크기 (저비용:20, 고비용:10)
HIGH_QUALITY_DPI = 200  # 균형잡힌 해상도 (저비용:150, 고비용:300)


# ============================================================================
# BASE PARSER CLASS (Vision API 사용)
# ============================================================================

class BaseCountryParser:
    """Base class for country-specific parsers (Vision API 기반)"""

    def __init__(self, client: OpenAI):
        self.client = client
        # ⭐ 최고 성능 Vision 모델 유지
        self.model_name = "gpt-4o"  # 최신 Vision 모델 (변경 안 함)

    # ----------------------------------------------------------------------
    # PDF → 이미지(Base64) 변환 + 전처리
    # ----------------------------------------------------------------------
    def enhance_image(self, img_bytes: bytes) -> bytes:
        """
        ⭐ 밸런스 모드: 적절한 이미지 품질 향상
        - 선명도 약간 증가
        - 대비 약간 향상
        """
        try:
            # PIL Image로 변환
            img = Image.open(io.BytesIO(img_bytes))

            # 1. 선명도 향상 (Sharpness) - 적절한 강도
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.2)  # 20% 증가

            # 2. 대비 향상 (Contrast) - 적절한 강도
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.15)  # 15% 증가

            # PNG로 다시 변환 (노이즈 제거는 생략 - 속도 향상)
            output = io.BytesIO()
            img.save(output, format='PNG', optimize=True)
            return output.getvalue()

        except Exception as e:
            print(f"  ⚠ Image enhancement failed: {e}, using original")
            return img_bytes

    def get_pdf_page_images(
        self,
        pdf_path: str,
        dpi: int = HIGH_QUALITY_DPI,  # ⭐ 200 DPI 균형 해상도
        max_pages: int = None,
        enhance: bool = True  # ⭐ 적절한 이미지 전처리
    ) -> List[Tuple[int, str]]:
        """
        PDF를 열고 각 페이지를 PNG 이미지(Base64)로 변환.
        ⭐ 밸런스 모드: 200 DPI + 적절한 전처리
        반환: [(page_num, base64_png_str), ...]
        """
        try:
            doc = fitz.open(pdf_path)
            page_images: List[Tuple[int, str]] = []

            for page_index, page in enumerate(doc):
                page_num = page_index + 1
                if max_pages is not None and page_num > max_pages:
                    break

                # 고해상도 변환
                pix = page.get_pixmap(dpi=dpi)
                img_bytes = pix.tobytes("png")

                # ⭐ 이미지 품질 향상
                if enhance:
                    img_bytes = self.enhance_image(img_bytes)

                b64 = base64.b64encode(img_bytes).decode("utf-8")
                page_images.append((page_num, b64))

            doc.close()

            if not page_images:
                print("  ✗ No pages/images extracted from PDF")
            else:
                print(f"  ✓ Extracted {len(page_images)} pages as high-quality images (DPI: {dpi})")

            return page_images

        except Exception as e:
            print(f"  ✗ Error extracting images from PDF: {e}")
            return []

    # ----------------------------------------------------------------------
    # (옵션) 텍스트 스니펫 추출 - USA country 탐지용 등
    # ----------------------------------------------------------------------
    def extract_text_snippet(
        self,
        pdf_path: str,
        max_chars: int = 15000
    ) -> str:
        """
        PDF에서 간단히 텍스트만 추출 (Vision 모델용이 아니라,
        국가 리스트 추출 등 보조 용도에만 사용)
        """
        try:
            doc = fitz.open(pdf_path)
            texts = []
            for page in doc:
                t = page.get_text()
                if t:
                    texts.append(t)
                if sum(len(x) for x in texts) > max_chars:
                    break
            doc.close()
            full_text = "\n".join(texts)
            if len(full_text) > max_chars:
                return full_text[:max_chars]
            return full_text
        except Exception as e:
            print(f"  ⚠ Error extracting text snippet: {e}")
            return ""

    # ----------------------------------------------------------------------
    # Vision API 호출
    # ----------------------------------------------------------------------
    def call_vision_api(
        self,
        instruction: str,
        page_images_b64: List[str],
        max_retries: int = 3  # ⭐ 적절한 재시도 횟수
    ) -> str:
        """
        Vision 모델에 텍스트 + 이미지(Base64) 리스트를 전달.
        instruction: 추출 규칙/포맷 설명 텍스트
        page_images_b64: 각 페이지의 PNG Base64 문자열 리스트
        """
        for attempt in range(max_retries):
            try:
                content = [
                    {
                        "type": "text",
                        "text": instruction
                    }
                ]

                for b64 in page_images_b64:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64}"
                            }
                        }
                    )

                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a precise data extraction assistant. "
                                "Always output complete, valid JSON only. "
                                "Never truncate your response. "
                                "Extract ALL information with maximum accuracy. "
                                "Double-check all HS codes, company names, and rates."
                            ),
                        },
                        {
                            "role": "user",
                            "content": content,
                        },
                    ],
                    max_completion_tokens=16000,  # ⭐ 적절한 토큰 수
                    temperature=0.1,  # ⭐ 거의 결정적
                )

                response_text = response.choices[0].message.content.strip()

                # 코드 블럭 제거
                if response_text.startswith("```"):
                    lines = response_text.split('\n')
                    lines = lines[1:]  # ```json 또는 ``` 제거
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]  # 마지막 ``` 제거
                    response_text = '\n'.join(lines).strip()

                return response_text

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  ⚠ Vision API attempt {attempt + 1} failed, retrying...")
                else:
                    print(f"  ✗ Vision API error after {max_retries} attempts: {e}")
                    return ""

        return ""

    # ----------------------------------------------------------------------
    # 파서별 프롬프트 (텍스트만) - 서브클래스에서 구현
    # ----------------------------------------------------------------------
    def create_extraction_prompt(self) -> str:
        """Create extraction instruction prompt - to be overridden by subclasses"""
        raise NotImplementedError("Subclasses must implement create_extraction_prompt")

    # ----------------------------------------------------------------------
    # JSON 파싱
    # ----------------------------------------------------------------------
    def parse_response(self, response: str) -> List[Dict]:
        """Parse JSON response with robust error handling"""
        if not response:
            return []

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
            else:
                first_brace = response.find('{')
                last_brace = response.rfind('}')
                if first_brace != -1 and last_brace != -1:
                    response = response[first_brace:last_brace+1]

        # 앞뒤 잡다한 텍스트 제거
        response = response.strip()
        if not response.startswith('{'):
            first_brace = response.find('{')
            if first_brace != -1:
                response = response[first_brace:]

        # 닫기 전에 붙은 콤마 제거
        response = re.sub(r',(\s*[}\]])', r'\1', response)

        # 중괄호/대괄호 짝 맞추기
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
            items = data.get('items', [])
            print(f"    ✓ Parsed {len(items)} items successfully")
            return items
        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON decode error: {e}")

            # items 배열에서 개별 object만 복구 시도
            try:
                items_match = re.search(
                    r'"items"\s*:\s*\[(.*)\]',
                    response,
                    re.DOTALL
                )
                if items_match:
                    items_str = items_match.group(1)

                    partial_items = []
                    depth = 0
                    current_item = ""
                    in_string = False
                    escape_next = False

                    for char in items_str:
                        if escape_next:
                            current_item += char
                            escape_next = False
                            continue

                        if char == '\\':
                            escape_next = True
                            current_item += char
                            continue

                        if char == '"' and not escape_next:
                            in_string = not in_string

                        if not in_string:
                            if char == '{':
                                depth += 1
                            elif char == '}':
                                depth -= 1

                        current_item += char

                        if depth == 0 and current_item.strip().endswith('}'):
                            try:
                                item = json.loads(
                                    current_item.strip().rstrip(',')
                                )
                                partial_items.append(item)
                                current_item = ""
                            except Exception:
                                pass

                    if partial_items:
                        print(
                            f"    ✓ Recovered {len(partial_items)} items "
                            f"from partial JSON"
                        )
                        return partial_items

            except Exception as recover_error:
                print(f"  ⚠ Could not recover partial data: {recover_error}")

            return []

    # ----------------------------------------------------------------------
    # 기본 process: 여러 배치로 나눠서 Vision에 전달
    # ----------------------------------------------------------------------
    def process(self, pdf_path: str) -> List[Dict]:
        """
        Process PDF and return extracted items via Vision API.

        - 전체 페이지 이미지를 뽑은 뒤
        - BATCH_PAGE_LIMIT 단위로 쪼개서 여러 번 Vision 호출
        - 각 응답의 items를 합쳐서 반환

        ※ 전 페이지 다 처리함. 앞 20페이지만 보는 거 아님.
        """
        page_imgs = self.get_pdf_page_images(pdf_path)
        if not page_imgs:
            return []

        instruction = self.create_extraction_prompt()
        all_items: List[Dict] = []

        total_pages = len(page_imgs)
        for start in range(0, total_pages, BATCH_PAGE_LIMIT):
            end = min(start + BATCH_PAGE_LIMIT, total_pages)
            batch = page_imgs[start:end]
            batch_page_nums = [p for p, _ in batch]
            print(f"  ▶ Vision batch pages {batch_page_nums[0]}–{batch_page_nums[-1]}")

            b64_list = [b64 for _, b64 in batch]
            response = self.call_vision_api(instruction, b64_list)

            if not response:
                print("  ⚠ Empty response for this batch, skipping.")
                continue

            try:
                items = self.parse_response(response)
                if items:
                    all_items.extend(items)
                    print(f"  ✓ Batch {batch_page_nums[0]}–{batch_page_nums[-1]}: {len(items)} items")
                else:
                    print(f"  ⚠ Batch {batch_page_nums[0]}–{batch_page_nums[-1]}: no items found")
            except Exception as e:
                print(f"  ✗ Error parsing batch {batch_page_nums[0]}–{batch_page_nums[-1]}: {e}")
                continue

        print(f"  ➜ Total items from all batches: {len(all_items)}")
        return all_items


# ============================================================================
# DEFAULT PARSER
# ============================================================================

class DefaultParser(BaseCountryParser):
    """Default parser for other countries (Vision 기반)"""

    def create_extraction_prompt(self) -> str:
        """Create default extraction prompt (Vision용)"""
        return """You are given a trade remedy / tariff PDF document as a sequence of page images.

Extract tariff/trade remedy information from the document pages.

**CRITICAL INSTRUCTIONS:**

1. **HS Code Separation - MANDATORY:**
   - If multiple HS codes are listed (e.g., "7208.10.00, 7208.25.00, 7208.36.00"), create SEPARATE items for EACH HS code
   - DO NOT combine multiple HS codes into one item
   - Example: If 3 HS codes → create 3 separate items

2. **Country Separation - MANDATORY:**
   - If multiple countries are listed (e.g., "China, Korea, Taiwan"), create SEPARATE items for EACH country
   - DO NOT combine multiple countries into one item
   - Example: If 3 countries → create 3 separate items

3. **Combination Rule:**
   - If you have 3 HS codes AND 2 countries → create 6 items (3 × 2)
   - Each item should have exactly ONE hs_code and ONE country

4. **Company Handling:**
   - If multiple companies are listed, create separate items for each company
   - All-others or "All Other Producers" can be one item

5. **Use ALL PAGE IMAGES:**
   - Read all attached page images carefully.
   - Use tables, headers, footers, and any notes that provide HS codes, tariff rates, company names, periods, etc.

OUTPUT JSON FORMAT:

{
  "items": [
    {
      "country": "Single country name ONLY",
      "hs_code": "Single HS code ONLY (e.g., 7208.10.00)",
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
- ONE hs_code per item (NOT "code1, code2, code3")
- ONE country per item (NOT "China, Korea, Taiwan")
- Create ALL combinations: each HS code × each country × each company
- Use ONLY the information visible in the attached page images.
- Output ONLY JSON, no explanatory text.
"""


# ============================================================================
# MALAYSIA PARSER
# ============================================================================

class MalaysiaParser(BaseCountryParser):
    """Parser for Malaysia trade remedy documents (Vision 기반)"""

    def create_extraction_prompt(self) -> str:
        """Create Malaysia-specific extraction prompt (Vision용)"""
        return """You are given a Malaysia government trade remedy PDF as page images.

Extract tariff/trade remedy information from these pages.

**CRITICAL RULES:**

1. **Case Number from Page Header**:
   - Look in the TOP RIGHT corner of each page header.
   - Format: P.U. (A) XX (e.g., P.U. (A) 197, P.U. (A) 23).
   - This is MANDATORY for Malaysia documents.
   - Use the same P.U. (A) number for all items in this document, unless clearly different for some pages.

2. **Product Description - Separate Field**:
   - Find the "Description of goods" section (often in a table).
   - Extract the FULL text of the description of goods.
   - Put it in the product_description field (NOT in note field).
   - Example: "Cold rolled stainless steel in coils, sheets or any other form with the thickness of not more than 6.5 millimeters..."

3. **HS Codes - SEPARATE Items**:
   - Malaysia uses 8 or 10-digit HS codes.
   - Format example: 7219.31.00 or 7220.20.10.
   - If multiple HS codes are listed, create SEPARATE item for EACH HS code.
   - DO NOT combine HS codes in one item.

4. **Multiple Countries - SEPARATE Items**:
   - Malaysia documents often cover multiple target countries.
   - Example: Indonesia, Vietnam, People's Republic of China.
   - If multiple countries are listed, create SEPARATE item for EACH country.
   - DO NOT combine countries in one item.
   - Create separate items for each country–company–HS code combination.

5. **Issuing Country**:
   - This is a MALAYSIA document.
   - The "country" field = TARGET country (Indonesia, Vietnam, etc.), NOT Malaysia.

6. **Tariff Type and Rate**:
   - Usually antidumping duties.
   - Extract exact duty rate for each company or group (e.g., 7.73%).

OUTPUT JSON:

{
  "items": [
    {
      "country": "Target country (Indonesia, Vietnam, People's Republic of China, etc.)",
      "hs_code": "HS code (8 or 10 digits)",
      "tariff_type": "Antidumping",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": null,
      "investigation_period_to": null,
      "basis_law": "Order name (e.g., Customs (Anti-Dumping Duties) Order 2021)",
      "company": "Company name or 'Others'",
      "case_number": "P.U. (A) number from page header",
      "product_description": "FULL description of goods",
      "note": null
    }
  ]
}

**IMPORTANT**:
- Case number MUST be extracted from the page header.
- Product description goes in product_description field.
- ONE hs_code per item (SEPARATE items for each HS code).
- ONE country per item (SEPARATE items for each country).
- Create items for ALL combinations: each HS code × each country × each company.
- Use ONLY the information visible in the page images.
- Output ONLY JSON, no explanatory text.
"""


# ============================================================================
# EU PARSER
# ============================================================================

class EUParser(BaseCountryParser):
    """Parser for EU trade remedy documents (Vision 기반)"""

    def create_extraction_prompt(self) -> str:
        """Create EU-specific extraction prompt (Vision용)"""
        return """You are given an EU trade remedy regulation PDF as page images.

Extract antidumping information from the document pages.

**CRITICAL RULES:**

1. **HS Codes - Use 8 Digits WITHOUT dots - SEPARATE Items**:
   - EU uses 8-digit HS codes.
   - The document may show them as "7225 11 00" or with spaces/dots.
   - Convert them to 8-digit codes without dots or spaces, e.g.:
     - "7225 11 00" → "72251100"
     - "7226 11 00" → "72261100"
   - If multiple HS codes are listed, create SEPARATE item for EACH HS code.
   - DO NOT combine multiple HS codes into one item.

2. **Company Names - EXACT as written**:
   - Use FULL official company names from the tables (often near the end).
   - Examples (from typical EU GOES regulation):
     - "OJSC Novolipetsk Steel"
     - "PJSC Severstal"
     - "Nippon Steel Corporation (formerly Nippon Steel & Sumitomo Metal Corporation)"
     - "Baoshan Iron & Steel Co., Ltd."
     - "Wuhan Iron and Steel Co., Ltd."
   - Also create an item for "All other companies" or similar wording for each country.

3. **Tariff Rates from Tables**:
   - Look in the tables listing companies and duty rates.
   - Extract EXACT rates: e.g., 21.5%, 35.9%, 39.0%, 22.0%, etc.
   - Different companies have different rates.

4. **Multiple Countries - SEPARATE Items**:
   - Countries often include:
     - "People's Republic of China"
     - "Japan"
     - "Republic of Korea"
     - "Russian Federation"
     - "United States"
   - If multiple countries appear, create SEPARATE sets of items for EACH country.
   - DO NOT combine countries in one item.
   - Create items for each country × company × HS code.

5. **Country Names**:
   - Use official names:
     - "People's Republic of China"
     - "Japan"
     - "Republic of Korea"
     - "Russian Federation"
     - "United States"

6. **Product Description**:
   - For this type of regulation, the product is often grain-oriented electrical steel.
   - Use a concise but clear description like:
     - "Grain-oriented silicon-electrical steel"
   - If a more precise description is given in the document, use that.

OUTPUT JSON:

{
  "items": [
    {
      "country": "People's Republic of China / Japan / Republic of Korea / Russian Federation / United States",
      "hs_code": "8-digit code (e.g., 72251100 or 72261100)",
      "tariff_type": "Antidumping",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": null,
      "investigation_period_to": null,
      "basis_law": "Regulation number (e.g., Commission Implementing Regulation (EU) ...)",
      "company": "FULL company name or 'All Other Companies'",
      "case_number": null,
      "product_description": "Grain-oriented silicon-electrical steel",
      "note": null
    }
  ]
}

**IMPORTANT**:
- Extract ALL companies from the rate tables.
- Use 8-digit HS codes WITHOUT dots or spaces.
- Use FULL company names exactly as written.
- ONE hs_code per item.
- ONE country per item.
- Create items for ALL combinations: each HS code × each country × each company.
- Use ONLY the information visible in the attached page images.
- Output ONLY JSON.
"""


# ============================================================================
# USA PARSER (Vision + country-by-country 처리)
# ============================================================================

class USAParser(BaseCountryParser):
    """Parser for USA trade remedy documents (Vision 기반, country-by-country)"""

    def process(self, pdf_path: str) -> List[Dict]:
        """
        Process USA PDF with country-by-country extraction using Vision.

        - 텍스트 스니펫으로 문서에 나오는 국가 리스트 추출 (_extract_countries)
        - 전체 페이지 이미지를 Vision 모델에 전달하되,
          각 국가별로 instruction만 바꿔가며 여러 번 호출
        """
        # 1) PDF 페이지 이미지 (전 페이지)
        page_imgs = self.get_pdf_page_images(pdf_path)
        if not page_imgs:
            return []

        b64_list_all = [b64 for _, b64 in page_imgs]

        # 2) 텍스트 스니펫으로 국가 추출
        text_snippet = self.extract_text_snippet(pdf_path, max_chars=15000)
        countries = self._extract_countries(text_snippet)
        print(f"  Found {len(countries)} countries: {', '.join(countries)}")

        # 3) 각 국가별로 Vision 호출
        all_items: List[Dict] = []

        for country in countries:
            print(f"  Processing {country}...")
            instruction = self.create_country_specific_prompt(country)

            # 미국 문서도 길 수 있으니, 여기에서도 배치 처리 사용
            total_pages = len(b64_list_all)
            country_items: List[Dict] = []
            for start in range(0, total_pages, BATCH_PAGE_LIMIT):
                end = min(start + BATCH_PAGE_LIMIT, total_pages)
                batch_b64 = b64_list_all[start:end]
                print(f"    ▶ {country} batch pages {start+1}–{end}")

                response = self.call_vision_api(instruction, batch_b64)
                if not response:
                    print("    ⚠ Empty response for this batch, skipping.")
                    continue

                try:
                    items = self.parse_response(response)
                    if items:
                        country_items.extend(items)
                        print(f"    ✓ {country} batch {start+1}–{end}: {len(items)} items")
                    else:
                        print(f"    ⚠ {country} batch {start+1}–{end}: no items found")
                except Exception as e:
                    print(f"    ✗ Error parsing {country} batch {start+1}–{end}: {e}")
                    continue

            print(f"  ➜ {country}: total {len(country_items)} items")
            all_items.extend(country_items)

        print(f"  ➜ USA total items: {len(all_items)}")
        return all_items

    # ------------------------------------------------------------------
    # 국가 리스트 추출 (텍스트 스니펫 사용)
    # ------------------------------------------------------------------
    def _extract_countries(self, text: str) -> List[str]:
        """Extract list of countries from the document snippet"""
        countries = set()

        if not text:
            print("  No text snippet available, using 'Unknown'")
            return ['Unknown']

        search_text = text[:15000]

        known_countries = [
            'Republic of Korea', 'Korea',
            "People's Republic of China", 'China',
            'Brazil', 'India', 'Vietnam', 'Thailand',
            'Japan', 'Taiwan', 'Indonesia', 'Malaysia',
            'Turkey', 'Mexico', 'Canada', 'Italy', 'Germany',
            'France', 'Russia', 'Russian Federation', 'Ukraine'
        ]

        for country in known_countries:
            pattern = rf'from\s+(?:the\s+)?{re.escape(country)}[\s:,]'
            if re.search(pattern, search_text, re.IGNORECASE):
                if country.lower() == 'korea':
                    countries.add('Republic of Korea')
                elif country.lower() == 'china':
                    countries.add("People's Republic of China")
                elif country.lower() == 'russia':
                    countries.add('Russian Federation')
                else:
                    countries.add(country)

        countries_list = list(countries)

        if countries_list:
            print(f"  Found countries: {', '.join(countries_list)}")
        else:
            print("  No countries found, using 'Unknown'")
            countries_list = ['Unknown']

        return countries_list

    # ------------------------------------------------------------------
    # 국가별 Vision 프롬프트
    # ------------------------------------------------------------------
    def create_country_specific_prompt(self, country: str) -> str:
        """Create prompt for extracting data for a specific country (Vision용)"""
        return f"""You are given a United States Department of Commerce / ITC trade remedy PDF as page images.

Extract tariff data for **{country} ONLY** from this document.

**CRITICAL INSTRUCTIONS:**

1. **Target Country**:
   - Extract data ONLY for "{country}".
   - Ignore all other countries completely.

2. **HS Code List - MANDATORY - SEPARATE Items**:
   - Find the SCOPE section.
   - Look for wording like:
     "The products subject to this order are currently classified under the Harmonized Tariff Schedule of the United States (HTSUS) under item numbers:"
   - There may be many HS codes (often 10-digit codes, e.g., 7208.10.1500, 7208.10.3000, etc.).
   - Extract ALL HS codes from that list.
   - Create a SEPARATE item for EACH HS code.
   - DO NOT combine multiple HS codes into one item.

3. **Company & Rate Table**:
   - Find the tables that list companies and dumping/countervailing duty rates for {country}.
   - Extract:
     - Full company name (no abbreviations)
     - Exact rate (e.g., 7.33%)

4. **Dates**:
   - Use the document to identify:
     - "Effective Date" or date of order publication → effective_date_from
     - "Period of Investigation" or "Period of Review" → investigation_period_from / investigation_period_to
   - If some dates are not clearly indicated, set them to null.

5. **Cash Deposit Requirements**:
   - If there is a separate "Cash Deposit Requirements" section, ignore it.
   - Extract only the final determination rates / final duty rates for {country}.

6. **Combination Rule for USA**:
   - For {country}, if there are N HS codes in the SCOPE list and M companies in the rate table:
     - Create N × M items for this country.
     - Each item must have exactly:
       - ONE hs_code
       - ONE company
       - ONE country ({country})
     - Example: 3 companies × 49 HS codes = 147 items.

7. **Output Format**:
   - Follow this JSON structure exactly.

OUTPUT JSON:

{{
  "items": [
    {{
      "country": "{country}",
      "hs_code": "10-digit HSUS code from the SCOPE list (e.g., 7208.10.1500)",
      "tariff_type": "Antidumping or Countervailing",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": null,
      "investigation_period_from": "YYYY-MM-DD or null",
      "investigation_period_to": "YYYY-MM-DD or null",
      "basis_law": "Order / case title from the first pages (e.g., 'Certain Hot-Rolled Steel Flat Products from ...')",
      "company": "Full company name (exactly as written in the rate table)",
      "case_number": "A-XXX-XXX or C-XXX-XXX, etc., if visible on the first pages",
      "product_description": "Short description of the product scope",
      "note": null
    }}
  ]
}}

**CRITICAL**:
- Extract ALL HS codes from the SCOPE section.
- Use only the companies and rates for {country}.
- ONE hs_code per item.
- ONE company per item.
- ONE country per item (“{country}”).
- Create items for ALL combinations: each HS code × each company for {country}.
- Use ONLY information visible in the page images.
- Output ONLY JSON, no explanatory text.
"""

    # USAParser는 country-specific 프롬프트를 쓰기 때문에
    # create_extraction_prompt는 사용하지 않지만 인터페이스 상 구현
    def create_extraction_prompt(self) -> str:
        return ""


# ============================================================================
# PARSER FACTORY
# ============================================================================

class ParserFactory:
    """Factory to create appropriate parser based on document"""

    @staticmethod
    def create_parser(file_name: str, client: OpenAI) -> BaseCountryParser:
        """Create parser based on file name"""
        file_name_upper = file_name.upper()

        if 'USA_' in file_name_upper or 'US_' in file_name_upper:
            print("  Using USA Parser (country-by-country processing, Vision API)")
            return USAParser(client)
        elif 'MALAYSIA_' in file_name_upper:
            print("  Using Malaysia Parser (Vision API)")
            return MalaysiaParser(client)
        elif 'EU_' in file_name_upper:
            print("  Using EU Parser (Vision API)")
            return EUParser(client)
        else:
            print("  Using Default Parser (Vision API)")
            return DefaultParser(client)

    @staticmethod
    def detect_issuing_country(file_name: str) -> str:
        """Detect issuing country from file name"""
        file_name_upper = file_name.upper()

        if 'USA_' in file_name_upper or 'US_' in file_name_upper:
            return "United States"
        elif 'MALAYSIA_' in file_name_upper:
            return "Malaysia"
        elif 'EU_' in file_name_upper:
            return "European Union"
        elif 'BRAZIL_' in file_name_upper:
            return "Brazil"
        elif 'AUSTRALIA_' in file_name_upper:
            return "Australia"
        elif 'PAKISTAN_' in file_name_upper:
            return "Pakistan"
        elif 'INDIA_' in file_name_upper:
            return "India"
        elif 'TURKEY_' in file_name_upper:
            return "Turkey"
        elif 'CANADA_' in file_name_upper:
            return "Canada"
        else:
            return "Unknown"


# ============================================================================
# TARIFF EXTRACTOR
# ============================================================================

class TariffExtractor:
    """Main tariff extractor with country-specific parsers (Vision 버전)"""

    def __init__(self, db: TariffDatabase):
        self.db = db

        # Initialize OpenAI client
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        self.client = OpenAI(api_key=api_key)

    def process_single_pdf(self, pdf_path: str) -> bool:
        """Process a single PDF file"""
        file_name = os.path.basename(pdf_path)
        print(f"\n{'='*80}")
        print(f"Processing: {file_name}")
        print('='*80)

        # 발행국 추론
        issuing_country = ParserFactory.detect_issuing_country(file_name)
        print(f"  Issuing country: {issuing_country}")

        # 파일 정보
        file_size = os.path.getsize(pdf_path)

        # 파서 생성
        parser = ParserFactory.create_parser(file_name, self.client)

        # Vision으로 아이템 추출
        print(f"  Extracting tariff information with Vision API...")
        items = parser.process(pdf_path)

        if not items:
            print(f"  ⚠ No tariff items found")
            return False

        # 페이지 수
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        doc.close()

        # documents 테이블에 기록
        doc_id = self.db.insert_document(
            file_name=file_name,
            file_path=pdf_path,
            issuing_country=issuing_country,
            total_pages=total_pages,
            file_size=file_size,
            processing_mode="v3_vision_batch"
        )

        if not doc_id:
            print(f"  ✗ Failed to insert document record")
            return False

        # 기존 아이템 삭제 후 새로 삽입
        self.db.delete_tariff_items_by_doc(doc_id)

        for item in items:
            self.db.insert_tariff_item(doc_id, item)

        print(f"  ✓ Successfully processed: {len(items)} tariff items")
        return True

    def process_folder(self, input_folder: str):
        """Process all PDF files in folder"""
        if not os.path.exists(input_folder):
            print(f"✗ Input folder not found: {input_folder}")
            return

        pdf_files = sorted(
            [f for f in os.listdir(input_folder) if f.lower().endswith('.pdf')]
        )

        if not pdf_files:
            print(f"✗ No PDF files found in {input_folder}")
            return

        print(f"\n{'='*80}")
        print(f"Found {len(pdf_files)} PDF files")
        print(f"{'='*80}")

        successful = 0
        failed = []

        for i, pdf_file in enumerate(pdf_files, 1):
            print(f"\n[{i}/{len(pdf_files)}]")
            pdf_path = os.path.join(input_folder, pdf_file)
            try:
                if self.process_single_pdf(pdf_path):
                    successful += 1
                else:
                    failed.append(pdf_file)
            except Exception as e:
                print(f"  ✗ Error processing {pdf_file}: {e}")
                failed.append(pdf_file)

        print(f"\n{'='*80}")
        print(f"Processing Complete")
        print(f"{'='*80}")
        print(f"Successfully processed: {successful}/{len(pdf_files)} files")
        if failed:
            print(f"\nFailed files:")
            for f in failed:
                print(f"  - {f}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main execution"""
    parser = argparse.ArgumentParser(
        description='Tariff Information Extractor v3 - Vision-based Modular Parser System (batch)'
    )
    parser.add_argument(
        '--input',
        default=INPUT_FOLDER,
        help=f'Input folder containing PDF files (default: {INPUT_FOLDER})'
    )
    parser.add_argument(
        '--file',
        type=str,
        default=None,
        help='Process only this specific PDF file'
    )
    parser.add_argument(
        '--reprocess',
        action='store_true',
        help='Delete existing data before reprocessing'
    )

    args = parser.parse_args()

    print("="*80)
    print("Tariff Information Extractor v3 (Vision API, Batching)")
    print("Modular Country-Specific Parser System with Page Images")
    print("="*80)
    print("\nParsers available:")
    print("  - USA Parser (country-by-country processing, Vision)")
    print("  - Malaysia Parser (case number + product description, Vision)")
    print("  - EU Parser (8-digit HS codes + exact company names, Vision)")
    print("  - Default Parser (for other countries, Vision)")
    print("="*80)

    # DB 초기화
    db = TariffDatabase(DB_PATH)

    # Extractor 생성
    try:
        extractor = TariffExtractor(db)
    except ValueError as e:
        print(f"\n✗ Error: {e}")
        print("\nPlease set OPENAI_API_KEY in .env file")
        return

    # PDF 처리
    if args.file:
        pdf_path = os.path.join(args.input, args.file)
        if not os.path.exists(pdf_path):
            print(f"✗ File not found: {pdf_path}")
            return

        # 재처리 옵션이면 기존 데이터 삭제
        if args.reprocess:
            db.cursor.execute(
                "SELECT doc_id FROM documents WHERE file_name = ?",
                (args.file,)
            )
            result = db.cursor.fetchone()
            if result:
                doc_id = result[0]
                print(f"\n✓ Deleting existing data for {args.file}")
                db.delete_tariff_items_by_doc(doc_id)
                db.cursor.execute(
                    "DELETE FROM documents WHERE doc_id = ?",
                    (doc_id,)
                )
                db.conn.commit()

        extractor.process_single_pdf(pdf_path)
    else:
        extractor.process_folder(args.input)

    # 통계 출력
    stats = db.get_stats()
    print(f"\n{'='*80}")
    print("Database Statistics")
    print(f"{'='*80}")
    print(f"Total documents: {stats['total_documents']}")
    print(f"Total tariff items: {stats['total_tariff_items']}")

    if stats.get('by_issuing_country'):
        print(f"\nBy issuing country:")
        for country, count in stats['by_issuing_country'].items():
            print(f"  {country}: {count} documents")

    print(f"\nDatabase: {DB_PATH}")
    print(f"{'='*80}")

    db.close()


if __name__ == "__main__":
    main()

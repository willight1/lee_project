"""
Default Text Parser for all countries
모든 국가에 대한 기본 텍스트 파서
"""

import base64
import fitz  # PyMuPDF
from typing import Dict, List

from .base_parser import TextBasedParser


def extract_text_from_pdf(pdf_path: str, max_pages: int = None) -> str:
    """
    PyMuPDF로 PDF에서 텍스트 직접 추출 (무료, 빠름)
    이미지 기반 PDF는 Vision API 폴백
    """
    try:
        doc = fitz.open(pdf_path)
        texts = []

        total_pages = len(doc)
        pages_to_process = min(total_pages, max_pages) if max_pages else total_pages

        print(f"  📄 Extracting text from {pages_to_process} pages...")

        for page_num, page in enumerate(doc):
            if max_pages and page_num >= max_pages:
                break

            text = page.get_text()
            if text.strip():
                texts.append(f"\n--- PAGE {page_num + 1} ---\n{text}")

            # 진행 상황 표시
            if (page_num + 1) % 20 == 0:
                print(f"    → Processed {page_num + 1}/{pages_to_process} pages")

        doc.close()

        full_text = "\n".join(texts)

        # ⭐ 이미지 기반 PDF 감지
        if len(full_text) < 100:
            print(f"  ⚠ Text extraction failed ({len(full_text)} chars) - Image-based PDF detected")
            print(f"  → Falling back to Vision API for image-based PDF...")
            return None  # Vision API로 처리하도록 신호

        print(f"  ✓ Extracted {len(full_text):,} characters from {pages_to_process} pages")
        return full_text

    except Exception as e:
        print(f"  ✗ Error extracting text: {e}")
        return None


class DefaultTextParser(TextBasedParser):
    """기본 텍스트 파서 (모든 국가)"""

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the document text.

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
- Output ONLY JSON, no explanatory text.
"""

    def process_image_pdf_with_vision(self, pdf_path: str) -> List[Dict]:
        """
        이미지 기반 PDF를 Vision API로 처리
        텍스트 추출 실패 시 폴백
        """
        print(f"  🖼️  Processing image-based PDF with Vision API...")

        try:
            doc = fitz.open(pdf_path)
            all_items = []

            # 페이지를 배치로 처리 (비용 절감)
            batch_size = 10
            total_pages = len(doc)

            for start in range(0, total_pages, batch_size):
                end = min(start + batch_size, total_pages)
                print(f"  ▶ Vision batch pages {start+1}–{end}")

                # 이미지로 변환
                images_b64 = []
                for page_num in range(start, end):
                    page = doc[page_num]
                    pix = page.get_pixmap(dpi=150)  # 저해상도로 비용 절감
                    img_bytes = pix.tobytes("png")
                    b64 = base64.b64encode(img_bytes).decode("utf-8")
                    images_b64.append(b64)

                # Vision API 호출
                content = [{"type": "text", "text": self.create_extraction_prompt()}]
                for b64 in images_b64:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}
                    })

                try:
                    response = self.client.chat.completions.create(
                        model=self.vision_model,
                        messages=[
                            {"role": "system", "content": "You are a precise data extraction assistant. Always output complete, valid JSON only."},
                            {"role": "user", "content": content}
                        ],
                        max_tokens=16000,
                        temperature=0.1
                    )

                    response_text = response.choices[0].message.content.strip()
                    items = self.parse_response(response_text)
                    all_items.extend(items)
                    print(f"  ✓ Batch {start+1}–{end}: {len(items)} items")

                except Exception as e:
                    print(f"  ✗ Vision API error for batch {start+1}–{end}: {e}")
                    continue

            doc.close()
            print(f"  ➜ Total items from Vision API: {len(all_items)}")
            return all_items

        except Exception as e:
            print(f"  ✗ Image processing error: {e}")
            return []

    def process(self, pdf_path: str) -> List[Dict]:
        """PDF에서 텍스트 추출 후 LLM으로 파싱"""
        # 1. 텍스트 추출 시도 (무료)
        text = extract_text_from_pdf(pdf_path)

        # 2. 이미지 기반 PDF면 Vision API 사용
        if text is None or len(text) < 100:
            print(f"  💡 Switching to Vision API for image-based PDF")
            return self.process_image_pdf_with_vision(pdf_path)

        if not text:
            return []

        # 2. 텍스트가 너무 길면 배치로 나누기
        max_chars = 100000  # 약 25,000 토큰
        all_items = []

        if len(text) > max_chars:
            print(f"  📊 Text too long ({len(text):,} chars), splitting into batches...")

            # 페이지 단위로 분할
            pages = text.split("\n--- PAGE ")
            batch_text = ""
            batch_num = 1

            for page in pages:
                if not page.strip():
                    continue

                page_text = "--- PAGE " + page if batch_text else page

                if len(batch_text) + len(page_text) > max_chars:
                    # 현재 배치 처리
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

            # 마지막 배치 처리
            if batch_text.strip():
                print(f"  ▶ Processing batch {batch_num} ({len(batch_text):,} chars)...")
                prompt = self.create_extraction_prompt()
                response = self.parse_text_with_llm(batch_text, prompt)
                items = self.parse_response(response)
                all_items.extend(items)
                print(f"  ✓ Batch {batch_num}: {len(items)} items")

        else:
            # 3. 한 번에 처리
            print(f"  ▶ Processing full text ({len(text):,} chars)...")
            prompt = self.create_extraction_prompt()
            response = self.parse_text_with_llm(text, prompt)
            all_items = self.parse_response(response)

        print(f"  ➜ Total items from all batches: {len(all_items)}")
        return all_items
    

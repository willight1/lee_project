"""
Base Parser for PDF Processing
OCR(텍스트) 및 Vision API 기반 파싱의 기본 클래스
"""

import re
import json
import base64
import io
import fitz  # PyMuPDF
from typing import Dict, List, Tuple, Optional
from openai import OpenAI
from PIL import Image, ImageEnhance, ImageFilter


def normalize_case_number(case_number: Optional[str]) -> Optional[str]:
    """
    케이스 넘버 정규화
    - 엔대시(–)를 하이픈(-)으로 변경
    - 공백 제거
    - 여러 케이스 넘버가 있으면 첫 번째만 추출
    - 유효한 형식인지 검증 (A-XXX-XXX 또는 C-XXX-XXX만 허용)
    - Court Number (22-XXXXX) 등은 제외
    """
    if not case_number or case_number == "null":
        return None

    # 문자열로 변환
    case_str = str(case_number).strip()

    # 엔대시(–, U+2013)를 하이픈(-, U+002D)으로 변경
    case_str = case_str.replace('–', '-')
    case_str = case_str.replace('—', '-')  # em dash도 처리

    # 여러 케이스 넘버가 쉼표나 세미콜론으로 구분되어 있으면 첫 번째만 추출
    if ',' in case_str or ';' in case_str:
        case_str = re.split(r'[,;]', case_str)[0].strip()

    # 공백 제거
    case_str = case_str.replace(' ', '')

    # 유효한 케이스 넘버 형식 검증
    # 미국: A-XXX-XXX (Antidumping) 또는 C-XXX-XXX (Countervailing) 형식만 허용
    # Court Number (22-XXXXX), 기타 형식은 제외
    if not re.match(r'^[AC]-\d{3}-\d{3}$', case_str, re.IGNORECASE):
        return None

    return case_str

# Vision API 설정
BATCH_PAGE_LIMIT = 10  # 한 번에 처리할 최대 페이지 수
HIGH_QUALITY_DPI = 200  # 이미지 해상도


class TextBasedParser:
    """텍스트 기반 파서 (저렴한 LLM 사용)"""

    def __init__(self, client: OpenAI):
        self.client = client
        self.model_name = "gpt-4o-mini"  # 저렴한 텍스트 모델
        self.vision_model = "gpt-4o-mini"  # 이미지 PDF용 (Vision 지원)

    def parse_text_with_llm(
        self,
        text: str,
        prompt: str,
        max_retries: int = 2
    ) -> str:
        """
        저렴한 텍스트 모델로 파싱
        Vision API보다 10-20배 저렴!
        """
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a precise data extraction assistant. "
                                "Always output complete, valid JSON only. "
                                "Extract ALL information accurately. "
                                "IMPORTANT: Always close all JSON strings and objects properly."
                            )
                        },
                        {
                            "role": "user",
                            "content": f"{prompt}\n\n[DOCUMENT TEXT]\n{text}"
                        }
                    ],
                    max_completion_tokens=16000,
                    temperature=0.1
                )

                return response.choices[0].message.content.strip()

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  ⚠ LLM attempt {attempt + 1} failed, retrying...")
                else:
                    print(f"  ✗ LLM error after {max_retries} attempts: {e}")
                    return ""

        return ""

    def parse_response(self, response: str) -> List[Dict]:
        """JSON 파싱 - 잘린 JSON 복구 지원"""
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

        # 앞뒤 정리
        response = response.strip()
        if not response.startswith('{'):
            first_brace = response.find('{')
            if first_brace != -1:
                response = response[first_brace:]

        # 콤마 정리
        response = re.sub(r',(\s*[}\]])', r'\1', response)

        # JSON 복구 시도 (잘린 JSON 처리)
        def try_repair_json(text: str) -> str:
            """잘린 JSON을 복구 시도"""
            import copy
            repaired = text
            
            # 1. 마지막 완전한 객체 찾기 (items 배열 내)
            # items 배열에서 마지막 완전한 객체까지만 추출
            last_complete_obj = repaired.rfind('},')
            if last_complete_obj == -1:
                last_complete_obj = repaired.rfind('}')
            
            if last_complete_obj != -1:
                # 마지막 완전한 객체 이후 불완전한 부분 제거 시도
                potential = repaired[:last_complete_obj + 1]
                
                # 닫히지 않은 배열과 객체 닫기
                open_braces = potential.count('{') - potential.count('}')
                open_brackets = potential.count('[') - potential.count(']')
                
                if open_brackets > 0:
                    potential += ']' * open_brackets
                if open_braces > 0:
                    potential += '}' * open_braces
                
                try:
                    json.loads(potential)
                    return potential
                except:
                    pass
            
            # 2. 열린 문자열 닫기
            # 마지막 열린 따옴표 찾기
            in_string = False
            escape_next = False
            for i, char in enumerate(repaired):
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"':
                    in_string = not in_string
            
            if in_string:
                # 문자열이 닫히지 않음 - 닫아주기
                repaired = repaired + '"'
            
            # 3. 괄호 균형 맞추기
            open_braces = repaired.count('{') - repaired.count('}')
            open_brackets = repaired.count('[') - repaired.count(']')
            
            # 마지막 쉼표 제거
            repaired = re.sub(r',\s*$', '', repaired)
            
            if open_brackets > 0:
                repaired += ']' * open_brackets
            if open_braces > 0:
                repaired += '}' * open_braces
            
            return repaired

        try:
            data = json.loads(response)
            items = data.get('items', [])

            # 케이스 넘버 정규화
            for item in items:
                if 'case_number' in item:
                    item['case_number'] = normalize_case_number(item['case_number'])

            print(f"    ✓ Parsed {len(items)} items successfully")
            return items
        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON decode error: {e}")
            print(f"  🔧 Attempting JSON repair...")
            
            # JSON 복구 시도
            repaired = try_repair_json(response)
            try:
                data = json.loads(repaired)
                items = data.get('items', [])
                
                # 케이스 넘버 정규화
                for item in items:
                    if 'case_number' in item:
                        item['case_number'] = normalize_case_number(item['case_number'])
                
                print(f"    ✓ JSON repaired! Parsed {len(items)} items successfully")
                return items
            except json.JSONDecodeError as e2:
                print(f"  ✗ JSON repair failed: {e2}")
                # 디버깅용: 마지막 500자 출력
                print(f"  📋 Last 500 chars of response: ...{response[-500:]}")
                return []

    def create_extraction_prompt(self) -> str:
        """추출 프롬프트 (서브클래스에서 구현)"""
        raise NotImplementedError("Subclasses must implement create_extraction_prompt()")


# ============================================================================
# VISION-BASED PARSER
# ============================================================================

class VisionBasedParser:
    """Vision API 기반 파서"""

    def __init__(self, client: OpenAI):
        self.client = client
        self.model_name = "gpt-4o-mini"  # Vision 모델 (gpt-4o 접근 불가시 폴백)

    def enhance_image(self, img_bytes: bytes) -> bytes:
        """이미지 품질 향상 (선명도, 대비)"""
        try:
            img = Image.open(io.BytesIO(img_bytes))

            # 선명도 향상
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.2)

            # 대비 향상
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.15)

            # PNG로 변환
            output = io.BytesIO()
            img.save(output, format='PNG', optimize=True)
            return output.getvalue()

        except Exception as e:
            print(f"  ⚠ Image enhancement failed: {e}, using original")
            return img_bytes

    def get_pdf_page_images(
        self,
        pdf_path: str,
        dpi: int = HIGH_QUALITY_DPI,
        max_pages: int = None,
        enhance: bool = True
    ) -> List[Tuple[int, str]]:
        """PDF를 페이지별 이미지(Base64)로 변환"""
        try:
            doc = fitz.open(pdf_path)
            page_images: List[Tuple[int, str]] = []

            for page_index, page in enumerate(doc):
                page_num = page_index + 1
                if max_pages is not None and page_num > max_pages:
                    break

                # 이미지로 변환
                pix = page.get_pixmap(dpi=dpi)
                img_bytes = pix.tobytes("png")

                # 이미지 품질 향상
                if enhance:
                    img_bytes = self.enhance_image(img_bytes)

                b64 = base64.b64encode(img_bytes).decode("utf-8")
                page_images.append((page_num, b64))

            doc.close()

            if not page_images:
                print("  ✗ No pages extracted from PDF")
            else:
                print(f"  ✓ Extracted {len(page_images)} pages as images (DPI: {dpi})")

            return page_images

        except Exception as e:
            print(f"  ✗ Error extracting images from PDF: {e}")
            return []

    def call_vision_api(
        self,
        instruction: str,
        page_images_b64: List[str],
        max_retries: int = 3
    ) -> str:
        """Vision API 호출"""
        for attempt in range(max_retries):
            try:
                content = [{"type": "text", "text": instruction}]

                for b64 in page_images_b64:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}
                    })

                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a precise data extraction assistant. "
                                "Always output complete, valid JSON only. "
                                "Never truncate your response. "
                                "Extract ALL information with maximum accuracy."
                            )
                        },
                        {
                            "role": "user",
                            "content": content
                        }
                    ],
                    max_completion_tokens=16000,
                    temperature=0.1
                )

                response_text = response.choices[0].message.content.strip()

                # 코드 블럭 제거
                if response_text.startswith("```"):
                    lines = response_text.split('\n')
                    lines = lines[1:]
                    if lines and lines[-1].strip() == "```":
                        lines = lines[:-1]
                    response_text = '\n'.join(lines).strip()

                return response_text

            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  ⚠ Vision API attempt {attempt + 1} failed, retrying...")
                else:
                    print(f"  ✗ Vision API error after {max_retries} attempts: {e}")
                    return ""

        return ""

    def parse_response(self, response: str) -> List[Dict]:
        """JSON 응답 파싱"""
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
            items = data.get('items', [])

            # 케이스 넘버 정규화
            for item in items:
                if 'case_number' in item:
                    item['case_number'] = normalize_case_number(item['case_number'])

            print(f"    ✓ Parsed {len(items)} items successfully")
            return items
        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON decode error: {e}")
            return []

    def process(self, pdf_path: str) -> List[Dict]:
        """PDF 처리 (Vision API)"""
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
            items = self.parse_response(response)
            all_items.extend(items)
            print(f"  ✓ Batch {batch_page_nums[0]}–{batch_page_nums[-1]}: {len(items)} items")

        print(f"  ➜ Total items from all batches: {len(all_items)}")
        return all_items

    def create_extraction_prompt(self) -> str:
        """추출 프롬프트 (서브클래스에서 구현)"""
        raise NotImplementedError("Subclasses must implement create_extraction_prompt()")

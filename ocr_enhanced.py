"""
OCR 정확도 향상 버전 - 테이블 추출 특화

Tesseract + 이미지 전처리 + Camelot 표 추출 조합
"""

import os
import cv2
import numpy as np
import fitz  # PyMuPDF
import pytesseract
import camelot
from typing import List, Dict, Tuple
from PIL import Image
import io


class EnhancedOCRExtractor:
    """향상된 OCR + 표 추출 시스템"""

    def __init__(self, use_table_extraction: bool = True):
        self.use_table_extraction = use_table_extraction

        # Tesseract 설정 (최고 정확도)
        self.tesseract_config = r'--oem 3 --psm 6'
        # oem 3: LSTM 엔진
        # psm 6: 단일 텍스트 블록 (표에 적합)

    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """이미지 전처리로 OCR 정확도 향상"""

        # 1. 그레이스케일
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        # 2. 노이즈 제거
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

        # 3. 이진화 (Otsu's method)
        _, binary = cv2.threshold(
            denoised, 0, 255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        # 4. 모폴로지 연산 (선명도 향상)
        kernel = np.ones((1, 1), np.uint8)
        processed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        # 5. 대비 향상
        processed = cv2.equalizeHist(processed)

        return processed

    def extract_text_with_preprocessing(
        self,
        pdf_path: str,
        page_num: int = 0,
        dpi: int = 300
    ) -> str:
        """전처리 + OCR 조합"""

        # PDF → 고해상도 이미지
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        pix = page.get_pixmap(dpi=dpi)  # 300 DPI

        # numpy 배열로 변환
        img_bytes = pix.tobytes("png")
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        # 전처리
        processed = self.preprocess_image(img)

        # OCR 실행
        text = pytesseract.image_to_string(
            processed,
            lang='eng',
            config=self.tesseract_config
        )

        doc.close()
        return text

    def extract_tables_with_camelot(
        self,
        pdf_path: str
    ) -> List[Dict]:
        """Camelot으로 표 구조 정확히 추출"""

        try:
            # Camelot으로 표 추출 (stream 모드: 선이 없는 표도 인식)
            tables = camelot.read_pdf(
                pdf_path,
                pages='all',
                flavor='stream',  # or 'lattice' for bordered tables
                edge_tol=50
            )

            result = []
            for i, table in enumerate(tables):
                # pandas DataFrame으로 변환
                df = table.df

                # 표 정보
                table_info = {
                    'page': table.page,
                    'accuracy': table.accuracy,
                    'data': df.to_dict('records'),
                    'shape': df.shape
                }
                result.append(table_info)

            return result

        except Exception as e:
            print(f"⚠ Camelot extraction failed: {e}")
            return []

    def extract_tariff_data(self, pdf_path: str) -> Dict:
        """관세 문서에서 데이터 추출 (표 + OCR 조합)"""

        result = {
            'tables': [],
            'text': '',
            'method': 'hybrid'
        }

        # 1. 표 추출 시도 (Camelot)
        if self.use_table_extraction:
            print("  → Extracting tables with Camelot...")
            tables = self.extract_tables_with_camelot(pdf_path)

            if tables:
                result['tables'] = tables
                print(f"  ✓ Found {len(tables)} tables")

                # 표가 정확히 추출되면 OCR 스킵 가능
                if len(tables) > 0 and tables[0]['accuracy'] > 80:
                    result['method'] = 'table_only'
                    return result

        # 2. OCR로 전체 텍스트 추출 (백업)
        print("  → Extracting text with enhanced OCR...")
        try:
            text = self.extract_text_with_preprocessing(pdf_path)
            result['text'] = text
            print(f"  ✓ Extracted {len(text)} characters")
        except Exception as e:
            print(f"  ✗ OCR failed: {e}")

        return result


# ============================================================================
# 사용 예시
# ============================================================================

def compare_methods(pdf_path: str):
    """기존 방법 vs OCR 개선 방법 비교"""

    print("\n" + "="*80)
    print("OCR 정확도 비교 테스트")
    print("="*80)

    # 방법 1: 기본 PyMuPDF 텍스트 추출
    print("\n[방법 1] 기본 텍스트 추출 (PyMuPDF)")
    doc = fitz.open(pdf_path)
    basic_text = ""
    for page in doc:
        basic_text += page.get_text()
    doc.close()
    print(f"  글자 수: {len(basic_text)}")
    print(f"  샘플: {basic_text[:200]}...")

    # 방법 2: 향상된 OCR
    print("\n[방법 2] 향상된 OCR (전처리 + Tesseract)")
    extractor = EnhancedOCRExtractor()
    enhanced_text = extractor.extract_text_with_preprocessing(pdf_path, dpi=300)
    print(f"  글자 수: {len(enhanced_text)}")
    print(f"  샘플: {enhanced_text[:200]}...")

    # 방법 3: 표 추출
    print("\n[방법 3] 표 추출 (Camelot)")
    tables = extractor.extract_tables_with_camelot(pdf_path)
    if tables:
        print(f"  발견된 표: {len(tables)}개")
        for i, table in enumerate(tables):
            print(f"  표 {i+1}: {table['shape']} (정확도: {table['accuracy']:.1f}%)")

    # 방법 4: 하이브리드
    print("\n[방법 4] 하이브리드 (표 + OCR)")
    hybrid_result = extractor.extract_tariff_data(pdf_path)
    print(f"  추출 방법: {hybrid_result['method']}")
    print(f"  표 개수: {len(hybrid_result['tables'])}")
    print(f"  텍스트 길이: {len(hybrid_result['text'])}")


if __name__ == "__main__":
    # 테스트
    import sys

    if len(sys.argv) > 1:
        pdf_file = sys.argv[1]
    else:
        pdf_file = "PDF/USA_HR_Countervailing_C-580-884_2016.pdf"

    if os.path.exists(pdf_file):
        compare_methods(pdf_file)
    else:
        print(f"파일을 찾을 수 없습니다: {pdf_file}")
        print("\n사용법: python ocr_enhanced.py <PDF파일경로>")

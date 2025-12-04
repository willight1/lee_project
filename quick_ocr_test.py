"""
빠른 OCR 테스트 - 3가지 방법 비교

못 읽는 문서를 개선하는 가장 쉬운 방법:
1. DPI 올리기 (150 → 300)
2. 표 전용 라이브러리 (Camelot)
3. EasyOCR (설치만 하면 끝)
"""

import fitz
import os


def method1_increase_dpi(pdf_path, page_num=0):
    """방법 1: DPI만 올리기 (가장 간단)"""
    print("\n[방법 1] DPI 300으로 올리기")

    doc = fitz.open(pdf_path)
    page = doc[page_num]

    # DPI 150 → 300
    pix = page.get_pixmap(dpi=300)

    # 이미지 저장
    pix.save(f"page_{page_num}_dpi300.png")
    print(f"  ✓ 저장: page_{page_num}_dpi300.png")

    # 텍스트 추출
    text = page.get_text()
    print(f"  ✓ 추출된 글자 수: {len(text)}")

    doc.close()
    return text


def method2_table_extraction(pdf_path):
    """방법 2: 표 전용 라이브러리 (가장 정확)"""
    print("\n[방법 2] Camelot 표 추출")

    try:
        import camelot

        tables = camelot.read_pdf(pdf_path, pages='1', flavor='stream')

        if tables:
            print(f"  ✓ 발견된 표: {len(tables)}개")

            for i, table in enumerate(tables):
                df = table.df
                print(f"\n  표 {i+1} ({df.shape[0]}행 × {df.shape[1]}열):")
                print(df.head())

                # CSV로 저장
                df.to_csv(f"table_{i+1}.csv", index=False)
                print(f"  ✓ 저장: table_{i+1}.csv")
        else:
            print("  ⚠ 표를 찾지 못했습니다")

    except ImportError:
        print("  ✗ Camelot 미설치. 설치: pip install 'camelot-py[cv]'")
    except Exception as e:
        print(f"  ✗ 오류: {e}")


def method3_easyocr(pdf_path, page_num=0):
    """방법 3: EasyOCR (딥러닝, 가장 강력)"""
    print("\n[방법 3] EasyOCR (딥러닝)")

    try:
        import easyocr

        # 먼저 이미지로 변환
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        pix = page.get_pixmap(dpi=300)
        pix.save("temp_page.png")
        doc.close()

        # EasyOCR 실행
        print("  → 모델 로딩 중...")
        reader = easyocr.Reader(['en'])  # 영어만

        print("  → OCR 실행 중...")
        result = reader.readtext("temp_page.png")

        # 결과 출력
        print(f"  ✓ 인식된 텍스트 블록: {len(result)}개")

        full_text = "\n".join([text for (bbox, text, conf) in result])
        print(f"  ✓ 총 글자 수: {len(full_text)}")

        # 신뢰도 낮은 것 표시
        low_conf = [(text, conf) for (_, text, conf) in result if conf < 0.5]
        if low_conf:
            print(f"  ⚠ 신뢰도 낮음 ({len(low_conf)}개):")
            for text, conf in low_conf[:3]:
                print(f"    - '{text}' ({conf:.2f})")

        # 정리
        os.remove("temp_page.png")

        return full_text

    except ImportError:
        print("  ✗ EasyOCR 미설치. 설치: pip install easyocr")
    except Exception as e:
        print(f"  ✗ 오류: {e}")


def compare_all_methods(pdf_path):
    """3가지 방법 모두 비교"""
    print("="*80)
    print(f"OCR 테스트: {os.path.basename(pdf_path)}")
    print("="*80)

    if not os.path.exists(pdf_path):
        print(f"✗ 파일을 찾을 수 없습니다: {pdf_path}")
        return

    # 방법 1: DPI 올리기
    method1_increase_dpi(pdf_path)

    # 방법 2: 표 추출
    method2_table_extraction(pdf_path)

    # 방법 3: EasyOCR
    method3_easyocr(pdf_path)

    print("\n" + "="*80)
    print("추천 방법:")
    print("  - 표가 많으면: Camelot (방법 2)")
    print("  - 일반 텍스트: DPI 300 + EasyOCR (방법 1+3)")
    print("  - 현재 Vision API: 이미 최고 수준")
    print("="*80)


if __name__ == "__main__":
    import sys

    # PDF 파일 경로
    if len(sys.argv) > 1:
        pdf_file = sys.argv[1]
    else:
        # 기본 파일
        pdf_folder = "PDF"
        if os.path.exists(pdf_folder):
            pdfs = [f for f in os.listdir(pdf_folder) if f.endswith('.pdf')]
            if pdfs:
                pdf_file = os.path.join(pdf_folder, pdfs[0])
            else:
                print("PDF 폴더에 파일이 없습니다.")
                sys.exit(1)
        else:
            print("PDF 폴더가 없습니다.")
            sys.exit(1)

    compare_all_methods(pdf_file)

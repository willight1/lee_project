"""
Parser Factory
파일명 및 모드에 따라 적절한 파서를 생성
"""

from openai import OpenAI
from .base_parser import TextBasedParser, VisionBasedParser
from .default_parser import DefaultTextParser
from .usa_parser import USATextParser, USAVisionParser
from .eu_parser import EUTextParser, EUVisionParser
from .malaysia_parser import MalaysiaTextParser, MalaysiaVisionParser
from .australia_parser import AustraliaTextParser, AustraliaVisionParser
from .brazil_parser import BrazilParser
from .india_parser import IndiaParser
from .canada_parser import CanadaParser
from .turkey_parser import TurkeyParser
from .pakistan_parser import PakistanParser


class ParserFactory:
    """파서 팩토리 - 파일명과 모드에 따라 적절한 파서 생성"""

    @staticmethod
    def create_parser(
        file_name: str,
        client: OpenAI,
        mode: str = "ocr"
    ):
        """
        파일명 및 모드 기반으로 파서 생성

        Args:
            file_name: PDF 파일명
            client: OpenAI 클라이언트
            mode: "ocr" (텍스트 추출) 또는 "vision" (Vision API)

        Returns:
            적절한 파서 인스턴스
        """
        file_name_upper = file_name.upper()
        mode = mode.lower()

        if mode not in ["ocr", "vision"]:
            print(f"  ⚠ Invalid mode '{mode}', defaulting to 'ocr'")
            mode = "ocr"

        # 국가별 파서 매핑
        if 'USA_' in file_name_upper or 'US_' in file_name_upper:
            if mode == "vision":
                print("  Using USA Vision Parser")
                return USAVisionParser(client)
            else:
                print("  Using USA Text Parser (OCR)")
                return USATextParser(client)

        elif 'EU_' in file_name_upper:
            if mode == "vision":
                print("  Using EU Vision Parser")
                return EUVisionParser(client)
            else:
                print("  Using EU Text Parser (OCR)")
                return EUTextParser(client)

        elif 'MALAYSIA_' in file_name_upper:
            if mode == "vision":
                print("  Using Malaysia Vision Parser")
                return MalaysiaVisionParser(client)
            else:
                print("  Using Malaysia Text Parser (OCR)")
                return MalaysiaTextParser(client)

        elif 'AUSTRALIA_' in file_name_upper:
            if mode == "vision":
                print("  Using Australia Vision Parser")
                return AustraliaVisionParser(client)
            else:
                print("  Using Australia Text Parser (OCR)")
                return AustraliaTextParser(client)

        elif 'BRAZIL_' in file_name_upper:
            print(f"  Using Brazil Parser ({'Vision' if mode == 'vision' else 'OCR'})")
            return BrazilParser(client)

        elif 'INDIA_' in file_name_upper:
            print(f"  Using India Parser ({'Vision' if mode == 'vision' else 'OCR'})")
            return IndiaParser(client)

        elif 'CANADA_' in file_name_upper:
            print(f"  Using Canada Parser ({'Vision' if mode == 'vision' else 'OCR'})")
            return CanadaParser(client)

        elif 'TURKEY_' in file_name_upper:
            print(f"  Using Turkey Parser ({'Vision' if mode == 'vision' else 'OCR'})")
            return TurkeyParser(client)

        elif 'PAKISTAN_' in file_name_upper:
            print(f"  Using Pakistan Parser ({'Vision' if mode == 'vision' else 'OCR'})")
            return PakistanParser(client)

        else:
            print(f"  Using Default Parser ({'Vision' if mode == 'vision' else 'OCR'})")
            return DefaultTextParser(client)

    @staticmethod
    def detect_issuing_country(file_name: str) -> str:
        """파일명에서 발행국 추론"""
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

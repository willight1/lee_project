"""
Canada Tariff Parser
캐나다 관세 정보 파서
"""

from .default_parser import DefaultTextParser


class CanadaParser(DefaultTextParser):
    """캐나다 특화 파서"""
    pass  # 기본 파서 사용, 필요시 프롬프트 커스터마이징

"""
India Tariff Parser
인도 관세 정보 파서
"""

from .default_parser import DefaultTextParser


class IndiaParser(DefaultTextParser):
    """인도 특화 파서"""
    pass  # 기본 파서 사용, 필요시 프롬프트 커스터마이징

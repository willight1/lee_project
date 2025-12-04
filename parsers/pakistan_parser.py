"""
Pakistan Tariff Parser
파키스탄 관세 정보 파서
"""

from .default_parser import DefaultTextParser


class PakistanParser(DefaultTextParser):
    """파키스탄 특화 파서"""
    pass  # 기본 파서 사용, 필요시 프롬프트 커스터마이징

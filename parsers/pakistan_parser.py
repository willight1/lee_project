"""
Pakistan Tariff Parser
파키스탄 관세 정보 파서
"""

from typing import Dict, List
from .default_parser import DefaultTextParser


class PakistanParser(DefaultTextParser):
    """파키스탄 특화 파서"""

    def process(self, pdf_path: str) -> List[Dict]:
        """
        PDF 처리 후 모든 HS Code × 국가 조합을 강제 생성
        LLM이 불완전한 조합을 반환해도 Python에서 완전한 Cartesian product 생성
        """
        # 기본 파서로 먼저 추출
        items = super().process(pdf_path)
        
        if not items:
            return items
        
        # 모든 고유 HS 코드 수집
        all_hs_codes = set()
        for item in items:
            if item.get('hs_code'):
                all_hs_codes.add(item['hs_code'])
        
        # 국가별 정보 수집 (tariff_rate 등)
        country_info = {}
        for item in items:
            country = item.get('country')
            if country and country not in country_info:
                country_info[country] = {
                    'tariff_rate': item.get('tariff_rate'),
                    'tariff_type': item.get('tariff_type'),
                    'effective_date_from': item.get('effective_date_from'),
                    'effective_date_to': item.get('effective_date_to'),
                    'investigation_period_from': item.get('investigation_period_from'),
                    'investigation_period_to': item.get('investigation_period_to'),
                    'basis_law': item.get('basis_law'),
                    'case_number': item.get('case_number'),
                    'product_description': item.get('product_description'),
                    'note': item.get('note'),
                    'company': item.get('company'),
                }
        
        print(f"  📊 Found {len(all_hs_codes)} unique HS codes")
        print(f"  📊 Found {len(country_info)} countries: {list(country_info.keys())}")
        
        # Cartesian product 생성: 모든 HS Code × 모든 국가
        complete_items = []
        for hs_code in sorted(all_hs_codes):
            for country, info in country_info.items():
                complete_items.append({
                    'country': country,
                    'hs_code': hs_code,
                    'tariff_type': info.get('tariff_type'),
                    'tariff_rate': info.get('tariff_rate'),
                    'effective_date_from': info.get('effective_date_from'),
                    'effective_date_to': info.get('effective_date_to'),
                    'investigation_period_from': info.get('investigation_period_from'),
                    'investigation_period_to': info.get('investigation_period_to'),
                    'basis_law': info.get('basis_law'),
                    'company': info.get('company'),
                    'case_number': info.get('case_number'),
                    'product_description': info.get('product_description'),
                    'note': info.get('note'),
                })
        
        expected_count = len(all_hs_codes) * len(country_info)
        print(f"  ✓ Generated {len(complete_items)} items ({len(all_hs_codes)} HS codes × {len(country_info)} countries = {expected_count})")
        
        return complete_items

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the Pakistan Anti-Dumping document.

**DOCUMENT STRUCTURE:**
- The document contains a list of HS codes and their tariff rates by country
- All HS codes listed apply to ALL countries mentioned
- Each country may have different tariff rates

**CRITICAL EXTRACTION RULES:**

1. **HS CODE × COUNTRY COMBINATION - EXTREMELY IMPORTANT:**
   - Find ALL HS codes listed in the document (usually 10-20 codes)
   - Find ALL countries mentioned (e.g., Chinese Taipei, EU, Korea, Vietnam)
   - Create items for EVERY combination: each HS code × each country
   - Example: If 16 HS codes and 4 countries → create 64 items (16 × 4)
   - The SAME tariff rate for a country applies to ALL HS codes for that country

2. **TARIFF RATE BY COUNTRY:**
   - Each country has ONE tariff rate that applies to all HS codes
   - Example structure:
     * Chinese Taipei: 6.18% → applies to ALL 16 HS codes
     * EU: 4.50% → applies to ALL 16 HS codes
     * Korea: 3.20% → applies to ALL 16 HS codes
     * Vietnam: 5.00% → applies to ALL 16 HS codes

3. **HS CODE FORMAT:**
   - Extract HS codes as shown in document (e.g., "7209.1510", "7209.1590")
   - Include both 4-digit and 6/8-digit codes if present

4. **EXCLUSION LIST:**
   - If there's a section with "Excluded Grades" or similar
   - Extract these to the "note" field

**OUTPUT FORMAT:**

{
  "items": [
    {
      "country": "Country name (e.g., Chinese Taipei)",
      "hs_code": "Single HS code (e.g., 7209.1510)",
      "tariff_type": "Antidumping",
      "tariff_rate": number,
      "effective_date_from": "YYYY-MM-DD or null",
      "effective_date_to": "YYYY-MM-DD or null",
      "investigation_period_from": null,
      "investigation_period_to": null,
      "basis_law": "Legal basis (e.g., A.D.C No. 60)",
      "company": null,
      "case_number": "A.D.C No. from document title",
      "product_description": "Product description",
      "note": "Excluded grades if any"
    }
  ]
}

**EXAMPLE:**
If document has HS codes: 7209.1510, 7209.1590, 7209.1610
And countries: Chinese Taipei (6.18%), EU (4.50%)

Create 6 items:
- hs_code: 7209.1510, country: Chinese Taipei, tariff_rate: 6.18
- hs_code: 7209.1510, country: EU, tariff_rate: 4.50
- hs_code: 7209.1590, country: Chinese Taipei, tariff_rate: 6.18
- hs_code: 7209.1590, country: EU, tariff_rate: 4.50
- hs_code: 7209.1610, country: Chinese Taipei, tariff_rate: 6.18
- hs_code: 7209.1610, country: EU, tariff_rate: 4.50

**FINAL CHECKLIST:**
- [ ] Did I find ALL HS codes in the document?
- [ ] Did I find ALL countries/origins in the document?
- [ ] Did I create an item for EVERY HS code × country combination?
- [ ] Is the count = (number of HS codes) × (number of countries)?

Output ONLY valid JSON.
"""

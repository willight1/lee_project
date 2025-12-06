"""
Pakistan Tariff Parser
파키스탄 관세 정보 파서
"""

from .default_parser import DefaultTextParser


class PakistanParser(DefaultTextParser):
    """파키스탄 특화 파서"""

    def create_extraction_prompt(self) -> str:
        return """Extract tariff/trade remedy information from the Pakistan document text.

**CRITICAL INSTRUCTIONS:**

1. **Exclusion List from Definitive Anti-dumping Duty Rates:**
   - Look for section titled "Definitive Anti-dumping Duty Rates"
   - Under this section, there is a list of excluded grades/products (S.No, Grade columns)
   - Extract ALL grades listed (i, ii, iii, iv, v, vi, vii, viii, ix, x, etc.)
   - Add this exclusion list to the "note" field with prefix "Excluded Grades: "
   - These are products that are EXCLUDED from anti-dumping duties
   - Example grades: JAC, JSC, SPC, SPCD-S, SECC-0/20, SUS 304, SUS 409LT-E, etc.
   - Include all grade information exactly as shown in the document

2. **HS Code Separation - MANDATORY:**
   - If multiple HS codes are listed, create SEPARATE items for EACH HS code
   - DO NOT combine multiple HS codes into one item

3. **Country Separation - MANDATORY:**
   - If multiple countries are listed, create SEPARATE items for EACH country
   - DO NOT combine multiple countries into one item

4. **Company Handling:**
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
      "note": "Excluded Grades: [list all excluded grades from Definitive Anti-dumping Duty Rates section]"
    }
  ]
}

**REMEMBER:**
- ONE hs_code per item
- ONE country per item
- Create ALL combinations: each HS code × each country × each company
- Include excluded grades in note field if found
- Output ONLY JSON, no explanatory text.
"""

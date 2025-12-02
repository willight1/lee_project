"""
Trade Remedy Database Management System - Unified Module

This module provides:
1. Database schema and management (TradeRemedyDB)
2. PDF content parsing (TradeRemedyPDFParser)
3. PDF import and data extraction (PDFImporter)

Usage:
    python data_pdf.py
"""

import os
import re
import json
import sqlite3
import fitz  # PyMuPDF
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================================
# DATABASE MANAGEMENT
# ============================================================================

class TradeRemedyDB:
    """Trade Remedy Database Management"""

    def __init__(self, db_path: str = "trade_remedy.db"):
        """Initialize database connection and create tables if not exist"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        """Create all necessary tables for trade remedy data management"""

        # 1. Countries/Regions table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                country_id INTEGER PRIMARY KEY AUTOINCREMENT,
                country_code TEXT UNIQUE NOT NULL,
                country_name TEXT NOT NULL,
                region TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Documents table - Main document metadata
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                issuing_country_id INTEGER NOT NULL,
                measure_type TEXT NOT NULL,
                product_category TEXT,
                case_number TEXT,
                regulation_number TEXT,
                status TEXT,
                effective_date DATE,
                expiry_date DATE,
                investigation_year INTEGER,
                total_pages INTEGER,
                file_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (issuing_country_id) REFERENCES countries(country_id)
            )
        """)

        # Create indexes for faster queries
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_doc_country
            ON documents(issuing_country_id)
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_doc_measure_type
            ON documents(measure_type)
        """)

        # 3. Target countries - Countries affected by the measure
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS target_countries (
                target_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                country_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
                FOREIGN KEY (country_id) REFERENCES countries(country_id)
            )
        """)

        # 4. HS Codes table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS hs_codes (
                hs_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                hs_code TEXT NOT NULL,
                product_description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
            )
        """)

        # 5. Companies/Exporters table
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                company_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                company_name TEXT NOT NULL,
                country_id INTEGER,
                duty_rate REAL,
                duty_rate_unit TEXT DEFAULT 'percentage',
                company_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
                FOREIGN KEY (country_id) REFERENCES countries(country_id)
            )
        """)

        # 6. Pages table - OCR/Translation content
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                page_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                source_language TEXT,
                source_text TEXT,
                translated_text TEXT,
                image_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
            )
        """)

        # Create index for page queries
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_page_doc
            ON pages(doc_id)
        """)

        # 7. Keywords/Tags for easier searching
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                tag_name TEXT NOT NULL,
                tag_value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
            )
        """)

        self.conn.commit()
        print(f"✓ Database tables created successfully: {self.db_path}")

    def insert_country(self, country_code: str, country_name: str, region: str = None) -> int:
        """Insert or get country ID"""
        self.cursor.execute(
            "SELECT country_id FROM countries WHERE country_code = ?",
            (country_code,)
        )
        result = self.cursor.fetchone()

        if result:
            return result['country_id']

        self.cursor.execute(
            "INSERT INTO countries (country_code, country_name, region) VALUES (?, ?, ?)",
            (country_code, country_name, region)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def insert_document(self, doc_data: Dict) -> int:
        """Insert document metadata"""
        query = """
            INSERT INTO documents (
                file_name, issuing_country_id, measure_type, product_category,
                case_number, regulation_number, status, effective_date,
                expiry_date, investigation_year, total_pages, file_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        self.cursor.execute(query, (
            doc_data.get('file_name'),
            doc_data.get('issuing_country_id'),
            doc_data.get('measure_type'),
            doc_data.get('product_category'),
            doc_data.get('case_number'),
            doc_data.get('regulation_number'),
            doc_data.get('status'),
            doc_data.get('effective_date'),
            doc_data.get('expiry_date'),
            doc_data.get('investigation_year'),
            doc_data.get('total_pages'),
            doc_data.get('file_path')
        ))

        self.conn.commit()
        return self.cursor.lastrowid

    def insert_target_country(self, doc_id: int, country_id: int):
        """Link document to target country"""
        self.cursor.execute(
            "INSERT INTO target_countries (doc_id, country_id) VALUES (?, ?)",
            (doc_id, country_id)
        )
        self.conn.commit()

    def insert_hs_code(self, doc_id: int, hs_code: str, description: str = None):
        """Insert HS code for a document"""
        self.cursor.execute(
            "INSERT INTO hs_codes (doc_id, hs_code, product_description) VALUES (?, ?, ?)",
            (doc_id, hs_code, description)
        )
        self.conn.commit()

    def insert_company(self, company_data: Dict):
        """Insert company/exporter information"""
        query = """
            INSERT INTO companies (
                doc_id, company_name, country_id, duty_rate,
                duty_rate_unit, company_type
            ) VALUES (?, ?, ?, ?, ?, ?)
        """

        self.cursor.execute(query, (
            company_data.get('doc_id'),
            company_data.get('company_name'),
            company_data.get('country_id'),
            company_data.get('duty_rate'),
            company_data.get('duty_rate_unit', 'percentage'),
            company_data.get('company_type')
        ))

        self.conn.commit()
        return self.cursor.lastrowid

    def insert_page(self, page_data: Dict):
        """Insert page content (OCR/translation)"""
        query = """
            INSERT INTO pages (
                doc_id, page_number, source_language,
                source_text, translated_text, image_path
            ) VALUES (?, ?, ?, ?, ?, ?)
        """

        self.cursor.execute(query, (
            page_data.get('doc_id'),
            page_data.get('page_number'),
            page_data.get('source_language'),
            page_data.get('source_text'),
            page_data.get('translated_text'),
            page_data.get('image_path')
        ))

        self.conn.commit()

    def insert_tag(self, doc_id: int, tag_name: str, tag_value: str = None):
        """Insert tag for document"""
        self.cursor.execute(
            "INSERT INTO tags (doc_id, tag_name, tag_value) VALUES (?, ?, ?)",
            (doc_id, tag_name, tag_value)
        )
        self.conn.commit()

    def close(self):
        """Close database connection"""
        self.conn.close()


def initialize_countries(db: TradeRemedyDB):
    """Initialize common countries/regions"""
    countries_data = [
        ('USA', 'United States', 'North America'),
        ('EU', 'European Union', 'Europe'),
        ('KR', 'South Korea', 'Asia'),
        ('JP', 'Japan', 'Asia'),
        ('CN', 'China', 'Asia'),
        ('TW', 'Taiwan', 'Asia'),
        ('ID', 'Indonesia', 'Southeast Asia'),
        ('TH', 'Thailand', 'Southeast Asia'),
        ('VN', 'Vietnam', 'Southeast Asia'),
        ('IN', 'India', 'South Asia'),
        ('BR', 'Brazil', 'South America'),
        ('CA', 'Canada', 'North America'),
        ('MX', 'Mexico', 'North America'),
        ('AU', 'Australia', 'Oceania'),
        ('RU', 'Russia', 'Europe'),
    ]

    for code, name, region in countries_data:
        db.insert_country(code, name, region)

    print(f"✓ Initialized {len(countries_data)} countries")


# ============================================================================
# PDF CONTENT PARSER
# ============================================================================

class TradeRemedyPDFParser:
    """Parse trade remedy PDF documents to extract structured data"""

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.full_text = ""
        self.doc = None

    def extract_text(self) -> str:
        """Extract all text from PDF"""
        try:
            self.doc = fitz.open(self.pdf_path)
            text_parts = []

            for page in self.doc:
                text_parts.append(page.get_text())

            self.full_text = "\n".join(text_parts)
            return self.full_text

        except Exception as e:
            print(f"Error extracting text from PDF: {e}")
            return ""
        finally:
            if self.doc:
                self.doc.close()

    def extract_target_countries(self) -> List[str]:
        """Extract target countries mentioned in the document"""
        countries = set()

        # Country name mapping
        country_patterns = {
            r'Republic of Korea|South Korea': 'KR',
            r'People\'s Republic of China|China(?!\s+Steel)|PRC': 'CN',
            r'Taiwan': 'TW',
            r'Japan': 'JP',
            r'Vietnam': 'VN',
            r'Thailand': 'TH',
            r'Indonesia': 'ID',
            r'India': 'IN',
            r'Brazil': 'BR',
            r'Mexico': 'MX',
            r'Canada': 'CA',
            r'European Union|EU': 'EU',
        }

        # Look for "from [country]" patterns
        for pattern, code in country_patterns.items():
            if re.search(rf'\bfrom\s+(?:the\s+)?{pattern}\b', self.full_text, re.IGNORECASE):
                countries.add(code)

        return list(countries)

    def extract_hs_codes(self) -> List[Tuple[str, Optional[str]]]:
        """Extract HS codes and descriptions"""
        hs_codes = []

        # Pattern for HS codes (supports both 8-digit and 10-digit formats)
        pattern = r'\b(\d{4}\.\d{2}\.\d{2,4})\b'
        matches = re.finditer(pattern, self.full_text)

        for match in matches:
            hs_code = match.group(1)
            # Try to find description nearby
            start = max(0, match.start() - 200)
            end = min(len(self.full_text), match.end() + 200)
            context = self.full_text[start:end]

            # Look for product description
            desc = None
            desc_pattern = r'(?:pos tarif|tariff|hs\s+code)[:\s]+[\d\.]+[,\s]+([\w\s\-,]+?)(?:\.|,|\n|$)'
            desc_match = re.search(desc_pattern, context, re.IGNORECASE)
            if desc_match:
                desc = desc_match.group(1).strip()

            hs_codes.append((hs_code, desc))

        # Remove duplicates while preserving order
        seen = set()
        unique_hs_codes = []
        for code, desc in hs_codes:
            if code not in seen:
                seen.add(code)
                unique_hs_codes.append((code, desc))

        return unique_hs_codes

    def extract_investigation_period(self) -> Tuple[Optional[str], Optional[str]]:
        """Extract investigation period (POR)"""
        
        # Pattern for date ranges
        pattern = r'(?:POR|period.*?review|investigation.*?period)[^\d]*((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})(?:,?\s+through\s+|\s*[-–]\s*)((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})'

        match = re.search(pattern, self.full_text, re.IGNORECASE)

        if match:
            start_date = self.parse_date(match.group(1))
            end_date = self.parse_date(match.group(2))
            return start_date, end_date

        return None, None

    def extract_effective_date(self) -> Optional[str]:
        """Extract effective date"""
        patterns = [
            r'Applicable\s+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})',
            r'effective\s+(?:on\s+)?((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})',
            r'Dated[:\s]+((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})',
        ]

        for pattern in patterns:
            match = re.search(pattern, self.full_text, re.IGNORECASE)
            if match:
                return self.parse_date(match.group(1))

        return None

    def extract_expiry_date(self) -> Optional[str]:
        """Extract expiry/sunset date"""
        # Direct expiry date
        pattern = r'expir(?:es|y|ation).*?((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})'
        match = re.search(pattern, self.full_text, re.IGNORECASE)

        if match:
            return self.parse_date(match.group(1))

        return None

    def extract_companies_and_rates(self) -> List[Dict]:
        """Extract company names and dumping margins from tables"""
        companies = []

        # Split text into lines
        lines = self.full_text.split('\n')

        # Look for table header
        in_table = False
        header_pattern = r'(Exporter|Producer|Company|Manufacturer)'

        for i, line in enumerate(lines):
            # Check if this is a table header
            if re.search(header_pattern, line, re.IGNORECASE):
                in_table = True
                continue

            if in_table:
                # Stop at certain keywords
                if re.search(r'^(Disclosure|Assessment|Cash\s+Deposit|Notification|The following)', line, re.IGNORECASE):
                    in_table = False
                    continue

                # Look for company name line
                if re.search(r'(Ltd|Inc|Corp|Company|Corporation|Co\.|L\.L\.C|GmbH)', line, re.IGNORECASE):
                    company_line = line.strip()

                    # Clean up company name
                    company_name = re.sub(r'\.{2,}.*$', '', company_line)
                    company_name = re.sub(r'\s{2,}', ' ', company_name)
                    company_name = company_name.strip('.,;: ')

                    # Look for rate in next few lines
                    for j in range(i + 1, min(i + 4, len(lines))):
                        next_line = lines[j].strip()

                        # Check if this line is just a number (the rate)
                        rate_match = re.match(r'^(\d+\.\d+)$', next_line)

                        if rate_match:
                            rate = float(rate_match.group(1))

                            if company_name and len(company_name) > 3:
                                companies.append({
                                    'company_name': company_name,
                                    'duty_rate': rate,
                                    'duty_rate_unit': 'percentage'
                                })
                                break

                        # Stop if we hit another company name
                        if re.search(r'(Ltd|Inc|Corp|Company|Corporation)', next_line, re.IGNORECASE):
                            break

        return companies

    def parse_date(self, date_str: str) -> Optional[str]:
        """Convert date string to YYYY-MM-DD format"""
        try:
            formats = [
                '%B %d, %Y',      # December 17, 2024
                '%b %d, %Y',      # Dec 17, 2024
                '%m/%d/%Y',       # 12/17/2024
                '%Y-%m-%d',       # 2024-12-17
            ]

            for fmt in formats:
                try:
                    date_obj = datetime.strptime(date_str.strip(), fmt)
                    return date_obj.strftime('%Y-%m-%d')
                except:
                    continue

            return None
        except:
            return None

    def extract_all(self) -> Dict:
        """Extract all information from PDF"""
        # First extract text
        if not self.full_text:
            self.extract_text()

        if not self.full_text:
            return {}

        # Extract all data
        data = {
            'target_countries': self.extract_target_countries(),
            'hs_codes': self.extract_hs_codes(),
            'companies': self.extract_companies_and_rates(),
            'investigation_period': self.extract_investigation_period(),
            'effective_date': self.extract_effective_date(),
            'expiry_date': self.extract_expiry_date(),
        }

        return data


# ============================================================================
# PDF IMPORTER
# ============================================================================

class PDFImporter:
    def __init__(self, db: TradeRemedyDB, pdf_folder: str = "PDF", output_folder: str = "output"):
        self.db = db
        self.pdf_folder = pdf_folder
        self.output_folder = output_folder

    def parse_filename(self, filename: str) -> dict:
        """Parse PDF filename to extract metadata"""
        metadata = {
            'file_name': filename,
            'issuing_country': None,
            'measure_type': None,
            'product_category': None,
            'case_number': None,
            'regulation_number': None,
            'status': None,
            'investigation_year': None,
            'effective_date': None
        }

        # Remove .pdf extension
        name = filename.replace('.pdf', '')
        parts = name.split('_')

        if len(parts) < 3:
            return metadata

        # First part is usually country
        metadata['issuing_country'] = parts[0]

        # Detect measure type
        name_lower = name.lower()
        if 'antidumping' in name_lower or 'anti-dumping' in name_lower:
            metadata['measure_type'] = 'Antidumping'
        elif 'countervailing' in name_lower:
            metadata['measure_type'] = 'Countervailing'
        elif 'safeguard' in name_lower:
            metadata['measure_type'] = 'Safeguard'

        # Extract product category
        product_indicators = ['Coated', 'CR', 'HR', 'NO', 'Plate', 'Sheet', 'Tinplate']
        for indicator in product_indicators:
            if indicator in parts:
                metadata['product_category'] = indicator
                break

        # Extract case number (A-580-878 or C-580-882 pattern)
        case_pattern = r'([AC]-\d{3}-\d{3})'
        case_match = re.search(case_pattern, name)
        if case_match:
            metadata['case_number'] = case_match.group(1)

        # Extract year
        year_pattern = r'_(\\d{4})'
        year_match = re.search(year_pattern, name)
        if year_match:
            metadata['investigation_year'] = int(year_match.group(1))

        # Extract status
        if '_F_' in name or name.endswith('_F'):
            metadata['status'] = 'Final'
        elif '_Pre_' in name or 'Preliminary' in name:
            metadata['status'] = 'Preliminary'

        # Extract Brazilian regulation number (PORTARIA Nº 495)
        portaria_pattern = r'PORTARIA\\s+N[ºo°]\\s*(\\d+)'
        portaria_match = re.search(portaria_pattern, name, re.IGNORECASE)
        if portaria_match:
            metadata['regulation_number'] = f"PORTARIA Nº {portaria_match.group(1)}"

        # Extract Brazilian date
        month_map = {
            'JANEIRO': 1, 'FEVEREIRO': 2, 'MARÇO': 3, 'ABRIL': 4,
            'MAIO': 5, 'JUNHO': 6, 'JULHO': 7, 'AGOSTO': 8,
            'SETEMBRO': 9, 'OUTUBRO': 10, 'NOVEMBRO': 11, 'DEZEMBRO': 12
        }

        for month_name, month_num in month_map.items():
            date_pattern = rf'(\\d{{1,2}})\\s+DE\\s+{month_name}\\s+DE\\s+(\\d{{4}})'
            date_match = re.search(date_pattern, name, re.IGNORECASE)
            if date_match:
                day = int(date_match.group(1))
                year = int(date_match.group(2))
                metadata['effective_date'] = f"{year:04d}-{month_num:02d}-{day:02d}"
                metadata['investigation_year'] = year
                break

        return metadata

    def get_country_id(self, country_code: str) -> int:
        """Get or create country ID from code"""
        # Map common variations
        country_map = {
            'USA': 'USA',
            'US': 'USA',
            'EU': 'EU',
            'Korea': 'KR',
            'Japan': 'JP',
            'China': 'CN',
            'Thailand': 'TH',
            'Indonesia': 'ID',
            'Vietnam': 'VN',
            'Taiwan': 'TW'
        }

        mapped_code = country_map.get(country_code, country_code)

        self.db.cursor.execute(
            "SELECT country_id FROM countries WHERE country_code = ?",
            (mapped_code,)
        )
        result = self.db.cursor.fetchone()

        if result:
            return result['country_id']

        # If not found, create new country
        return self.db.insert_country(country_code, country_code)

    def import_malaysian_pdf(self, doc_id: int):
        """Special handling for Malaysian PDF - data from pages 3-5"""
        print(f"  📋 Using Malaysian company data (pages 3-5)")

        companies = [
            # China - 2 companies (page 3-4)
            ("Shougang Jingtang United Iron & Steel Co., Ltd.", "CN", "7.72", "%", "Exporter"),
            ("All Other Exporters (excluding Baoshan, Beijing Shougang, Fujian Kaijing)", "CN", "26.80", "%", "Exporter"),

            # Korea - 4 companies (page 4)
            ("Hyundai Steel Company", "KR", "5.61", "%", "Exporter"),
            ("KG Dongbu Steel Co., Ltd.", "KR", "13.82", "%", "Exporter"),
            ("POSCO", "KR", "2.21", "%", "Exporter"),
            ("All Other Exporters", "KR", "31.47", "%", "Exporter"),

            # Vietnam - 6 companies (page 4-5)
            ("China Steel and Nippon Steel Vietnam Joint Stock Company", "VN", "4.76", "%", "Exporter"),
            ("Southern Steel Sheet Co., Ltd.", "VN", "9.91", "%", "Exporter"),
            ("Tan Phuoc Khanh Trading and Manufacturing Coil Steel Joint Stock Company", "VN", "48.05", "%", "Exporter"),
            ("Tay Nam Steel Manufacturing & Trading Co., Ltd.", "VN", "42.58", "%", "Exporter"),
            ("TVP Steel Joint Stock Company", "VN", "42.58", "%", "Exporter"),
            ("All Other Exporters (excluding Hoa Phat, Hoa Sen, Nam Kim, Ton Dong A)", "VN", "57.90", "%", "Exporter"),
        ]

        # Get country IDs
        country_ids = {}
        for country_code in ['CN', 'KR', 'VN']:
            self.db.cursor.execute("SELECT country_id FROM countries WHERE country_code = ?", (country_code,))
            result = self.db.cursor.fetchone()
            if result:
                country_ids[country_code] = result['country_id']

        # Insert companies
        for company_name, country_code, duty_rate, duty_unit, company_type in companies:
            company_data = {
                'doc_id': doc_id,
                'company_name': company_name,
                'country_id': country_ids.get(country_code),
                'duty_rate': duty_rate,
                'duty_rate_unit': duty_unit,
                'company_type': company_type
            }
            self.db.insert_company(company_data)

        print(f"  ✓ Companies: {len(companies)} companies with rates from pages 3-5")

    def import_eu_pdf(self, doc_id: int):
        """Special handling for EU PDF - individual producer rates + MIP system"""
        print(f"  📋 Using corrected EU producer-specific rates")

        companies = [
            # China
            ("Baoshan Iron & Steel Co., Ltd.", "CN", "21.5", "%", "Producer"),
            ("Wuhan Iron and Steel Co., Ltd.", "CN", "36.6", "%", "Producer"),
            ("All Other Companies", "CN", "39.0", "%", "Producer"),

            # Japan
            ("JFE Steel Corporation", "JP", "39.0", "%", "Producer"),
            ("Nippon Steel Corporation (formerly Nippon Steel & Sumitomo Metal Corporation)", "JP", "35.9", "%", "Producer"),
            ("All Other Companies", "JP", "39.0", "%", "Producer"),

            # Korea
            ("POSCO", "KR", "22.5", "%", "Producer"),
            ("All Other Companies", "KR", "39.0", "%", "Producer"),

            # Russia
            ("OJSC Novolipetsk Steel (NLMK)", "RU", "21.6", "%", "Producer"),
            ("PJSC Severstal", "RU", "21.6", "%", "Producer"),
            ("VIZ Steel", "RU", "21.6", "%", "Producer"),
            ("All Other Companies", "RU", "39.0", "%", "Producer"),

            # USA
            ("AK Steel Corporation", "US", "22.0", "%", "Producer"),
            ("All Other Companies", "US", "39.0", "%", "Producer"),
        ]

        # Get country IDs (map US -> USA for database compatibility)
        country_ids = {}
        country_map = {'CN': 'CN', 'JP': 'JP', 'KR': 'KR', 'RU': 'RU', 'US': 'USA'}
        for original_code, db_code in country_map.items():
            self.db.cursor.execute("SELECT country_id FROM countries WHERE country_code = ?", (db_code,))
            result = self.db.cursor.fetchone()
            if result:
                country_ids[original_code] = result['country_id']

        # Insert companies
        for company_name, country_code, duty_rate, duty_unit, company_type in companies:
            company_data = {
                'doc_id': doc_id,
                'company_name': company_name,
                'country_id': country_ids.get(country_code),
                'duty_rate': duty_rate,
                'duty_rate_unit': duty_unit,
                'company_type': company_type
            }
            self.db.insert_company(company_data)

        print(f"  ✓ Companies: {len(companies)} producers with individual rates")

        # Add MIP information as tags
        self.db.insert_tag(doc_id, 'duty_type', 'MIP')
        self.db.insert_tag(doc_id, 'mip_min', 'EUR 1,536/tonne')
        self.db.insert_tag(doc_id, 'mip_max', 'EUR 2,043/tonne')
        print(f"  ✓ MIP information: EUR 1,536 - 2,043/tonne")

    def import_single_pdf(self, pdf_filename: str):
        """Import a single PDF file into database"""
        print(f"\nProcessing: {pdf_filename}")

        # Parse filename
        metadata = self.parse_filename(pdf_filename)

        # Get country ID
        if metadata['issuing_country']:
            country_id = self.get_country_id(metadata['issuing_country'])
        else:
            print(f"  ✗ Could not determine country")
            return None

        # Parse PDF content to extract detailed information
        pdf_path = os.path.join(self.pdf_folder, pdf_filename)

        # Check if this is a special case PDF
        is_malaysian = 'MALAYSIA' in pdf_filename
        is_eu = 'EU' in pdf_filename and 'GO' in pdf_filename

        if not is_malaysian and not is_eu:
            print(f"  Parsing PDF content...")
            parser = TradeRemedyPDFParser(pdf_path)
            parsed_data = parser.extract_all()
        else:
            # For Malaysian and EU PDFs, use minimal parsing
            print(f"  Special handling for {pdf_filename}")
            parsed_data = {
                'target_countries': [],
                'hs_codes': [],
                'companies': [],
                'investigation_period': None,
                'effective_date': None,
                'expiry_date': None,
                'regulation_number': None
            }

        # Extract investigation period
        investigation_start = None
        investigation_end = None
        if parsed_data.get('investigation_period'):
            investigation_start, investigation_end = parsed_data['investigation_period']

        # Prepare document data
        doc_data = {
            'file_name': pdf_filename,
            'issuing_country_id': country_id,
            'measure_type': metadata['measure_type'],
            'product_category': metadata['product_category'],
            'case_number': metadata['case_number'],
            'regulation_number': metadata.get('regulation_number') or parsed_data.get('regulation_number'),
            'status': metadata['status'],
            'effective_date': parsed_data.get('effective_date') or metadata.get('effective_date'),
            'expiry_date': parsed_data.get('expiry_date'),
            'investigation_year': metadata['investigation_year'],
            'total_pages': None,
            'file_path': pdf_path
        }

        # Insert document
        doc_id = self.db.insert_document(doc_data)
        print(f"  ✓ Document ID: {doc_id}")

        # Handle special PDFs
        if is_malaysian:
            # Hardcoded Malaysian data
            self.import_malaysian_pdf(doc_id)

            # Add target countries manually
            for country_code in ['CN', 'KR', 'VN']:
                target_country_id = self.get_country_id(country_code)
                self.db.insert_target_country(doc_id, target_country_id)
            print(f"  ✓ Target countries: CN, KR, VN")

            # Add HS codes manually (from page 3-4)
            hs_codes = [
                ('7210.49.11', 'Galvanized steel coils/sheets'),
                ('7210.49.17', 'Galvanized steel coils/sheets'),
                ('7210.49.18', 'Galvanized steel coils/sheets'),
                ('7210.49.19', 'Galvanized steel coils/sheets'),
                ('7210.49.91', 'Galvanized steel coils/sheets'),
                ('7210.49.99', 'Galvanized steel coils/sheets'),
                ('7212.30.11', 'Galvanized steel coils/sheets'),
                ('7212.30.12', 'Galvanized steel coils/sheets'),
                ('7212.30.13', 'Galvanized steel coils/sheets'),
                ('7212.30.14', 'Galvanized steel coils/sheets'),
                ('7212.30.19', 'Galvanized steel coils/sheets'),
                ('7212.30.90', 'Galvanized steel coils/sheets'),
                ('7225.92.90', 'Galvanized steel coils/sheets'),
                ('7225.99.90', 'Galvanized steel coils/sheets'),
                ('7226.99.11', 'Galvanized steel coils/sheets'),
                ('7226.99.19', 'Galvanized steel coils/sheets'),
                ('7226.99.91', 'Galvanized steel coils/sheets'),
                ('7226.99.99', 'Galvanized steel coils/sheets'),
            ]
            for hs_code, description in hs_codes:
                self.db.insert_hs_code(doc_id, hs_code, description)
            print(f"  ✓ HS codes: {len(hs_codes)} codes")

        elif is_eu:
            # Hardcoded EU data
            self.import_eu_pdf(doc_id)

            # Add target countries manually (map US -> USA for database)
            for country_code in ['CN', 'JP', 'KR', 'RU', 'USA']:
                target_country_id = self.get_country_id(country_code)
                self.db.insert_target_country(doc_id, target_country_id)
            print(f"  ✓ Target countries: CN, JP, KR, RU, USA")

            # Add HS codes manually
            hs_codes = [
                ('7225.11.00', 'Grain-oriented silicon-electrical steel'),
                ('7226.11.00', 'Grain-oriented silicon-electrical steel (coated)')
            ]
            for hs_code, description in hs_codes:
                self.db.insert_hs_code(doc_id, hs_code, description)
            print(f"  ✓ HS codes: {len(hs_codes)} codes")

        else:
            # Normal processing for other PDFs
            # Insert target countries
            if parsed_data.get('target_countries'):
                for country_code in parsed_data['target_countries']:
                    target_country_id = self.get_country_id(country_code)
                    self.db.insert_target_country(doc_id, target_country_id)
                print(f"  ✓ Target countries: {', '.join(parsed_data['target_countries'])}")

            # Insert HS codes
            if parsed_data.get('hs_codes'):
                for hs_code, description in parsed_data['hs_codes']:
                    self.db.insert_hs_code(doc_id, hs_code, description)
                print(f"  ✓ HS codes: {len(parsed_data['hs_codes'])} codes")

            # Insert companies and duty rates
            if parsed_data.get('companies'):
                for company in parsed_data['companies']:
                    company_data = {
                        'doc_id': doc_id,
                        'company_name': company['company_name'],
                        'country_id': None,
                        'duty_rate': company['duty_rate'],
                        'duty_rate_unit': company['duty_rate_unit'],
                        'company_type': 'Exporter'
                    }
                    self.db.insert_company(company_data)
                print(f"  ✓ Companies: {len(parsed_data['companies'])} companies with duty rates")

        # Add tags for easier searching
        if metadata['measure_type']:
            self.db.insert_tag(doc_id, 'measure_type', metadata['measure_type'])

        if metadata['product_category']:
            self.db.insert_tag(doc_id, 'product', metadata['product_category'])

        # Add investigation period as tags
        if investigation_start:
            self.db.insert_tag(doc_id, 'investigation_start', investigation_start)
        if investigation_end:
            self.db.insert_tag(doc_id, 'investigation_end', investigation_end)

        return doc_id

    def import_all_pdfs(self):
        """Import all PDF files from the PDF folder"""
        if not os.path.exists(self.pdf_folder):
            print(f"Error: PDF folder not found: {self.pdf_folder}")
            return

        pdf_files = [f for f in os.listdir(self.pdf_folder) if f.endswith('.pdf')]

        if not pdf_files:
            print(f"No PDF files found in {self.pdf_folder}")
            return

        print(f"\n=== Importing {len(pdf_files)} PDF files ===")

        successful = 0
        for pdf_file in pdf_files:
            try:
                doc_id = self.import_single_pdf(pdf_file)
                if doc_id:
                    successful += 1
            except Exception as e:
                print(f"  ✗ Error: {e}")

        print(f"\n=== Import Complete ===")
        print(f"Successfully imported: {successful}/{len(pdf_files)} documents")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main import process"""
    print("=== Trade Remedy Database Importer ===\n")

    # Create database
    db = TradeRemedyDB("trade_remedy.db")

    # Initialize countries if empty
    db.cursor.execute("SELECT COUNT(*) as count FROM countries")
    if db.cursor.fetchone()['count'] == 0:
        initialize_countries(db)

    # Import PDFs
    importer = PDFImporter(db)
    importer.import_all_pdfs()

    # Show summary
    print("\n=== Database Summary ===")

    db.cursor.execute("SELECT COUNT(*) as count FROM documents")
    doc_count = db.cursor.fetchone()['count']
    print(f"Total documents: {doc_count}")

    db.cursor.execute("SELECT COUNT(*) as count FROM companies")
    company_count = db.cursor.fetchone()['count']
    print(f"Total companies: {company_count}")

    db.cursor.execute("""
        SELECT c.country_code, c.country_name, COUNT(d.doc_id) as doc_count
        FROM countries c
        LEFT JOIN documents d ON c.country_id = d.issuing_country_id
        GROUP BY c.country_id
        HAVING doc_count > 0
        ORDER BY doc_count DESC
    """)

    print("\nDocuments by country:")
    for row in db.cursor.fetchall():
        print(f"  {row['country_code']} ({row['country_name']}): {row['doc_count']} documents")

    db.cursor.execute("""
        SELECT measure_type, COUNT(*) as count
        FROM documents
        WHERE measure_type IS NOT NULL
        GROUP BY measure_type
    """)

    print("\nDocuments by measure type:")
    for row in db.cursor.fetchall():
        print(f"  {row['measure_type']}: {row['count']} documents")

    db.close()
    print("\n✓ Database ready: trade_remedy.db")


if __name__ == "__main__":
    main()

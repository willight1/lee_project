"""
Database Module

Manages SQLite database for tariff data storage.
"""

import sqlite3
from typing import Dict


class TariffDatabase:
    """Improved database with additional fields for better data organization"""

    def __init__(self, db_path: str = "tariff_data.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        """Create database tables with improved schema"""

        # Documents table - PDF metadata
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL UNIQUE,
                file_path TEXT NOT NULL,
                issuing_country TEXT,
                total_pages INTEGER,
                file_size INTEGER,
                processing_mode TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Pages table - Raw text content (for RAW mode if needed)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS pages (
                page_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                raw_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE,
                UNIQUE(doc_id, page_number)
            )
        """)

        # Tariff items table - Structured tariff data with improved fields
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS tariff_items (
                tariff_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER NOT NULL,
                issuing_country TEXT,
                country TEXT,
                hs_code TEXT,
                tariff_type TEXT,
                tariff_rate REAL,
                effective_date_from TEXT,
                effective_date_to TEXT,
                investigation_period_from TEXT,
                investigation_period_to TEXT,
                basis_law TEXT,
                company TEXT,
                case_number TEXT,
                product_description TEXT,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
            )
        """)

        # Add issuing_country column if it doesn't exist (for existing databases)
        try:
            self.cursor.execute("ALTER TABLE tariff_items ADD COLUMN issuing_country TEXT")
            self.conn.commit()
            print("  ✓ Added issuing_country column to tariff_items")
        except sqlite3.OperationalError:
            # Column already exists
            pass

        # Create indexes for faster queries
        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tariff_hs_code ON tariff_items(hs_code)
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tariff_country ON tariff_items(country)
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_doc_issuing_country ON documents(issuing_country)
        """)

        self.cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tariff_issuing_country ON tariff_items(issuing_country)
        """)

        self.conn.commit()
        print(f"✓ Database initialized: {self.db_path}")

    def insert_document(self, file_name: str, file_path: str, issuing_country: str,
                       total_pages: int, file_size: int, processing_mode: str) -> int:
        """Insert or update document record"""
        try:
            self.cursor.execute("""
                INSERT INTO documents (file_name, file_path, issuing_country, total_pages, file_size, processing_mode)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_name) DO UPDATE SET
                    file_path = excluded.file_path,
                    issuing_country = excluded.issuing_country,
                    total_pages = excluded.total_pages,
                    file_size = excluded.file_size,
                    processing_mode = excluded.processing_mode,
                    created_at = CURRENT_TIMESTAMP
            """, (file_name, file_path, issuing_country, total_pages, file_size, processing_mode))

            self.conn.commit()

            # Get the doc_id
            self.cursor.execute("SELECT doc_id FROM documents WHERE file_name = ?", (file_name,))
            return self.cursor.fetchone()['doc_id']

        except Exception as e:
            print(f"  ✗ Error inserting document: {e}")
            self.conn.rollback()
            return None

    def upsert_or_merge_tariff_item(self, doc_id: int, item: Dict, issuing_country: str = None) -> str:
        """
        Tariff item 병합 삽입.
        - 기존 데이터가 있으면: null 필드만 새 값으로 채움 (기존 값 유지)
        - 기존 데이터가 없으면: 새로 삽입
        
        매칭 기준: doc_id + country + company + hs_code + case_number
        
        Returns: 'inserted' (신규), 'merged' (병합), 'skipped' (변경 없음), 'error' (오류)
        """
        try:
            # 매칭 키 생성
            country = item.get('country')
            company = item.get('company')
            hs_code = item.get('hs_code')
            case_number = item.get('case_number')
            
            # 기존 데이터 찾기 (매칭 기준: 주요 키 조합)
            self.cursor.execute("""
                SELECT tariff_id, country, hs_code, tariff_type, tariff_rate,
                       effective_date_from, effective_date_to,
                       investigation_period_from, investigation_period_to,
                       basis_law, company, case_number, product_description, note
                FROM tariff_items
                WHERE doc_id = ?
                  AND (country = ? OR (country IS NULL AND ? IS NULL))
                  AND (company = ? OR (company IS NULL AND ? IS NULL))
                  AND (hs_code = ? OR (hs_code IS NULL AND ? IS NULL))
                  AND (case_number = ? OR (case_number IS NULL AND ? IS NULL))
            """, (doc_id, country, country, company, company, hs_code, hs_code, case_number, case_number))
            
            existing = self.cursor.fetchone()
            
            if existing:
                # 기존 데이터가 있으면 null 필드만 업데이트
                tariff_id = existing['tariff_id']
                updates = {}
                
                # 업데이트 가능한 필드들
                fields_to_check = [
                    ('tariff_type', item.get('tariff_type')),
                    ('tariff_rate', item.get('tariff_rate')),
                    ('effective_date_from', item.get('effective_date_from')),
                    ('effective_date_to', item.get('effective_date_to')),
                    ('investigation_period_from', item.get('investigation_period_from')),
                    ('investigation_period_to', item.get('investigation_period_to')),
                    ('basis_law', item.get('basis_law')),
                    ('product_description', item.get('product_description')),
                    ('note', item.get('note')),
                    # 키 필드도 null이면 채움
                    ('country', country),
                    ('company', company),
                    ('hs_code', hs_code),
                    ('case_number', case_number),
                ]
                
                for field_name, new_value in fields_to_check:
                    # 기존 값이 null이고 새 값이 있으면 업데이트
                    if existing[field_name] is None and new_value is not None:
                        updates[field_name] = new_value
                
                if updates:
                    set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
                    values = list(updates.values()) + [tariff_id]
                    
                    self.cursor.execute(f"""
                        UPDATE tariff_items
                        SET {set_clause}
                        WHERE tariff_id = ?
                    """, values)
                    self.conn.commit()
                    return 'merged'
                else:
                    return 'skipped'
            else:
                # 기존 데이터가 없으면 새로 삽입
                self.cursor.execute("""
                    INSERT INTO tariff_items (
                        doc_id, issuing_country, country, hs_code, tariff_type, tariff_rate,
                        effective_date_from, effective_date_to,
                        investigation_period_from, investigation_period_to,
                        basis_law, company, case_number, product_description, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    doc_id, 
                    issuing_country, 
                    country,
                    hs_code,
                    item.get('tariff_type'),
                    item.get('tariff_rate'),
                    item.get('effective_date_from'),
                    item.get('effective_date_to'),
                    item.get('investigation_period_from'),
                    item.get('investigation_period_to'),
                    item.get('basis_law'),
                    company,
                    case_number,
                    item.get('product_description'),
                    item.get('note')
                ))
                self.conn.commit()
                return 'inserted'
                
        except Exception as e:
            print(f"  ✗ Error upserting tariff item: {e}")
            print(f"     Item: {item}")
            self.conn.rollback()
            return 'error'

    def insert_tariff_item(self, doc_id: int, item: Dict, issuing_country: str = None) -> bool:
        """
        Insert tariff item (단순 INSERT).
        Returns: True (성공), False (실패)
        """
        try:
            self.cursor.execute("""
                INSERT INTO tariff_items (
                    doc_id, issuing_country, country, hs_code, tariff_type, tariff_rate,
                    effective_date_from, effective_date_to,
                    investigation_period_from, investigation_period_to,
                    basis_law, company, case_number, product_description, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                doc_id, 
                issuing_country, 
                item.get('country'),
                item.get('hs_code'),
                item.get('tariff_type'),
                item.get('tariff_rate'),
                item.get('effective_date_from'),
                item.get('effective_date_to'),
                item.get('investigation_period_from'),
                item.get('investigation_period_to'),
                item.get('basis_law'),
                item.get('company'),
                item.get('case_number'),
                item.get('product_description'),
                item.get('note')
            ))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"  ✗ Error inserting tariff item: {e}")
            print(f"     Item: {item}")
            self.conn.rollback()
            return False

    def delete_tariff_items_by_doc(self, doc_id: int):
        """Delete all tariff items for a document"""
        self.cursor.execute("DELETE FROM tariff_items WHERE doc_id = ?", (doc_id,))
        self.conn.commit()

    def get_stats(self) -> Dict:
        """Get database statistics"""
        stats = {}

        self.cursor.execute("SELECT COUNT(*) as count FROM documents")
        stats['total_documents'] = self.cursor.fetchone()['count']

        self.cursor.execute("SELECT COUNT(*) as count FROM tariff_items")
        stats['total_tariff_items'] = self.cursor.fetchone()['count']

        self.cursor.execute("""
            SELECT issuing_country, COUNT(*) as count
            FROM documents
            WHERE issuing_country IS NOT NULL
            GROUP BY issuing_country
            ORDER BY count DESC
        """)
        stats['by_issuing_country'] = dict(self.cursor.fetchall())

        return stats

    def close(self):
        """Close database connection"""
        self.conn.close()

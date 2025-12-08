#!/usr/bin/env python3
"""
국가명 정규화 스크립트
기존 DB의 country 필드를 표준 형식으로 업데이트

사용법:
    python normalize_countries.py
"""

import sqlite3

# 국가명 정규화 매핑 테이블
COUNTRY_NAME_MAPPING = {
    # 한국
    "Republic of Korea": "South Korea",
    "The Republic of Korea": "South Korea",
    "Korea": "South Korea",
    "Rep. of Korea": "South Korea",
    "ROK": "South Korea",
    
    # 중국
    "People's Republic of China": "China",
    "The People's Republic of China": "China",
    "P.R.C": "China",
    "PRC": "China",
    
    # 베트남
    "The Socialist Republic of Viet Nam": "Vietnam",
    "Socialist Republic of Viet Nam": "Vietnam",
    "The Socialist Republic of Vietnam": "Vietnam",
    "Socialist Republic of Vietnam": "Vietnam",
    "Republik Sosialis Viet Nam": "Vietnam",
    "Viet Nam": "Vietnam",
    
    # 대만
    "Chinese Taipei": "Taiwan",
    "Republic of China": "Taiwan",
    
    # 태국
    "Kingdom of Thailand": "Thailand",
    
    # 인도네시아
    "Republic of Indonesia": "Indonesia",
    "Republik Indonesia": "Indonesia",
    
    # EU
    "European Union": "EU",
    
    # 터키
    "Republic of Turkey": "Turkey",
    "Türkiye": "Turkey",
    
    # 러시아
    "Russian Federation": "Russia",
    
    # 미국
    "United States of America": "USA",
    "United States": "USA",
    "U.S.A": "USA",
    
    # 인도
    "Republic of India": "India",
    
    # 브라질
    "Federative Republic of Brazil": "Brazil",
    
    # 호주
    "Commonwealth of Australia": "Australia",
    
    # 영국
    "United Kingdom": "UK",
    "Great Britain": "UK",
    
    # 네덜란드
    "The Netherlands": "Netherlands",

    # 잘못된 값
    "Country name": None,  # 삭제 대상
}


def normalize_countries(db_path: str = "tariff_data.db"):
    """기존 DB의 국가명을 정규화"""
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("=" * 60)
    print("국가명 정규화 시작")
    print("=" * 60)
    
    # 현재 국가명 분포 확인
    cursor.execute("""
        SELECT country, COUNT(*) as count 
        FROM tariff_items 
        WHERE country IS NOT NULL 
        GROUP BY country 
        ORDER BY count DESC
    """)
    
    current_countries = cursor.fetchall()
    print(f"\n현재 국가명 분포 ({len(current_countries)}개 유형):")
    for country, count in current_countries[:10]:
        print(f"  {country}: {count}")
    if len(current_countries) > 10:
        print(f"  ... 외 {len(current_countries) - 10}개")
    
    # 정규화 실행
    total_updated = 0
    
    for old_name, new_name in COUNTRY_NAME_MAPPING.items():
        if new_name is None:
            # 잘못된 값 삭제
            cursor.execute(
                "DELETE FROM tariff_items WHERE country = ?",
                (old_name,)
            )
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"  ✗ 삭제: '{old_name}' ({deleted}건)")
                total_updated += deleted
        else:
            # 정규화 업데이트
            cursor.execute(
                "UPDATE tariff_items SET country = ? WHERE country = ?",
                (new_name, old_name)
            )
            updated = cursor.rowcount
            if updated > 0:
                print(f"  ✓ '{old_name}' → '{new_name}' ({updated}건)")
                total_updated += updated
    
    conn.commit()
    
    # 정규화 후 국가명 분포 확인
    cursor.execute("""
        SELECT country, COUNT(*) as count 
        FROM tariff_items 
        WHERE country IS NOT NULL 
        GROUP BY country 
        ORDER BY count DESC
    """)
    
    new_countries = cursor.fetchall()
    print(f"\n정규화 후 국가명 분포 ({len(new_countries)}개 유형):")
    for country, count in new_countries:
        print(f"  {country}: {count}")
    
    print(f"\n총 {total_updated}건 업데이트 완료")
    print("=" * 60)
    
    conn.close()


if __name__ == "__main__":
    normalize_countries()

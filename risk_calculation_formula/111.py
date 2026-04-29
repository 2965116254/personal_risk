#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pymysql
from pymysql.cursors import DictCursor
import csv

DB_CONFIG = {
    'host': '192.168.176.229',
    'port': 23306,
    'user': 'root',
    'password': 'hyetec@2025_personal_risk',
    'database': 'hvdc_risk_db',
    'charset': 'utf8mb4'
}

OUTPUT_CSV = "db_structure.csv"

def get_connection():
    try:
        conn = pymysql.connect(**DB_CONFIG, cursorclass=DictCursor)
        return conn
    except pymysql.Error as e:
        print(f"数据库连接失败: {e}")
        exit(1)

def get_all_tables(conn):
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT TABLE_NAME, TABLE_COMMENT
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = %s
            ORDER BY TABLE_NAME
        """, (DB_CONFIG['database'],))
        return cursor.fetchall()

def get_columns_info(conn, table_name):
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_KEY,
                COLUMN_COMMENT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
            ORDER BY ORDINAL_POSITION
        """, (DB_CONFIG['database'], table_name))
        return cursor.fetchall()

def main():
    conn = get_connection()
    try:
        tables = get_all_tables(conn)
        if not tables:
            print(f"数据库 '{DB_CONFIG['database']}' 中没有表。")
            return

        print(f"发现 {len(tables)} 张表，正在生成 CSV...")

        # 写入 CSV（带 UTF-8 BOM，使 Excel 打开时中文正常）
        with open(OUTPUT_CSV, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            # 写入表头
            writer.writerow(['表名', '表注释', '字段名', '数据类型', '是否可空', '键类型', '字段注释'])

            for idx, table_row in enumerate(tables, 1):
                table_name = table_row['TABLE_NAME']
                table_comment = table_row['TABLE_COMMENT'] or ''
                columns = get_columns_info(conn, table_name)

                for col in columns:
                    writer.writerow([
                        table_name,
                        table_comment,
                        col['COLUMN_NAME'],
                        col['DATA_TYPE'],
                        'YES' if col['IS_NULLABLE'] == 'YES' else 'NO',
                        col['COLUMN_KEY'] or '',
                        col['COLUMN_COMMENT'] or ''
                    ])
                print(f"已处理 {idx}/{len(tables)}: {table_name}")

        print(f"导出完成！文件已保存为：{OUTPUT_CSV}")

    finally:
        conn.close()

if __name__ == '__main__':
    main()
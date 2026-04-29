#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
@Project ：personal_risk_prevention_agent 
@File    ：work_operation_ticket_plan_DB.py
@IDE     ：PyCharm 
@Author  ：BingshengTian
@Date    ：2026-01-20 14:54 
'''

import os
import logging
from contextlib import contextmanager

import pandas as pd
from dbutils.pooled_db import PooledDB
import pymysql
from dotenv import load_dotenv
# 加载环境变量
load_dotenv()

class WorkOperationTicketPlanMySQLConnectionPool:
    def __init__(self):
        self.pool = PooledDB(
            creator=pymysql,
            host=os.getenv('DB_HOST', '192.168.176.229'),
            port=int(os.getenv('DB_PORT', 23306)),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'),
            charset=os.getenv('DB_CHARSET', 'utf8mb4'),
            maxconnections=int(os.getenv('DB_MAX_CONNECTIONS', 10)),
            blocking=True,  # 连接池无连接时是否等待
            ping=0,  # 不主动 ping，由程序控制
        )
        logging.info("MySQL connection pool initialized.")

    @contextmanager
    def get_connection(self):
        """上下文管理器，自动获取和释放连接"""
        conn = self.pool.connection()
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            logging.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def clear_database(self, confirm: str = ""):
        """
        清空当前数据库所有表。
        :param confirm: 必须传入 "CONFIRM_CLEAR" 才执行，防止误操作
        """
        if os.getenv("ALLOW_CLEAR_DB", "false").lower() != "true":
            raise RuntimeError("清库功能未启用。请设置 ALLOW_CLEAR_DB=true 环境变量（仅限测试环境）！")

        if confirm != "CONFIRM_CLEAR":
            raise ValueError("缺少确认参数。请传入 confirm='CONFIRM_CLEAR' 以确认清库操作。")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                # 获取当前数据库名
                cursor.execute("SELECT DATABASE();")
                db_name = cursor.fetchone()[0]
                if not db_name:
                    raise RuntimeError("No database selected.")

                logging.info(f"Clearing database: {db_name}")

                # 禁用外键检查
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")

                # 获取所有表名
                cursor.execute("SHOW TABLES;")
                tables = cursor.fetchall()
                table_names = [table[0] for table in tables]

                if not table_names:
                    logging.info("No tables found. Database is already empty.")
                    return

                # 生成 DROP TABLE 语句
                drop_sql = "DROP TABLE IF EXISTS " + ", ".join(f"`{name}`" for name in table_names) + ";"
                cursor.execute(drop_sql)

                # 重新启用外键检查
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

                conn.commit()
                logging.info(f"Successfully dropped {len(table_names)} tables from database '{db_name}'.")

            except Exception as e:
                conn.rollback()
                logging.error(f"Failed to clear database: {e}")
                raise

    def query_one(self, sql, params=None):
        """查询单条记录"""
        with self.get_connection() as conn:
            cursor = conn.cursor(pymysql.cursors.DictCursor)  # 使用字典游标
            cursor.execute(sql, params)
            result = cursor.fetchone()
            cursor.close()
            return result

    def query_all(self, sql, params=None):
        """查询多条记录"""
        with self.get_connection() as conn:
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(sql, params)
            result = cursor.fetchall()
            cursor.close()
            return result

    def execute(self, sql, params=None, commit=True):
        """执行 INSERT/UPDATE/DELETE"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql, params)
                if commit:
                    conn.commit()
                return cursor.rowcount
            except Exception as e:
                conn.rollback()
                logging.error(f"Execute SQL failed: {sql}, params: {params}, error: {e}")
                raise
            finally:
                cursor.close()

    def execute_many(self, sql, params_list, commit=True):
        """批量执行"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.executemany(sql, params_list)
                if commit:
                    conn.commit()
                return cursor.rowcount
            except Exception as e:
                conn.rollback()
                logging.error(f"Execute many failed: {e}")
                raise
            finally:
                cursor.close()

    # 列出当前数据库中的所有表
    def list_tables(self):
        """列出当前数据库中的所有表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SHOW TABLES;")
            tables = cursor.fetchall()
            cursor.close()
            return [table[0] for table in tables]

    # 作业文件-计划关联表（人生风险模块计划）  work_document_plan_association_table
    # 根据作业计划编号查询作业文件信息
    def query_work_plan_file_info(self, work_plan_code):
        sql = "SELECT guidebook_name, work_location, work_content FROM work_document_plan_association_table WHERE plan_number = %s;"
        return self.query_all(sql, (work_plan_code,))


    def close(self):
        """关闭连接池（通常不需要手动调用）"""
        self.pool.close()
        logging.info("MySQL connection pool closed.")


# 全局实例（单例模式）
work_operation_plan_db = WorkOperationTicketPlanMySQLConnectionPool()

if __name__ == '__main__':
    # 全局实例（单例模式）

    # 测试：计划编号：JH010920220328001597
    info = work_operation_plan_db.query_work_plan_file_info('JH01092022032800197')

    print(info)
    # 如果info为空，说明没有查询到相关记录
    if not info:
        print("没有查询到相关记录")




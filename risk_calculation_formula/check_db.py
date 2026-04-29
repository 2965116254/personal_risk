import mysql.connector

# 数据库配置
db_config = {
    'host': '192.168.176.229',
    'port': 23306,
    'user': 'root',
    'password': 'hyetec@2025_personal_risk',
    'database': 'hvdc_risk_db'
}

try:
    # 连接数据库
    connection = mysql.connector.connect(**db_config)
    cursor = connection.cursor()
    
    # 显示所有表
    print("数据库中的表:")
    cursor.execute("SHOW TABLES")
    tables = cursor.fetchall()
    for table in tables:
        print(f"- {table[0]}")
    
    # 显示sp_ss_uq_peccancy_list_log表的字段结构
    print("\nsp_ss_uq_peccancy_list_log表的字段结构:")
    cursor.execute("DESCRIBE sp_ss_uq_peccancy_list_log")
    fields = cursor.fetchall()
    for field in fields:
        print(f"- {field[0]}: {field[1]}")
    
    # 关闭连接
    cursor.close()
    connection.close()
    
    print("\n检查完成")
    
except Exception as e:
    print(f"错误: {e}")

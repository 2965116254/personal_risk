import mysql.connector
import config_loader

def test_db_connection():
    # 将输出写入文件
    with open('test_output.txt', 'w', encoding='utf-8') as f:
        f.write("开始测试数据库连接...\n")
        try:
            # 获取新数据库配置
            db_config = config_loader.get_db_new_config()
            f.write(f"数据库配置: {db_config}\n")
            
            # 创建数据库连接
            connection = mysql.connector.connect(
                host=db_config['host'],
                port=db_config['port'],
                user=db_config['user'],
                password=db_config['password'],
                database=db_config['database']
            )
            f.write("数据库连接成功\n")
            
            cursor = connection.cursor(dictionary=True)
            
            # 测试查询操作票表
            f.write("测试查询操作票表...\n")
            query = "SELECT id, work_principal_uid, work_member_uid, guardian_uid, work_member_count FROM sp_pd_wticket_base LIMIT 5"
            cursor.execute(query)
            tickets = cursor.fetchall()
            f.write(f"找到 {len(tickets)} 张操作票\n")
            for ticket in tickets:
                f.write(f"操作票ID: {ticket['id']}, 工作负责人: {ticket['work_principal_uid']}\n")
            
            # 测试查询违章记录
            f.write("测试查询违章记录...\n")
            if tickets:
                # 收集人员ID
                user_ids = set()
                for ticket in tickets:
                    if ticket.get('work_principal_uid'):
                        user_ids.add(ticket.get('work_principal_uid'))
                
                f.write(f"收集到 {len(user_ids)} 个人员ID\n")
                if user_ids:
                    placeholders = ','.join(['%s'] * len(user_ids))
                    peccancy_query = f"""
                    SELECT 
                        peccancy_uid,
                        peccancy_code,
                        COUNT(*) as count
                    FROM sp_ss_uq_peccancy_list_log 
                    WHERE peccancy_uid IN ({placeholders})
                    AND YEAR(record_date) = 2025
                    GROUP BY peccancy_uid, peccancy_code
                    """
                    peccancy_params = list(user_ids)
                    f.write(f"执行查询，参数: {peccancy_params}\n")
                    cursor.execute(peccancy_query, peccancy_params)
                    peccancy_records = cursor.fetchall()
                    f.write(f"找到 {len(peccancy_records)} 条违章记录\n")
                    for record in peccancy_records:
                        f.write(f"人员: {record['peccancy_uid']}, 违章代码: {record['peccancy_code']}, 次数: {record['count']}\n")
            
            # 关闭连接
            cursor.close()
            connection.close()
            f.write("数据库连接已关闭\n")
            f.write("测试完成，无错误\n")
            
        except Exception as e:
            f.write(f"错误: {e}\n")
            raise
        
    print("测试输出已写入test_output.txt文件")

if __name__ == "__main__":
    test_db_connection()
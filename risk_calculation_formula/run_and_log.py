import subprocess
import datetime

# 生成日志文件名
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = f'run_log_{timestamp}.txt'

# 运行new_rule.py并将输出写入日志文件
print(f"开始运行new_rule.py，日志将保存到: {log_file}")

with open(log_file, 'w', encoding='utf-8') as f:
    result = subprocess.run(
        ['python', 'new_rule.py'],
        capture_output=True,
        text=True,
        cwd='d:\\hyetec\\safety\\personal_risk_prevention_algo\\risk_calculation_formula'
    )
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\nSTDERR:\n")
    f.write(result.stderr)
    f.write(f"\nReturn code: {result.returncode}")

print(f"运行完成，日志已保存到: {log_file}")
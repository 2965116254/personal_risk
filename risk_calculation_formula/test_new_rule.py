import subprocess
import sys

print("开始运行new_rule.py...")
print("输出将直接显示在控制台")

try:
    result = subprocess.run(
        [sys.executable, 'new_rule.py'],
        cwd='d:\\hyetec\\safety\\personal_risk_prevention_algo\\risk_calculation_formula',
        capture_output=False,
        text=True
    )
    print(f"脚本执行完成，返回码: {result.returncode}")
except Exception as e:
    print(f"执行出错: {e}")
import json
import openpyxl
from pathlib import Path

# 相对路径定位
excel_path = Path(__file__).parent.parent / 'log' / '采购合同查询_20260706093517407.xlsx'
cache_dir = Path(__file__).parent.parent / 'cache'
cache_dir.mkdir(parents=True, exist_ok=True)

wb = openpyxl.load_workbook(excel_path)
ws = wb.active

seen = set()
supplier_names = []
for row in ws.iter_rows(min_row=3, values_only=True):
    contract_status = row[36]  # 合同状态
    if contract_status in ('签约完成', '归档完成'):
        supplier_name = row[10]  # 供应商名称
        if supplier_name and supplier_name not in seen:
            seen.add(supplier_name)
            supplier_names.append(supplier_name)

output = {"suppliers": supplier_names}
output_path = cache_dir / 'suppliers.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"提取到 {len(supplier_names)} 个供应商")
print(f"已保存到: {output_path}")
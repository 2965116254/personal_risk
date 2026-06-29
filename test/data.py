import json
import os
import sys

def read_data_file(filename):
    """
    从指定文件读取编号列表，清洗并返回字符串列表。
    清洗规则：
      - 去除每行首尾空白
      - 跳过空行
      - 跳过单独一行的 "}"（原始数据末尾可能含有此符号）
    """
    if not os.path.isfile(filename):
        raise FileNotFoundError(f"文件 '{filename}' 不存在于当前目录: {os.getcwd()}")

    with open(filename, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    cleaned = []
    for line in raw_lines:
        line = line.strip()
        if not line:          # 空行跳过
            continue
        if line == "}":       # 单独一行的 } 跳过（原始数据尾部标记）
            continue
        cleaned.append(line)
    return cleaned

def main():
    # 将工作目录切换到脚本所在目录，保证 data.txt 和生成的 data.json 都在同一位置
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)

    input_file = "data.txt"
    output_file = "data.json"

    try:
        items = read_data_file(input_file)
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)

    # 生成 JSON 数组（美观格式化）
    json_result = json.dumps(items, ensure_ascii=False, indent=2)

    # 写入输出文件
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(json_result)

    print(f"✅ 成功生成 {output_file}，共 {len(items)} 条数据。")
    print(f"📁 文件位置: {os.path.join(script_dir, output_file)}")

if __name__ == "__main__":
    main()
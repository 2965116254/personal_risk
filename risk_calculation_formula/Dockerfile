FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（如果需要，例如时区）
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# 设置时区（可选）
ENV TZ=Asia/Shanghai

# 升级 pip
RUN pip install --upgrade pip setuptools wheel

# 复制依赖文件并安装 Python 包
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制所有 Python 脚本和数据文件
COPY *.py ./
COPY *.csv ./
COPY config.yaml ./

# 创建临时输出目录（确保权限）
RUN mkdir -p /tmp/excel_output

# 运行入口
CMD ["python", "connect.py"]
#!/usr/bin/env bash
# 启动语音修改成绩表服务并自动打开浏览器
set -e
cd "$(dirname "$0")"
exec uv run python main.py

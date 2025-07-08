# Inmono项目运行指南

## 安装与运行

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 设置API密钥
在环境变量中配置OpenAI API密钥：
```bash
export OPENAI_API_KEY="您的密钥"
```
如果使用本地部署的Ollama，使用以下命令（一次性）
```bash
setx OPENAI_API_KEY  "ollama"
setx OPENAI_API_BASE http://localhost:11434/v1
$Env:OPENAI_API_KEY  = "ollama"
$Env:OPENAI_API_BASE = "http://localhost:11434/v1"
```

### 3. 启动应用
- **开发模式**（调试推荐）：
  ```bash
  python wsgiis.py
  ```

- **生产模式**（长期运行推荐）：
  ```bash
  gunicorn --timeout 60 --bind unix:/路径/到/app.sock -m 777 -w 5 wsgiis:app --reload
  ```
  > 注意：生产模式需提前配置NGINX + Gunicorn环境

### 4. 访问应用
浏览器打开默认地址：  
[http://127.0.0.1:5000/](http://127.0.0.1:5000/)

---

## 项目结构说明

### 核心文件
- **后端主逻辑**：`app_*.py` 文件
- **参数配置**：`*_params.py` 文件
- **前端资源**：
  - 静态文件：`static/` 目录
  - 页面模板：`templates/` 目录

### 数据管理
- **用户文档存储**：
  `documents/` 目录（JSON格式）
- **系统日志**：
  `logs/` 目录（包含API调用、LLM交互等记录）

---

## 自定义配置
可通过修改 `app_params.py` 文件：
- 启用/禁用特定功能组件
- 配置LLM模型参数
- 调整编辑器行为设置

> 提示：开发过程中建议保持默认配置，待功能稳定后再进行自定义调整

运行日志： logs/ 目录（含 API/LLM 调用记录）

# Open WebUI 部署与开发指南

## 目录

1. [前置准备](#1-前置准备)
2. [Docker 部署（Ubuntu 服务器）](#2-docker-部署ubuntu-服务器)
3. [环境变量配置](#3-环境变量配置)
4. [Python 本地开发环境搭建](#4-python-本地开发环境搭建)
5. [Fork + Upstream 同步策略](#5-fork--upstream-同步策略)
6. [自定义开发 + 保留官方升级](#6-自定义开发--保留官方升级)
7. [部署到 Ubuntu 服务器](#7-部署到-ubuntu-服务器)
8. [常见问题](#常见问题)

---

## 1. 前置准备

### 1.1 检查 Windows 开发环境

在 PowerShell 中运行以下命令，确认工具已安装：

```powershell
python --version    # 需要 3.11 或 3.12
git --version
node --version
```

### 1.2 Ubuntu 服务器安装 Docker

```bash
ssh user@192.168.1.100

sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# 重新登录使 docker 组生效
```

---

## 2. Docker 部署（Ubuntu 服务器）

### 场景 A：Ollama 在同一台服务器上

```bash
docker run -d \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

### 场景 B：Ollama 在另一台服务器上

```bash
docker run -d \
  -p 3000:8080 \
  -e OLLAMA_BASE_URL=http://<Ollama服务器IP>:11434 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

### 场景 C：Ollama + Open WebUI 打包在一起

```bash
# 有 GPU
docker run -d -p 3000:8080 --gpus=all \
  -v ollama:/root/.ollama \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:ollama

# 无 GPU（CPU）
docker run -d -p 3000:8080 \
  -v ollama:/root/.ollama \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  ghcr.io/open-webui/open-webui:ollama
```

部署后访问：`http://192.168.1.100:3000`

---

## 3. 环境变量配置

### 3.1 常用环境变量

| 变量 | 说明 | 示例 |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama 服务地址 | `http://192.168.1.101:11434` |
| `OPENAI_API_BASE_URL` | OpenAI 兼容 API 地址 | `http://192.168.1.100:18789/v1` |
| `OPENAI_API_KEY` | API 密钥 | `sk-xxx` |
| `WEBUI_AUTH` | 关闭登录验证（单用户模式） | `False` |
| `WEBUI_SECRET_KEY` | 会话密钥（防登出） | `openssl rand -hex 32` 生成 |
| `DATA_DIR` | 数据存储路径 | `/app/backend/data` |
| `ENABLE_SIGNUP` | 是否允许注册 | `True` / `False` |
| `DEFAULT_MODELS` | 默认模型 | `gpt-4o` |
| `RAG_EMBEDDING_ENGINE` | RAG 嵌入引擎 | `ollama` / `openai` |
| `RAG_EMBEDDING_MODEL` | RAG 嵌入模型 | `nomic-embed-text-v1.5` |
| `CORS_ALLOW_ORIGIN` | CORS 白名单 | `*`（生产环境应限制） |

### 3.2 docker-compose.yml 配置方式

在 Ubuntu 服务器上创建 `/opt/open-webui/docker-compose.yml`：

```yaml
services:
  openwebui:
    image: ghcr.io/open-webui/open-webui:main
    ports:
      - "3000:8080"
    volumes:
      - open-webui:/app/backend/data
    environment:
      - OPENAI_API_BASE_URL=http://192.168.1.100:18789/v1
      - OPENAI_API_KEY=d335a038fcc0306c0b161892043dc1b6981f36ca82a01a62
      - WEBUI_SECRET_KEY=你的会话密钥
      - ENABLE_SIGNUP=True
      - DEFAULT_MODELS=gpt-4o
    restart: always

volumes:
  open-webui:
```

启动：
```bash
cd /opt/open-webui
docker compose up -d
```

### 3.3 本地开发 .env 文件配置

在项目根目录创建 `.env` 文件：

```env
# ============ API 配置 ============
OPENAI_API_BASE_URL=http://192.168.1.100:18789/v1
OPENAI_API_KEY=d335a038fcc0306c0b161892043dc1b6981f36ca82a01a62

# ============ 基础配置 ============
WEBUI_NAME=我的AI助手
WEBUI_URL=http://192.168.1.100:3000
WEBUI_SECRET_KEY=2090a273257d91e2a8453930e7f44d058513fc401be789b32fe13af78fd6e065
DATA_DIR=./data
DEFAULT_LOCALE=zh-CN

# ============ 用户管理 ============
ENABLE_SIGNUP=True
DEFAULT_USER_ROLE=user

# ============ 功能开关 ============
ENABLE_CHANNELS=True
ENABLE_NOTES=True
ENABLE_MEMORIES=True
ENABLE_CALENDAR=True
ENABLE_AUTOMATIONS=True
CORS_ALLOW_ORIGIN=*
```

完整环境变量参考：https://docs.openwebui.com/reference/env-configuration/

---

## 4. Python 本地开发环境搭建

### 4.1 克隆仓库

```powershell
cd ~/Desktop   # 或你想放代码的目录

git clone https://github.com/Ning-JY/open-webui.git
cd open-webui

# 添加官方仓库为上游
git remote add upstream https://github.com/open-webui/open-webui.git
```

验证 remote 配置：
```powershell
git remote -v
```

### 4.2 创建虚拟环境

```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 4.3 安装依赖

> **注意：** 项目没有 `requirements.txt`，依赖定义在 `pyproject.toml` 中。

```powershell
pip install -e .
```

`-e` 表示可编辑模式，修改代码后无需重新安装。

### 4.4 配置环境变量

复制示例文件并编辑：
```powershell
copy .env.example .env
notepad .env
```

填入你的 API 地址和密钥。

### 4.5 构建前端（必须步骤）

克隆的源码没有前端构建产物，必须手动构建，否则访问会报 404。

```powershell
# 安装前端依赖
npm install

# 构建前端（耗时约1-2分钟）
npm run build

# 把构建产物复制到后端能识别的位置
# Windows PowerShell:
Copy-Item -Recurse -Force build backend\open_webui\frontend

# macOS/Linux:
cp -r build backend/open_webui/frontend
```

### 4.6 启动开发服务器

```powershell
open-webui serve
```

访问：`http://localhost:8080`

> **端口被占用？** 如果提示 `8080` 端口被占用，换一个端口：
> ```powershell
> open-webui serve --port 8081
> ```
> 然后访问 `http://localhost:8081`

### 4.7 项目目录结构

```
open-webui/
├── backend/          # 后端 Python 代码
│   ├── main.py       # 后端入口
│   └── open_webui/   # 核心业务逻辑
├── src/              # 前端 Svelte 代码
├── .env              # 环境变量（需自己创建）
├── pyproject.toml    # Python 依赖定义
└── package.json      # 前端依赖
```

---

## 5. Fork + Upstream 同步策略

### 5.1 工作原理

```
官方仓库 (upstream)  ──fetch──>  你的 Fork (origin)  ──clone──>  本地电脑
       ↑                              ↑
       └──────── merge/rebase ────────┘
```

### 5.2 同步官方更新

```powershell
# 拉取官方最新代码
git fetch upstream

# 合并到你的 main 分支
git checkout main
git merge upstream/main

# 如果有冲突，解决后
git add .
git commit -m "merge upstream"
```

---

## 6. 自定义开发 + 保留官方升级

### 6.1 开发流程

1. **所有自定义改动都在你 Fork 的分支上进行**
2. **不要直接修改官方代码**
3. **定期同步官方更新**

### 6.2 推荐的分支策略

```powershell
# 从 main 创建开发分支
git checkout -b feature/我的自定义功能

# 开发完成后合并回 main
git checkout main
git merge feature/我的自定义功能
```

### 6.3 构建自定义 Docker 镜像

```powershell
# 构建
docker build -t my-open-webui:latest .

# 运行
docker run -d -p 3000:8080 \
  -v open-webui:/app/backend/data \
  --name open-webui \
  --restart always \
  my-open-webui:latest
```

### 6.4 自动化升级脚本

创建 `update.sh`：

```bash
#!/bin/bash
cd /opt/open-webui

# 拉取官方最新
git fetch upstream
git merge upstream/main --no-edit

# 重新构建
docker compose build

# 重启服务（数据不丢）
docker compose up -d

echo "升级完成！"
```

每次官方发布新版本，运行 `bash update.sh` 即可。

---

## 7. 部署到 Ubuntu 服务器

### 7.1 推送代码到 GitHub

```powershell
git add .
git commit -m "你的改动说明"
git push origin main
```

### 7.2 在 Ubuntu 服务器上拉取并部署

```bash
ssh user@192.168.1.100

cd /opt
git clone https://github.com/Ning-JY/open-webui.git
cd open-webui

# 创建 .env 文件（配置环境变量）
cp .env.example .env
nano .env   # 填入你的 API 地址和密钥

# 启动
docker compose up -d
```

### 7.3 更新部署

```bash
cd /opt/open-webui
git pull origin main
docker compose up -d --build
```

---



### 7.4 更新官方版本（保留自定义修改）

当官方发布新版本时，按以下步骤更新：

```powershell
# 1. 提交你的自定义修改（如果还没提交）
git add backend/open_webui/main.py src/lib/components/layout/Sidebar.svelte
git commit -m "添加 drive 文件管理功能"

# 2. 丢弃无关的本地修改
git checkout -- static/pyodide/pyodide-lock.json

# 3. 拉取官方最新代码
git fetch upstream

# 4. 合并到你的 main 分支
git checkout main
git merge upstream/main
```

#### 冲突处理

如果合并时出现冲突，常见冲突文件及处理方式：

| 文件 | 处理方式 |
|------|----------|
| `backend/open_webui/main.py` | 手动合并，保留你加的 `drive` import 和路由 |
| `Sidebar.svelte` | 手动合并，保留你加的 drive 菜单项 |
| `pyproject.toml` | 接受官方版本（依赖更新） |
| 其他文件 | 直接接受官方版本 |

解决冲突后提交：

```powershell
git add .
git commit -m "合并 upstream/main，保留自定义功能"
```

#### 合并后更新依赖和构建

```powershell
# 安装更新的 Python 依赖
pip install -e .

# 安装前端依赖
npm install

# 重新构建前端
npm run build

# 复制构建产物
Copy-Item -Recurse -Force build backend\open_webui\frontend

# 重启服务
open-webui serve --port 8081
```

### 7.5 Token 用量统计配置

Open WebUI 支持统计每个账号的 token 用量，包括 OpenAI 兼容 API（如 OpenClaw）。

#### 开启步骤

1. 进入 **Admin Panel → Workspace → Models**
2. 编辑你使用的模型（如 `openclaw`）
3. 在 **Capabilities** 中勾选 **Usage**
4. 保存

开启后，每条消息右下角会显示 token 消耗量。

#### 前提条件

你的 API 需要在响应中返回 `usage` 字段。可以通过以下命令验证：

```bash
curl http://192.168.1.100:18789/v1/chat/completions \
  -H "Authorization: Bearer d335a038fcc0306c0b161892043dc1b6981f36ca82a01a62" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw","messages":[{"role":"user","content":"hello"}],"stream":false}'
```

如果响应中包含 `usage` 字段（如 `prompt_tokens`、`completion_tokens`），则支持统计。

#### 管理员查看全局用量

进入 **Admin Panel → Analytics**，可以查看所有用户的 token 使用统计。

### 7.6 模型访问控制（可选）

如果需要限制用户只能使用管理员配置的模型：

#### 方法 1：通过 Admin Panel 设置

1. 进入 **Admin Panel → Workspace → Models**
2. 编辑 `openclaw` 模型
3. 找到 **Access Control** 或 **Visibility** 选项
4. 设置为只有管理员可见或指定用户/组
5. 保存

#### 方法 2：通过环境变量限制

在 `.env` 文件中添加：

```env
# 禁止用户绕过模型访问控制
BYPASS_MODEL_ACCESS_CONTROL=False
```

这样只有管理员明确授权的模型才会显示在聊天界面的模型选择器中。

#### 说明

- **Connections**（Admin Panel → Settings → Connections）= 配置 API 连接
- **Workspace → Models** = 自定义模型配置（可选，不创建也能用）
- **聊天界面模型选择器** = 实际选择模型的地方

### 7.7 登录方式自定义（可选）

默认情况下，Open WebUI 使用邮箱登录。如果想让用户输入用户名即可登录（系统自动补全邮箱后缀），需要修改前端代码。

#### 修改内容

文件：`src/routes/auth/+page.svelte`

在 `signInHandler` 和 `signUpHandler` 函数中，自动为没有 `@` 的输入添加 `@local.com` 后缀：

```javascript
// 登录时
const loginEmail = email.includes('@') ? email : `${email}@local.com`;

// 注册时
const signupEmail = email.includes('@') ? email : `${email}@local.com`;
```

#### 使用方式

- 用户输入 `zhangsan` → 系统转为 `zhangsan@local.com`
- 用户输入 `test@gmail.com` → 保持原样 `test@gmail.com`

#### 注意事项

- 此修改仅影响前端，后端无需改动
- 合并官方更新时可能需要手动解决冲突
- 建议在独立分支上进行此修改

### 7.8 用户用量面板（自定义功能）

为普通用户提供独立的 Token 用量统计页面。

#### 功能说明

- 显示总聊天数、输入/输出/总 Token 数
- 按聊天显示详细用量
- 支持刷新数据

#### 文件修改

1. 新建页面：`src/routes/(app)/usage/+page.svelte`
2. 修改侧边栏：`src/lib/components/layout/Sidebar.svelte`
   - 添加 usage 菜单项
   - 添加用量图标
   - 加入默认固定菜单

#### 访问路径

登录后，侧边栏点击 **用量统计** 菜单即可访问。

### 7.9 登录页面汉化（自定义功能）

将登录页面的 "Email" 标签改为 "用户名"，配合自动邮箱后缀功能使用。

#### 文件修改

文件：`src/routes/auth/+page.svelte`

修改内容：
- 标签：`Email` → `用户名`
- 输入框类型：`email` → `text`
- 占位符：`Enter Your Email` → `请输入用户名`

#### 注意事项

此修改仅影响前端显示，后端登录逻辑不变（仍使用邮箱格式）。

## 常见问题

### Q: 启动后页面显示 404 或 "not found"？

原因：前端没有构建。执行 4.5 节的构建步骤：

```powershell
npm install
npm run build
Copy-Item -Recurse -Force build backend\open_webui\frontend
```

然后重启服务。

### Q: pip install -e . 报错怎么办？

通常是缺 Visual Studio Build Tools。下载安装：
https://visualstudio.microsoft.com/visual-cpp-build-tools/

安装时选择 "Desktop development with C++"。

### Q: 启动后访问不了？

检查端口是否被占用：
```powershell
netstat -ano | findstr :8080
```

### Q: 环境变量修改后不生效？

重启服务：
```powershell
# 本地开发
Ctrl+C 停止，重新运行 open-webui serve

# Docker 部署
docker compose restart
```

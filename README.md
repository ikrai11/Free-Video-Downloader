# Vault — 全平台视频下载器

基于 yt-dlp 引擎的 Web 视频下载工具，支持 YouTube、Bilibili、抖音、TikTok 等 **1000+ 平台**。

## 技术栈

| 层 | 技术 | 说明 |
|---|------|------|
| Web 框架 | Flask 3.x | 轻量级，单文件即可运行 |
| 通用下载 | yt-dlp (2025.10.14) | 覆盖 1000+ 站点，自动合并音视频 |
| 抖音解析 | 自研（基于页面 JSON 解析） | 无需 Cookie，无需外部签名服务 |
| 前端 | 原生 HTML + CSS + JS | 零构建工具，暗色高级主题 |
| 进度推送 | SSE (Server-Sent Events) | 浏览器原生支持，实时进度条 |

## 快速开始

```bash
# 安装依赖
pip install flask yt-dlp openai

# 设置 DeepSeek API Key（用于 AI 视频总结）
# 获取地址：https://platform.deepseek.com
set DEEPSEEK_API_KEY=你的key        # Windows
export DEEPSEEK_API_KEY=你的key     # Mac/Linux

# 启动服务
python app.py

# 浏览器打开
# http://localhost:5000
```

## 项目结构

```
├── app.py                  # Flask 主入口（路由、SSE、任务管理、限流）
├── downloader/
│   ├── engine.py           # 下载引擎（yt-dlp 封装 + 抖音专用解析器）
│   ├── summarizer.py       # AI 总结（字幕提取 + DeepSeek 流式生成）
│   └── utils.py            # URL 校验、文件名清理、过期清理
├── templates/
│   └── index.html          # 单页前端（中文界面）
├── static/
│   ├── css/style.css       # 暗色高级主题 + 玻璃拟态
│   └── js/app.js           # 前端交互逻辑
├── downloads/              # 临时下载目录（用完自动清理）
└── requirements.txt
```

## API 设计

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/extract` | POST | 解析视频信息（标题、封面、画质列表） |
| `/api/download` | POST | 开始下载，返回任务 ID |
| `/api/progress/<id>` | GET | SSE 实时进度流 |
| `/api/file/<id>/<name>` | GET | 下载完成的文件（即用即删） |
| `/api/thumbnail` | GET | 封面图代理（绕过浏览器加载限制） |
| `/api/summarize` | POST | AI 视频总结（SSE 流式输出） |

## 功能特性

- **多平台支持**：YouTube、Bilibili、抖音、TikTok、Twitter 等
- **画质选择**：自动列出所有可用分辨率，支持单独下载音频
- **AI 视频总结**：一键提取字幕 → DeepSeek 生成大纲、知识点、摘要
- **实时进度**：下载/总结过程中实时显示进度和状态
- **流式输出**：AI 总结逐字渲染，体验流畅
- **无需数据库**：内存管理任务状态，文件即用即删
- **安全防护**：URL 校验、路径遍历防护、简易限流
- **暗色主题**：玻璃拟态卡片 + 渐变设计，中文界面

## AI 视频总结

### 工作流程
```
粘贴链接 → 提取字幕(yt-dlp) → DeepSeek API → SSE流式输出
```

### 输出内容
- **视频大纲**：章节结构树形列表
- **核心知识点**：3-5 个要点，每个 2-3 句话解释
- **一句话总结**：概括整个视频

### 使用前提
1. 注册 DeepSeek 账号：https://platform.deepseek.com
2. 获取 API Key（新用户有免费额度）
3. 设置环境变量 `DEEPSEEK_API_KEY`
4. 视频需要有字幕（B站/YouTube 自动字幕即可）

### 成本
DeepSeek V3 价格仅 ¥1/百万 token，一次视频总结约 **¥0.01-0.02**。

## 抖音特殊处理

抖音的反爬策略较严格，本项目的解决方案：

1. **短链解析**：`v.douyin.com/xxx` → 跟踪重定向获取视频 ID
2. **页面解析**：请求 `iesdouyin.com/share/video/{id}`，提取 `_ROUTER_DATA` JSON
3. **去水印**：下载地址中 `playwm` 替换为 `play`
4. **直接下载**：解析后的无水印链接直接走 urllib 下载

支持的抖音链接格式：
- 短链：`https://v.douyin.com/xxxxx/`
- 视频页：`https://www.douyin.com/video/7614000636661794761`
- 弹窗页：`https://www.douyin.com/user/self?modal_id=7614000636661794761`

## 注意事项

- 请遵守各平台服务条款，仅用于个人合法用途
- yt-dlp 下载 YouTube 等境外平台可能需要代理
- 抖音页面结构可能变更，如解析失败请更新解析规则

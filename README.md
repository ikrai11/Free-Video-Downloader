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
pip install flask yt-dlp

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

## 功能特性

- **多平台支持**：YouTube、Bilibili、抖音、TikTok、Twitter 等
- **画质选择**：自动列出所有可用分辨率，支持单独下载音频
- **实时进度**：下载过程中显示百分比、速度、剩余时间
- **无需数据库**：内存管理任务状态，文件即用即删
- **安全防护**：URL 校验、路径遍历防护、简易限流
- **暗色主题**：玻璃拟态卡片 + 渐变设计，中文界面

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

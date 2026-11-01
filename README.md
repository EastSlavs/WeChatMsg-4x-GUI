# WeChatMsg-4x-GUI

Windows 微信 PC 4.x 聊天记录导出工具，支持图片解密、日期筛选和批量导出。

基于 [WeChatMsg-4x](https://github.com/chenanhan230-del/WeChatMsg-4x) 修改。

## 本项目的改进

沿用原项目的微信 4.x 数据库解密和消息读取功能，主要增加以下功能：

| 改进 | 说明 |
| --- | --- |
| V2 图片解密 | 完善 V2 图片解密，支持自动获取密钥并导出图片 |
| Tkinter 界面 | 集中设置账号、联系人、日期、导出内容和保存目录 |
| 多账号管理 | 识别当前登录账号，按账号独立保存解密数据库 |
| 数据库更新与备份 | 导出前更新数据库，校验后替换，并保留旧版本备份 |
| 联系人搜索与多选 | 搜索联系人和群聊，支持勾选多个会话 |
| 日期筛选 | 在界面和导出命令中增加开始日期、结束日期设置 |
| 导出模式 | 可选择完整记录、文字图片、语音或媒体文件 |
| 语音批量处理 | 批量转换为 MP3，生成 ZIP 压缩包 |
| 文件匹配 | 根据文件名、大小等信息匹配本地附件 |
| 批量导出索引 | 改进多会话导出索引，增加结果统计 |
| 任务管理 | 增加运行日志、取消入口和导出后联系人刷新 |

## 导出内容

- 文字聊天记录
- 图片，支持 V2 格式解密
- 语音，支持 MP3 和 ZIP
- 文件附件
- HTML 聊天页面及会话索引

媒体文件需要保存在本机，解码效果与微信版本有关。

## 运行环境

- Windows
- 微信 PC 4.x
- Python 3.11
- FFmpeg：部分媒体转换需要，安装后加入 PATH

## 安装与启动

在 PowerShell 中执行：

```powershell
git clone https://github.com/EastSlavs/WeChatMsg-4x-GUI.git
cd WeChatMsg-4x-GUI

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe wx4_gui.py
```

当前界面入口为 `wx4_gui.py`。

## 使用步骤

1. 登录微信 PC 客户端。
2. 启动工具，选择账号。
3. 搜索并选择联系人或群聊。
4. 设置日期范围、导出内容和保存目录。
5. 开始导出，查看日志和结果。

首次使用需初始化账号数据库，相关界面流程仍待完善。微信版本兼容性以实际测试为准。

## 主要代码

| 文件 | 作用 |
| --- | --- |
| `wx4_gui.py` | Tkinter 图形界面 |
| `wx4/image_key.py` | 图片密钥获取 |
| `wx4/media.py` | 图片解密及媒体处理 |
| `wx4/account_update.py` | 账号数据库更新与备份 |
| `wx4/gui_batch.py` | 多会话导出与索引 |
| `wx4/voice_batch.py` | 语音批量处理 |
| `wx4/cli.py` | 命令行入口 |
| `wx4/export.py` | 聊天记录导出 |
| `wx4/reader.py` | 联系人与消息读取 |

## 数据安全

请仅处理本人或获得授权的数据，妥善保管数据库、密钥和导出文件。

提交代码前，请检查聊天记录、个人信息和密钥是否被误加到仓库。导出的 HTML 可能加载远程头像。

## 来源与许可证

- 基础项目：[chenanhan230-del/WeChatMsg-4x](https://github.com/chenanhan230-del/WeChatMsg-4x)
- 项目许可证：[GPL-3.0](LICENSE)
- 本项目修改说明：[doc/修改声明.md](doc/修改声明.md)
- 上游原始声明：[LICENSES/WeChatMsg-4x-NOTICE.md](LICENSES/WeChatMsg-4x-NOTICE.md)
- 保留的 MIT 版权声明：[LICENSES/MIT.txt](LICENSES/MIT.txt)

保留上游和第三方代码的版权及许可声明。

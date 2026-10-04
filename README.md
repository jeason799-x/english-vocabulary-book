# 拾词 · English Vocabulary Book

一款 Windows 英语学习桌面应用，把生词、固定搭配、例句和作文积累放在一起。
使用 Python、Tkinter 与 Pillow 开发，学习记录保存在本机，支持打包为独立 EXE。

**直接使用：** 前往 [下载页面](https://github.com/jeason799-x/english-vocabulary-book/releases/latest)，
下载 `EnglishVocabularyBook.exe`，在 Windows 64 位系统上双击运行，无需安装 Python。

## 功能

- **生词与搭配**：手动添加、搜索、类型筛选和详情查看，保存音标、释义及双语例句。
- **批量导入**：粘贴词表，或导入 TXT、CSV、TSV；预览、去重后统一保存。
- **学习与复习**：区分新词和到期复习，按作答表现调整复习间隔，支持拼写与未完成练习续练。
- **语音朗读**：通过 Windows 系统语音朗读单词和例句，切换题目时取消上一组朗读。
- **作文积累**：保存原文、翻译、写作思路、搭配和句型，可将搭配加入生词本。
- **透明渐变 UI**：统一的背景与轻薄渐变卡片、三套主题、240 ms 页面转场和 160 ms 选项过渡。

## 从源码运行

环境：Windows 10 / 11、Python 3.12 或更新版本，安装 Python 时包含 Tcl/Tk。

在 PowerShell 中运行：

```powershell
git clone https://github.com/jeason799-x/english-vocabulary-book.git
cd english-vocabulary-book
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe desktop_app.pyw
```

仅预览界面时可使用示例词库，关闭后自动删除，不会读取个人学习记录：

```powershell
.\.venv\Scripts\python.exe scripts\check-ui-redesign.py --preview
```

## 打包 Windows 程序

```powershell
.\build-desktop.ps1
```

脚本会创建或复用 `.venv`，安装打包依赖，然后生成
`desktop-dist\EnglishVocabularyBook.exe`。也可以显式指定 Python 或输出目录：

```powershell
.\build-desktop.ps1 -Python 'C:\Python312\python.exe' -OutputPath '.\desktop-dist'
```

生成的 EXE 可以独立运行。窗口程序使用系统语音；可用声音取决于 Windows 安装的语音包。

## 使用

1. 在“生词本”添加词条，或使用左侧“批量导入”。词表格式见 [批量导入示例.csv](批量导入示例.csv)。
2. 在“今日”开始新词学习或到期复习，未完成的练习可以稍后继续。
3. 在“设置”调整每组词数、拼写策略、主题和透明渐变。
4. 在“作文”保存资料，将常用搭配加入生词本。

生词本快捷键：`Ctrl+F` 搜索、`Esc` 清空搜索、选中词条后 `Enter` 查看详情。
设置中的分组选项支持左右方向键切换。

## 数据与联网行为

词库、学习进度、作文与设置保存在：

```text
%LOCALAPPDATA%\EnglishVocabularyBook\vocabulary.json
```

源代码仓库不包含个人数据、备份、打包产物或本机环境配置。
首次运行会创建少量内置示例单词；已有数据沿用原来的存储位置。
启动时会修复缺失例句，修复已有数据前会在同目录保存备份。

手动添加和离线练习可在本机进行；自动查询释义、翻译与例句会向
有道词典、Dictionary API 或 MyMemory 发送所查询的词语或句子。无需在代码中填写 API 密钥。

## 开发与验证

```powershell
# 数据、复习、导入、作文与语音请求逻辑
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# 实际窗口、三套主题、不同尺寸与快捷键
.\.venv\Scripts\python.exe scripts\check-ui-redesign.py
.\.venv\Scripts\python.exe scripts\check-interface.py

# 导航性能
.\.venv\Scripts\python.exe scripts\check-ui-performance.py
```

界面检查使用临时数据，需要可显示 Tk 窗口的 Windows 会话。
`scripts/complete-existing-examples.py` 是旧词库维护工具，直接运行会备份并修改本机词库；
普通运行和测试无需执行它。

| 文件 | 职责 |
| --- | --- |
| `desktop_app.pyw` | 程序入口、数据存储、词典查询与系统语音 |
| `desktop_interface.py` | 主窗口、学习、生词本、统计与设置 |
| `ui_components.py` | 渐变绘制、字体、卡片、按钮与动画 |
| `review_engine.py` | 练习流程与复习计划 |
| `bulk_import.py` / `import_dialog.py` | 词表解析与导入界面 |
| `essay_library.py` / `essay_interface.py` | 作文解析、表达提取与阅读编辑 |
| `example_bank.py` / `vocabulary_items.py` | 例句补全与词条规范化 |

## 字体与第三方服务

内置寒蝉全圆体由 ChillType / Warren2060 提供，字体文件未修改，按 SIL Open Font License 1.1 分发。
完整声明见 [字体来源](assets/fonts/字体来源.md) 和 [OFL-ChillRound.txt](assets/fonts/OFL-ChillRound.txt)。
字体只在程序进程内加载；界面优先使用系统可用的思源黑体、微软雅黑 UI 与 Segoe UI。
词典与翻译接口由各自服务提供方运营，本项目与这些服务没有官方关联。

版本变化见 [CHANGELOG.md](CHANGELOG.md)。

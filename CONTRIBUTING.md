# 贡献指南

感谢你愿意为「局域网办公文件传输系统」出一份力。本项目坚持 **Python 标准库、零第三方依赖**，目标是让办公室里任何一台 Windows 电脑都能直接跑起来，因此贡献时请一并守住这个原则。

## 一、你可以怎样参与

- **报告缺陷**：程序异常、界面错乱、文件保存结果不符合预期。
- **提出建议**：新的使用场景、界面改进、协议或兼容性建议。
- **改进文档**：README、设计说明、使用说明中的错漏与翻译。
- **提交代码**：修复问题、补充测试、优化传输与排队逻辑。

不确定算不算贡献？直接开一个 Issue 聊聊就好。

## 二、报告问题之前

请在 Issue 里尽量包含以下信息，能大幅缩短定位时间：

| 项目 | 示例 |
| --- | --- |
| 运行方式 | Release 下载的 exe / 源码 `python main.py` |
| 环境 | Windows 版本、Python 版本、是否同一局域网 |
| 复现步骤 | 第 1 步做什么、第 2 步点哪里、看到什么 |
| 期望与实际 | 期望不覆盖原文件，实际被覆盖 |
| 截图或日志 | 界面截图、错误提示文字（**请勿粘贴含姓名、工号、IP 的配置内容**） |

提交前先搜一下已有 Issue，避免重复。缺陷请用「问题反馈」模板，新想法请用「功能建议」模板。

## 三、搭建开发环境

本项目**不需要 `pip install` 任何运行依赖**（tkinter + socket 均为标准库）。

```bash
git clone https://github.com/pengtk2026/office-lan-transfer.git
cd office-lan-transfer
python main.py
```

- 推荐 Python **3.10 及以上**（项目在 3.13 下测试通过）。
- 若自行编译 exe，才需要 `pyinstaller`（以及生成图标时可选的 `pillow`），详见 README 第六节。

**改动前后请跑完四个集成测试**：

```bash
python tests/test_integration.py
python tests/test_dir_submit.py
python tests/test_push_dir.py
python tests/test_queue.py
```

四个测试均无需图形界面，输出 `[OK]` / `TEST OK` 即通过；它们也会在 GitHub Actions 中于 Windows 环境自动运行。

## 四、提交改动

1. 从 `main` 建一个语义清晰的分支：`git switch -c fix/queue-timeout`。
2. **小步提交**，提交信息用约定前缀：`feat:` 新功能、`fix:` 修复、`docs:` 文档、`test:` 测试、`refactor:` 重构。
3. Pull Request 里写清三件事：**改了什么、为什么改、怎么验证**，并关联对应 Issue。
4. 涉及通信协议、文件命名或目录结构的改动，请同步更新 `design.md` 与相应测试。

**以下内容不要提交**（`.gitignore` 已排除大部分，但仍请复核）：

- `build/`、`dist/` 与任何 `.exe` 二进制文件（安装包走 Release 附件）；
- `*.ini` 等含 IP、姓名、工号的本机配置；
- `receiver_data/`、`sender_data/` 等运行数据、`__pycache__/`、日志文件。

## 五、代码约定

- 保持**零第三方运行依赖**；确需引入请先开 Issue 讨论。
- 界面文案与帮助信息使用简体中文，术语统一为「接收端 / 接收者」「发送端 / 发送者」。
- 新增功能请补一个无界面的集成测试，尽量复用 `tests/` 中已有的回环服务写法。
- 不要破坏「同名不覆盖」「按日期分目录」「文件夹原样保存」这三条既有行为。

## 六、行为准则

所有参与者请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。维护者会尽快但不一定即时回复，感谢耐心。

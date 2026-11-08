# 局域网办公文件传输系统（Python + tkinter）

## 一、项目简介

本项目用于在**同一局域网内**实现文件的**下发**与**提交**。它把「文件接收端」与「文件发送端」合并为**一个程序**，打开后通过 **两个 Tab** 切换，全部使用 Python 标准库（tkinter + socket），**无需安装任何第三方依赖**即可运行。

> 术语说明：本系统面向企业办公场景，统一使用「**接收端 / 接收者**」与「**发送端 / 发送者**」两套表述，不涉及学校、教师、学生等场景。

## 二、主要功能

| 端 | 功能 |
| --- | --- |
| 文件接收端 | 启动 / 停止网络服务、查看在线发送者、下发文件/文件夹、查看提交记录、定制接收目录 |
| 文件发送端 | 填写接收端 IP 后连接（无需注册账号）、接收下发文件/文件夹、提交单个文件或整个文件夹 |

额外特性：

- **双 Tab 合并**：一个程序、两个标签页，接收端与发送端无需分别启动。
- **中文界面**：全部界面、提示、帮助均为中文。
- **程序图标与版本信息**：内置图标（文件双向传输），右键 exe → 属性 → 详细信息可查看产品名、版本、开发者 prh。
- **帮助按钮**：内置中文使用说明。
- **ini 记忆**：记住最近一次填写的 IP、端口、姓名、工号、目录等信息，下次启动自动带出。
- **IP 规则校验**：接收端 IP 填写时校验格式，非 IP 样式会提示。
- **同名不覆盖**：同一天重复发送 / 提交同一文件时，自动追加版本号 `_v2`、`_v3`，绝不覆盖原文件。
- **按日期分目录**：收到的文件按「当天日期」自动建立目录，不同日期的文件互不重叠。
- **队列排队**：多个发送者同时提交时自动排队，显示排第几位，两端实时看到排队变化。
- **文件夹提交**：发送端可提交整个文件夹（含其下所有子文件夹），原样保存目录结构。
- **文件夹下发**：接收端可下发整个文件夹（含其下所有子文件夹），发送端原样接收保存目录结构。

## 三、目录结构

```
office_lan_transfer/
├── main.py                      # 主程序（单窗口双 Tab）
├── common/
│   ├── __init__.py              # 公共模块
│   ├── app_style.py             # 界面风格与图标
│   ├── config.py                # ini 记忆配置
│   ├── fileutil.py              # 日期目录 + 版本号命名
│   ├── help_dialog.py           # 帮助 / 关于对话框
│   └── protocol.py              # 网络通信协议
├── receiver/                    # 文件接收端
│   ├── __init__.py
│   ├── receiver_app.py          # 接收端图形界面
│   └── server_core.py           # 接收端服务端（含排队调度）
├── sender/                      # 文件发送端
│   ├── __init__.py
│   ├── sender_app.py            # 发送端图形界面
│   └── client_core.py           # 发送端客户端（含排队）
├── tools/
│   ├── gen_icons.py             # 生成程序图标
│   └── gen_version.py           # 生成版本资源文件
├── tests/
│   ├── test_integration.py      # 端到端集成测试
│   ├── test_queue.py            # 排队机制测试
│   ├── test_dir_submit.py       # 文件夹上传测试
│   └── test_push_dir.py         # 文件夹下发测试
├── build_assets/                # 图标与版本资源
│   ├── combined.ico
│   └── version_main.txt
├── dist/
│   └── 局域网办公文件传输系统.exe  # 编译产物
└── README.md
```

## 四、快速开始

### 方式一：直接运行编译好的 exe

1. 进入 `dist\` 目录，双击 `局域网办公文件传输系统.exe`。
2. 在「文件接收端」Tab 点击「启动服务」；把窗口顶部显示的 IP 告诉发送者。
3. 发送者在「文件发送端」Tab 填写该 IP、姓名、工号，点击「连接」即可收发文件。

### 方式二：从源码运行

```bash
python main.py
```

## 五、文件保存位置

- 接收端收到的文件：`接收端exe所在目录\receiver_data\received\当天日期\发送者姓名\文件名`
- 发送端收到的文件：`发送端exe所在目录\sender_data\received\当天日期\文件名`
- 发送者提交文件夹时：`当天日期\发送者姓名\文件夹名\`（内部子目录一并保留）
- 接收者下发文件夹时：`当天日期\文件夹名\`（发送端内部子目录一并保留）

> 数据保存在程序所在目录下，不会因程序更新而丢失。可删除 `receiver_data` / `sender_data` 来清空历史文件。

## 六、在另一台电脑上编译（详细操作指导）

前提：目标电脑已安装 Python 3.10 及以上版本（本项目在 Python 3.13 下测试通过）。

1. **获取项目源码**：把本项目整个 `office_lan_transfer` 文件夹复制到目标电脑。

2. **安装 PyInstaller（仅需一次）**：

   ```bash
   python -m pip install pyinstaller
   ```

3. **进入项目根目录**（含 `main.py` 的目录）。

4. **生成图标与版本资源**（脚本会自动创建 `build_assets\` 并生成 `combined.ico`、`version_main.txt`）：

   ```bash
   python tools\gen_icons.py
   python tools\gen_version.py
   ```

   > 生成图标需要 Pillow 库：`python -m pip install pillow`。若不需要图标可跳过此步。

5. **用 PyInstaller 编译**：

   ```bash
   python -m PyInstaller --noconfirm --onefile --windowed ^
     --name 局域网办公文件传输系统 ^
     --icon build_assets\combined.ico ^
     --version-file build_assets\version_main.txt ^
     --add-data "build_assets\combined.ico;." ^
     main.py
   ```

   - `--onefile`：打包成单个独立 exe；
   - `--windowed`：不显示黑色控制台窗口；
   - `--icon` / `--version-file`：写入图标与版本信息（产品名、版本、开发者）；
   - `--add-data`：把图标打进 exe，保证窗口图标正常显示；
   - `--name`：生成的可执行文件名。

6. **得到产物**：编译完成后，exe 位于 `dist\局域网办公文件传输系统.exe`，可拷贝到任意 Windows 电脑直接双击运行，无需安装 Python。

> 常见问题：杀毒软件可能对 PyInstaller 产物误报，添加信任即可；`build\` 与 `*.spec` 为中间文件，可删除。

## 七、运行测试

```bash
python tests\test_integration.py   # 端到端：下发/提交/版本号
python tests\test_dir_submit.py    # 文件夹上传（含子目录）
python tests\test_push_dir.py      # 文件夹下发（含子目录）
python tests\test_queue.py         # 并发提交排队
```

四个测试均无需图形界面，输出 `[OK]` 与 `TEST OK` 即通过。

## 八、开发者信息

- 软件名称：局域网办公文件传输系统
- 版本：v2.1.0.0
- 开发者：prh
- 版权：Copyright (C) 2026 prh
- 技术栈：Python · tkinter · TCP Socket（标准库）

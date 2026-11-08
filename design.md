# 局域网办公文件传输系统 详细设计说明书

- 软件名称：局域网办公文件传输系统
- 版本：v2.1.0.0
- 开发者：prh
- 文档类型：软件工程详细设计说明书（DDD）
- 更新日期：2026-10-27

---

## 1. 引言

### 1.1 编写目的

本文档描述局域网办公文件传输系统的详细设计，包括总体架构、模块划分、通信协议、数据存储、关键流程、函数设计、线程模型、界面设计与测试设计。目的在于：为维护、二次开发与教学讲解提供完整、可追溯的技术依据，使读者能据此理解本系统的设计与实现，并能在其基础上扩展功能。

本文档面向：本项目维护者、二次开发者、软件工程学习人员。

### 1.2 项目背景

在企业办公环境中，同一局域网内的多台电脑经常需要批量下发文件（如办公通知、项目资料）并回收员工提交的文件。传统方式依赖 U 盘拷贝或公共网盘，存在版本混乱、目录杂乱、重复覆盖等问题。

本系统针对上述痛点，在**同一局域网**内实现文件的下发与提交：

- 接收端：启动服务、查看在线发送者、下发文件或文件夹、查看提交记录、定制接收目录。
- 发送端：填写接收端 IP 后连接（无需注册账号）、接收下发文件或文件夹、提交单个文件或整个文件夹。
- 接收端与发送端合并为**一个程序、两个 Tab**，降低使用门槛。

### 1.3 术语定义

| 术语 | 含义 |
| --- | --- |
| 接收端 / 接收者 | 提供文件接收服务的角色，对应程序中的「文件接收端」Tab |
| 发送端 / 发送者 | 提交文件或接收下发的角色，对应程序中的「文件发送端」Tab |
| 工号 | 发送者用于标识身份的员工编号（替代传统学号概念） |
| 文件名称 | 下发或提交时给文件起的展示名称 |
| 队列 | 多个发送者同时提交时的集中调度序列 |

### 1.4 参考资料

- Python 3.13 官方文档（tkinter / socket / threading / configparser）
- PyInstaller 官方文档（打包指南）

---

## 2. 总体设计

### 2.1 设计目标

1. **易用**：中文界面、无需注册账号、填写 IP 即可连接。
2. **可靠**：同名文件不覆盖、按日期分目录、断线自动清理。
3. **健壮**：多人并发提交时集中排队，避免网络拥堵与文件冲突。
4. **轻量**：全部使用 Python 标准库，零第三方运行时依赖。
5. **可维护**：模块职责清晰、公共逻辑下沉、网络层与界面层解耦。

### 2.2 技术选型

| 技术 | 用途 | 说明 |
| --- | --- | --- |
| Python | 开发语言 | 3.10+，本项目在 3.13 验证 |
| tkinter / ttk | 图形界面 | Python 标准库 |
| socket | TCP 网络通信 | Python 标准库 |
| threading | 多线程网络服务 | Python 标准库 |
| configparser | ini 配置持久化 | Python 标准库 |
| queue | 事件队列 | 界面线程与网络线程间传递事件 |
| PyInstaller | 打包独立 exe | 仅打包阶段需要 |

### 2.3 系统架构

系统采用「**界面层 — 网络核心层 — 公共支撑层**」三层结构，运行在单个 TCP 局域网环境中。

```
┌──────────────────────────────────────────────┐
│                 主程序 main.py                 │
│            （单窗口，双 Tab 容器）               │
│  ┌───────────────┐   ┌───────────────┐        │
│  │  接收端 Tab    │   │  发送端 Tab    │        │
│  │ receiver_app  │   │  sender_app   │        │
│  └───────┬───────┘   └───────┬───────┘        │
└──────────┼───────────────────┼────────────────┘
           │ 事件回调            │ 事件回调
┌──────────▼───────────────────▼────────────────┐
│           网络核心层                            │
│  ReceiverServer(服务端)  SenderClient(客户端)   │
│         队列调度 / 收发 / 保存 / 下发             │
└─────────────────────┬──────────────────────────┘
                      │
┌─────────────────────▼──────────────────────────┐
│           公共支撑层 common/                     │
│   protocol(报文)  fileutil(存储命名)            │
│   config(ini)     app_style(样式)  help_dialog │
└────────────────────────────────────────────────┘
```

### 2.4 运行环境

- 操作系统：Windows（exe 运行）；源码亦可跨平台运行。
- 网络：接收端与发送端处于同一局域网，接收端开放固定 TCP 端口（默认 8888）。
- 运行方式：
  - 双击编译好的 `dist\局域网办公文件传输系统.exe`；
  - 或 `python main.py` 从源码运行。

---

## 3. 目录结构与模块划分

### 3.1 目录结构

```
office_lan_transfer/
├── main.py                      # 主程序：创建窗口与双 Tab，装配两端
├── common/                      # 公共支撑层
│   ├── __init__.py
│   ├── app_style.py             # 界面配色、字体、头栏/底栏、窗口图标
│   ├── config.py                # ini 配置持久化
│   ├── fileutil.py              # 日期目录 + 版本号命名
│   ├── help_dialog.py           # 帮助 / 关于对话框
│   └── protocol.py              # TCP 报文封装（发送/接收）
├── receiver/                    # 接收端模块
│   ├── __init__.py
│   ├── receiver_app.py          # 接收端图形界面
│   └── server_core.py           # 接收端服务端（监听/收发/排队/保存/下发）
├── sender/                      # 发送端模块
│   ├── __init__.py
│   ├── sender_app.py            # 发送端图形界面
│   └── client_core.py           # 发送端客户端（连接/收发/提交/排队）
├── tools/
│   ├── gen_icons.py             # 生成程序图标 combined.ico
│   └── gen_version.py           # 生成版本资源 version_main.txt
├── tests/                       # 自动化测试
│   ├── test_integration.py      # 端到端集成测试
│   ├── test_queue.py            # 排队机制测试
│   ├── test_dir_submit.py       # 文件夹上传测试
│   └── test_push_dir.py         # 文件夹下发测试
├── build_assets/                # 生成的图标与版本资源
├── dist/                        # 编译产物 exe
└── README.md
```

### 3.2 模块职责总览

| 模块 | 职责 |
| --- | --- |
| main.py | 装配主窗口、双 Tab；调用公共样式；启动两端 |
| common.protocol | 定义 TCP 报文封装与解析 |
| common.fileutil | 日期分目录、版本号命名（文件与文件夹） |
| common.config | ini 记忆用户最近填写内容 |
| common.app_style | 统一配色/字体/头栏/底栏/图标 |
| common.help_dialog | 中文使用说明与关于对话框 |
| receiver.server_core | TCP 服务端：连接、注册表、队列调度、保存、下发 |
| receiver.receiver_app | 接收端界面：启动服务、列表、下发、记录 |
| sender.client_core | TCP 客户端：连接注册、接收下发、提交（含排队） |
| sender.sender_app | 发送端界面：IP 校验、连接、接收、提交 |
| tools.* | 打包辅助：生成图标与版本资源 |

---

## 4. 通信协议设计

### 4.1 报文格式

一条完整消息由「头部长度 + JSON 头部 + 可选文件体」三段组成：

```
[ 4 字节头部长度 ][ JSON 头部字节 ][ 文件二进制数据（可选） ]
```

- 头部长度：4 字节大端序无符号整数，表示 JSON 头部占用的字节数。
- JSON 头部：utf-8 编码的 JSON 字典，记录消息类型、文件名、大小等元信息。
- 文件数据：当头部中 `filesize > 0` 时，紧随头部发送完整文件内容。

发送端用 `Protocol.send_msg(sock, header, data)`，接收端用 `Protocol.recv_msg(sock)` 成对使用。

### 4.2 消息类型定义

| type | 方向 | 说明 | 关键字段 |
| --- | --- | --- | --- |
| register | 客户端 → 服务端 | 发送者上线注册 | name, employee_id |
| ack | 双向 | 回执（成功/失败/确认） | status, msg |
| ping / pong | 双向 | 心跳保活 | — |
| push_task | 服务端 → 客户端 | 接收端下发单个文件 | filename, task_name, filesize, time |
| push_dir_start | 服务端 → 客户端 | 接收端声明下发整个文件夹 | filename, task_name, file_count, total_size, time |
| push_dir_data | 服务端 → 客户端 | 下发文件夹中的单个文件 | filename, task_name, rel_path, seq, file_count, filesize |
| push_dir_done | 服务端 → 客户端 | 文件夹全部文件已下发完成 | filename, task_name, file_count |
| task_received | 客户端 → 界面 | 客户端内部事件，收到下发文件/文件夹 | task_name, filename, path |
| submit_req | 客户端 → 服务端 | 申请提交（入队） | filename, task_name, is_dir, file_count, total_size |
| submit_queued | 服务端 → 客户端 | 告知排队位置 | queue_pos, queue_len |
| submit_go | 服务端 → 客户端 | 放行，开始上传 | — |
| submit_data | 客户端 → 服务端 | 实际文件体 | filename, task_name, filesize, rel_path, seq, file_count |
| submit_done | 客户端 → 服务端 | 文件夹全部文件已传完 | filename, task_name |
| queue_status | 服务端 → 全部 | 广播实时队列状态 | queue（列表） |

说明：客户端 → 界面的 `task_received`、`queued`、`submit_sending`、`submit_done` 等并非网络消息，而是网络线程通过 `on_event` 回调投递给界面的本地事件，此处一并列出以便理解全链路。

### 4.3 协议字段说明

- `name`：发送者姓名。
- `employee_id`：发送者工号。
- `filename`：展示文件名；文件夹模式下为顶层文件夹名。
- `task_name`：文件名称（可自定义）。
- `is_dir`：是否提交整个文件夹。
- `rel_path`：文件夹模式下当前文件在文件夹内的相对路径（如 `doc/report.md`）。
- `file_count` / `total_size`：文件夹的总文件数与总大小。
- `seq`：文件夹模式下当前是第几个文件。
- `queue_pos` / `queue_len`：排队位置与当前队列长度。

---

## 5. 数据存储与文件命名设计

### 5.1 目录结构（日期分目录 + 发送者分目录）

接收端保存提交文件：

```
save_dir/
└── 当天日期(YYYY-MM-DD)/
    └── 发送者姓名/
        ├── 文件A.docx           # 单个文件
        └── 文件夹名/             # 提交文件夹时的顶层目录
            ├── 子目录/...
            └── 文件B.txt
```

发送端保存下发的文件：

```
receive_dir/
└── 当天日期(YYYY-MM-DD)/
    ├── 通知A.txt
    └── 通知B.docx
```

发送端保存接收者下发的文件夹（下发方向，整体版本隔离）：

```
receive_dir/
└── 当天日期(YYYY-MM-DD)/
    └── 项目方案/
        ├── 子目录/...
        └── 文件B.txt
```

「当天日期」子目录由 `fileutil.dated_dir()` 自动建立，使**不同日期的文件互不重叠**。

### 5.2 版本号命名机制（同名不覆盖）

当目标文件/文件夹已存在时，自动追加 `_v2`、`_v3`…直到找到可用名字，**绝不覆盖原文件**：

- 文件：`report.docx` 已存在 → 保存为 `report_v2.docx`；再存 → `report_v3.docx`。
- 文件夹：`项目资料` 已存在 → 保存为 `项目资料_v2`。

实现：
- `fileutil.unique_path(directory, filename)` 处理文件。
- `fileutil.unique_dir_path(directory, name)` 处理文件夹。
- 两个函数均支持「以 `_vN` 结尾时从 N+1 继续编号」；极端情况下用毫秒时间戳兜底。

### 5.3 配置持久化（ini）

程序把用户最近一次填写的信息保存到程序目录下的 ini 文件，下次启动自动回填：

- 接收端：`receiver_config.ini`（端口、接收目录等）。
- 发送端：`sender_config.ini`（IP、端口、姓名、工号等）。

配置文件位置由 `config.app_base_dir()` 决定：打包为 exe 时为 exe 所在目录；源码运行时为项目根目录。

---

## 6. 线程模型与事件模型

### 6.1 线程模型

系统是「GUI 单线程 + 网络多线程」模型：

- **主线程（GUI）**：运行 tkinter 主循环，负责绘制与用户交互，不直接处理网络。
- **服务端线程**：`server_core` 启动后台 `accept_loop` 线程接受连接，并为每个客户端再启动一个独立 `client_loop` 线程。
- **客户端线程**：`client_core` 的 `connect()` 启动后台 `recv_loop` 线程，持续读取接收端消息。

tkinter **非线程安全**，因此所有网络线程都不直接操作界面控件，而是把事件放进回调/队列，由 GUI 主线程用 `after()` 周期性轮询处理。

### 6.2 事件模型

- 网络线程通过 `on_event(ev)` 回调投递事件字典 `ev`（含 `type` 字段）。
- 界面层把收到的网络线程事件放入 `queue.Queue`，再由 `_poll_events()` 用 `root.after()` 定时取出并更新界面。

事件字典常见 `type`：
`server_started`、`client_connected`、`client_left`、`submission`、`task_pushed`、`queue_status`、`error`、`log`、`connected`、`disconnected`、`task_received`、`queued`、`submit_sending`、`submit_sent`、`submit_done`、`ack` 等。

### 6.3 队列调度机制（排队）

为避免多发送者同时上传大文件造成网络拥堵，服务端对提交做**集中串行调度**：

1. 发送者发起 `submit_req`，服务端将其加入 `submit_queue`，分配排队号并回复 `submit_queued`。
2. 服务端向所有客户端广播 `queue_status`，两端实时看到排队变化。
3. 当无任务正在传输时，调度器放行队首：发送 `submit_go` 给队首客户端，将其置为 `transferring`。
4. 队首发送者开始逐个发送 `submit_data`；单文件保存后、或文件夹全部文件传完后发送 `submit_done`，服务端移出队列并调度下一个。
5. 若某发送者中途断开，服务端将其移出队列并重新调度。

队列中每项记录：`addr, name, task_name, filename, filesize, status(waiting/transferring), is_dir, file_count, received_count, folder_dir`。

---

## 7. 模块详细设计

### 7.1 公共支撑层 common

#### 7.1.1 app_style.py —— 界面样式与通用辅助

提供全局配色 `COLOR`（主色蓝 #2563EB、成功绿 #16A34A、背景灰 #F5F7FA 等）与字体 `FONT`（微软雅黑）；提供 `resource_path`（解析打包后资源路径，兼容 `sys._MEIPASS`）、`set_window_icon`（设置窗口图标）、`apply_style`（应用 clam 主题与各控件样式）、`add_header`（顶部彩色标题栏）、`add_footer`（底部开发者信息栏）。

#### 7.1.2 config.py —— ini 配置持久化

`app_base_dir()` 返回程序所在目录；`AppConfig` 类基于 `configparser` 封装 `get / set / save`，实现配置的读取、写入与保存，捕获异常保证配置损坏不影响程序启动。

#### 7.1.3 fileutil.py —— 存储与命名

`dated_dir(base, date_str)` 建立当天日期子目录；`unique_path(directory, filename)` 与 `unique_dir_path(directory, name)` 实现文件/文件夹的同名不覆盖版本控制（详见 5.2）。

#### 7.1.4 help_dialog.py —— 帮助与关于

`RECEIVER_HELP` / `SENDER_HELP` 为两段中文使用说明常量；`show_help(parent, mode)` 打开使用说明对话框，`show_about(parent)` 打开关于对话框（软件名、版本、开发者 prh、适用场景、技术、版权）。模块顶部定义 `APP_NAME`、`APP_VERSION`、`DEVELOPER`、`COPYRIGHT` 作为全局软件信息。

#### 7.1.5 protocol.py —— 报文封装

`Protocol` 类静态方法：`send_msg(sock, header, data)` 按格式发送；`recv_exact(sock, n)` 精确读取 n 字节（处理 TCP 粘包/半包）；`recv_msg(sock)` 读取一条完整消息并解析头部与文件体。

### 7.2 接收端模块 receiver

#### 7.2.1 receiver_app.py —— 接收端图形界面

- `get_local_ip()`：探测本机局域网 IP 用于展示。
- `ReceiverApp` 类：`__init__` 支持独立运行（container=None）或嵌入 Tab（container=Frame）；`_build_ui` 布局：顶部启动服务/定制目录、左侧在线发送者列表、右侧下发文件区、下方提交记录与运行日志；`_poll_events` 轮询网络事件队列；`_handle_event` 分发事件更新界面；`_update_queue` 刷新排队显示；`_start_server/_stop_server` 启停服务；`_choose_push_file/_choose_push_dir` 选择下发文件/文件夹；`_push_task` 下发文件或文件夹（全部或选中）；`_open_submission` 双击打开提交记录；`_open_receive_dir` 打开接收目录；`_load_config` 读取 ini 记忆。

#### 7.2.2 server_core.py —— 接收端服务端（核心）

`ReceiverServer` 类，维护客户端注册表 `clients`、姓名映射 `_name_to_addr`、提交队列 `submit_queue`；提供 `push_task`（下发单文件）与 `push_task_dir`（下发整个文件夹）。核心方法见第 8 节逐函数说明。

### 7.3 发送端模块 sender

#### 7.3.1 sender_app.py —— 发送端图形界面

`SenderApp` 类：`_build_ui` 布局连接区（IP/端口/姓名/工号）、下发文件列表、提交文件区；`_is_valid_ipv4` 校验 IP 格式（四段 0-255）；`_connect/_disconnect` 连接与断开；`_choose_submit_file/_choose_submit_dir` 选择文件/文件夹；`_submit` 发起提交；`_load_config` 读取 ini 记忆；`_log` 记录运行日志。

#### 7.3.2 client_core.py —— 发送端客户端（核心）

`SenderClient` 类：`connect` 建立连接并注册；`_recv_loop` 后台收消息；`_handle` 分派处理（push_task / push_dir_start / push_dir_data / push_dir_done / ack / submit_queued / submit_go / queue_status / pong）；`submit` 申请入队；`_collect_files` 递归收集文件夹文件；`_send_pending_submit` 被放行后上传单文件或逐个上传文件夹文件；用 `_pending_push` 记录正在接收的下发文件夹状态（顶层目标目录）。核心方法见第 8 节。

### 7.4 主程序 main.py

`MainApp` 类创建顶层 Tk 窗口、应用样式与图标、添加标题栏/底栏、建立两个 Tab，并分别用 `ReceiverApp(root, container=tab_recv)`、`SenderApp(root, container=tab_send)` 装配两端；`main()` 启动主循环。

### 7.5 工具与资源 tools

- `gen_icons.py`：用 Pillow 绘制扁平化「蓝色圆角方块 + 文件双向传输箭头」图标，输出 `build_assets\combined.ico`（含 16~256 多尺寸）。
- `gen_version.py`：生成 PyInstaller 版本资源文本，输出 `build_assets\version_main.txt`（产品名、版本 2.1.0.0、开发者 prh、版权）。

---

## 8. 函数详细设计

### 8.1 公共模块

| 函数 | 签名 | 作用与要点 |
| --- | --- | --- |
| app_style.resource_path | `resource_path(rel) -> str` | 返回资源绝对路径；打包时用 `sys._MEIPASS` |
| app_style.set_window_icon | `set_window_icon(root, icon_name)` | 设置窗口图标；失败静默 |
| app_style.apply_style | `apply_style(root) -> Style` | 应用 clam 主题与控件样式，返回 ttk.Style |
| app_style.add_header | `add_header(parent, title, subtitle)` | 顶部彩色标题栏（固定高度） |
| app_style.add_footer | `add_footer(parent, text)` | 底部开发者信息栏 |
| config.app_base_dir | `app_base_dir() -> str` | 返回 exe 所在目录或项目根目录 |
| config.AppConfig.__init__ | `AppConfig(filename)` | 绑定 ini 文件并读取 |
| config.AppConfig.get | `get(section, key, default) -> str` | 读配置项，带默认值 |
| config.AppConfig.set | `set(section, key, value)` | 写配置项（自动建节） |
| config.AppConfig.save | `save()` | 写回 ini，异常静默 |
| fileutil.dated_dir | `dated_dir(base, date_str=None) -> str` | 建当天日期子目录并返回路径 |
| fileutil.unique_path | `unique_path(directory, filename) -> str` | 文件同名加 `_vN` 版本，不覆盖 |
| fileutil.unique_dir_path | `unique_dir_path(directory, name) -> str` | 文件夹同名加 `_vN` 版本，不覆盖 |
| protocol.Protocol.send_msg | `send_msg(sock, header, data=b"")` | 按报文格式发送 |
| protocol.Protocol.recv_exact | `recv_exact(sock, n) -> bytes` | 循环精确读取 n 字节 |
| protocol.Protocol.recv_msg | `recv_msg(sock) -> (header, data)` | 读取一条完整消息 |
| help_dialog.show_help | `show_help(parent, mode)` | 打开中文使用说明 |
| help_dialog.show_about | `show_about(parent)` | 打开关于对话框 |

### 8.2 接收端服务端（ReceiverServer）

| 函数 | 作用与要点 |
| --- | --- |
| `__init__(host, port, save_dir, on_event)` | 初始化监听、注册表、提交队列、锁 |
| `_emit(event_type, **kw)` | 构造事件字典回调界面 |
| `start()` | 创建监听 socket（SO_REUSEADDR）、listen(128)、启动 accept 线程 |
| `stop()` | 关闭监听 socket 与所有客户端，清空注册表与队列 |
| `_accept_loop()` | 循环 accept，为每客户端启动独立线程 |
| `_client_loop(conn, addr)` | 客户端生命周期：注册登记、循环收消息、断开清理 |
| `_save_submission(conn, sender_name, task_name, filename, data)` | 保存单文件（日期/姓名/版本号），发 ack |
| `_enqueue_submission(conn, addr, client_info, header)` | 入队、分配排队号、回复 submit_queued、广播、调度 |
| `_broadcast_queue()` | 向所有客户端广播 queue_status |
| `_schedule()` | 队首放行：置 transferring，发 submit_go |
| `_receive_submission_data(conn, addr, client_info, header, data)` | 收实际文件；单文件即完成，文件夹累计计数 |
| `_save_dir_file(item, header, data)` | 保存文件夹内单文件（含相对路径/子目录结构） |
| `_finish_dir_submission(conn, addr, client_info)` | 文件夹完成：投递一条整体提交记录、发 ack、调度下一个 |
| `push_task(filename, filepath, task_name, targets=None)` | 向全部或指定发送者下发单个文件，返回成功数 |
| `push_task_dir(filename, dirpath, task_name, targets=None)` | 下发整个文件夹：push_dir_start 声明 → 逐个 push_dir_data → push_dir_done，返回成功数 |
| `_collect_dir_files(root)` | 递归收集文件夹内 (相对路径, 绝对路径) 列表，供下发文件夹使用 |
| `online_senders()` | 返回在线发送者姓名列表 |

### 8.3 发送端客户端（SenderClient）

| 函数 | 作用与要点 |
| --- | --- |
| `__init__(host, port, receive_dir, on_event)` | 初始化 socket、锁、待提交任务 |
| `_emit(etype, **kw)` | 构造事件回调界面 |
| `connect(name, employee_id)` | 建立连接（连接阶段 5s 超时）、发送 register、启动收线程 |
| `disconnect()` | 关闭连接并通知界面 |
| `_recv_loop()` | 后台线程持续读消息 |
| `_handle(header, data)` | 分派：push_task 存文件、push_dir_start/data/done 接收文件夹、ack 确认、submit_queued/go、queue_status |
| `submit(filename, path, task_name, is_dir=False)` | 校验、收集内容、发 submit_req 申请入队 |
| `_collect_files(root)` | 递归收集 (相对路径, 绝对路径) 列表 |
| `_send_pending_submit()` | 被放行后：单文件一条 submit_data；文件夹逐个 submit_data 后 submit_done |

> 下发文件夹接收逻辑：收到 `push_dir_start` 时用 `unique_dir_path` 确定顶层目标目录（整体版本隔离）并存入 `_pending_push`；`push_dir_data` 按 `rel_path` 还原子目录结构写入；`push_dir_done` 时投递一条整体接收记录（不逐文件刷屏）并清空 `_pending_push`。

### 8.4 界面层（ReceiverApp / SenderApp）

| 函数 | 作用与要点 |
| --- | --- |
| ReceiverApp.__init__ | 支持独立窗口或嵌入 Tab；加载 ini 记忆 |
| ReceiverApp._build_ui | 布局服务区、发送者列表、下发区、提交记录、日志 |
| ReceiverApp._poll_events | `after()` 轮询事件队列 |
| ReceiverApp._handle_event | 按事件类型更新界面 |
| ReceiverApp._update_queue | 刷新排队状态显示 |
| ReceiverApp._start_server / _stop_server | 启停 ReceiverServer |
| ReceiverApp._choose_push_file / _choose_push_dir | 选择下发文件 / 文件夹 |
| ReceiverApp._choose_recv_dir | 定制接收目录 |
| ReceiverApp._push_task | 向全部或选中发送者下发（文件或文件夹） |
| ReceiverApp._open_submission / _open_receive_dir | 打开提交记录 / 接收目录 |
| SenderApp._build_ui | 布局连接区、下发列表、提交区、日志 |
| SenderApp._is_valid_ipv4 | 校验 IP 为四段 0-255 |
| SenderApp._connect / _disconnect | 连接 / 断开 SenderClient |
| SenderApp._choose_submit_file / _choose_submit_dir | 选择文件 / 文件夹 |
| SenderApp._submit | 发起提交（含排队提示） |
| SenderApp._load_config / _log | 读取记忆 / 记录日志 |

---

## 9. 关键流程设计

### 9.1 连接注册流程

1. 发送端填写 IP、端口、姓名、工号，点击「连接」。
2. 客户端建立 TCP 连接，发送 `register`（name、employee_id）。
3. 服务端登记到 `clients` 与 `_name_to_addr`，同一姓名旧连接被替换。
4. 服务端回 `ack(ok)`；客户端启动后台收线程，界面显示已连接。

### 9.2 下发单个文件流程

1. 接收端选择文件、填写文件名称，点「发送给全部/选中发送者」。
2. 服务端 `push_task` 读取文件，向目标发送 `push_task`（含文件体）。
3. 发送端 `_handle` 收到后，用 `dated_dir + unique_path` 保存到当天日期目录（同名加版本），界面显示。

### 9.3 下发文件夹流程

1. 接收端选择文件夹，服务端 `push_task_dir` 用 `_collect_dir_files` 递归收集所有文件及相对路径。
2. 向目标发送 `push_dir_start`（file_count、total_size），发送端用 `unique_dir_path` 确定顶层目标目录（整体版本隔离）。
3. 服务端逐个发送 `push_dir_data`（头部带 `rel_path`、`seq`、`file_count` 与文件体）。
4. 发送端按 `rel_path` 还原子目录结构写入对应子目录。
5. 全部文件发完后服务端发送 `push_dir_done`，发送端投递一条整体接收记录（不逐文件刷屏）。

### 9.4 提交单个文件流程（含排队）

1. 发送端选择文件、填文件名称，点「提交文件」。
2. 客户端 `submit` 发送 `submit_req`（不带文件体）。
3. 服务端 `_enqueue_submission` 入队、回复 `submit_queued`（排第几位）、广播 `queue_status`。
4. 调度器放行队首：发 `submit_go`。
5. 客户端 `_send_pending_submit` 发送 `submit_data`（含文件体）。
6. 服务端 `_receive_submission_data` 保存文件，回 `ack(文件已接收)`，移出队列、调度下一个。
7. 客户端收到 ack 后清空待提交，界面显示提交成功。

### 9.5 提交文件夹流程（含排队 + 子目录）

1. 发送端选择文件夹，客户端 `_collect_files` 递归收集所有文件及相对路径。
2. 发送 `submit_req`（is_dir=True、file_count、total_size），入队排队。
3. 放行后，客户端逐个发送 `submit_data`（头部带 `rel_path`、`seq`、`file_count`）。
4. 服务端 `_save_dir_file` 首次保存时用 `unique_dir_path` 确定顶层文件夹目录（整体版本隔离），其后文件按相对路径写入对应子目录。
5. 全部文件发完后客户端发送 `submit_done`。
6. 服务端 `_finish_dir_submission` 投递一条整体提交记录（不逐文件刷屏）、回 ack、调度下一个。

### 9.6 排队调度流程

见 6.3。要点：同一时刻仅一个任务处于 `transferring`，`_schedule` 只在 `_transferring == False` 且队列非空时放行队首；断线客户端会被移出队列并重新调度。

### 9.7 同名文件版本控制流程

保存时统一调用 `unique_path` / `unique_dir_path`：目标已存在则以 `_vN` 递增寻找空闲名；文件夹模式下顶层目录做整体版本隔离，内部文件按相对路径写入不再逐个加版本。

---

## 10. 界面设计

### 10.1 主窗口布局

- 顶部：蓝色标题栏（软件名 + 副标题）。
- 中部：ttk.Notebook 双 Tab ——「文件接收端」「文件发送端」。
- 底部：开发者信息栏（开发者 prh、版本）。

### 10.2 接收端界面

- 服务区：本机 IP、端口、「启动/停止服务」、定制接收目录。
- 左侧「在线发送者」：Treeview 列表，可多选。
- 右侧「下发文件」：选择文件/选择文件夹 + 文件名称，「发送给全部」「发送给选中」。
- 下方「提交记录」：实时列表，双击打开；文件夹显示「（文件夹，n个文件）」。
- 「打开文件目录」与运行日志区。

### 10.3 发送端界面

- 连接区：接收端 IP（含 IP 规则校验）、端口、姓名、工号、「连接/断开」。
- 「接收端下发的文件」列表，双击打开。
- 「提交文件」区：选择文件 / 选择文件夹 + 文件名称 +「提交文件」。
- 运行日志区（记录连接、排队、发送、成功等，以文字说明即可）。

### 10.4 帮助与关于

- 「帮助」按钮弹出中文使用说明（接收端 / 发送端分别给出）。
- 「关于」显示软件名称、版本、开发者 prh、适用场景、技术栈、版权。

---

## 11. 测试设计

| 测试文件 | 覆盖内容 |
| --- | --- |
| tests/test_integration.py | 端到端：服务启动、双发送者连接注册、下发/接收、单文件提交、重复提交 `_v2`、`unique_path` 跨日期隔离 |
| tests/test_dir_submit.py | 文件夹上传：含子目录原样保存、提交记录一条、重复提交 `_v2` 不覆盖 |
| tests/test_push_dir.py | 文件夹下发：接收端下发含子目录文件夹、发送端原样保存、接收记录一条、重复下发 `_v2` 不覆盖 |
| tests/test_queue.py | 并发排队：三名发送者同时提交大文件，验证排队号、依次放行、全部接收 |

运行：`python tests\test_integration.py`、`python tests\test_dir_submit.py`、`python tests\test_push_dir.py`、`python tests\test_queue.py`。均无需图形界面，输出 `[OK]` / `TEST OK` 即通过。

---

## 12. 编译打包设计

打包流程（在装有 Python 与 PyInstaller 的电脑上）：

1. `python tools\gen_icons.py` → 生成 `build_assets\combined.ico`。
2. `python tools\gen_version.py` → 生成 `build_assets\version_main.txt`（版本 2.1.0.0、开发者 prh）。
3. PyInstaller 打包：

```
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name 局域网办公文件传输系统 ^
  --icon build_assets\combined.ico ^
  --version-file build_assets\version_main.txt ^
  --add-data "build_assets\combined.ico;." ^
  main.py
```

产物：`dist\局域网办公文件传输系统.exe`，可拷贝到任意 Windows 电脑双击运行，无需安装 Python。

---

## 13. 版本记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v2.1.0.0 | 2026-10-27 | 新增「接收端下发整个文件夹」功能：接收端可选择文件夹连同子文件夹原样下发，发送端按相对路径原样保存（整体版本隔离 `_v2`）；协议新增 push_dir_start/data/done 消息类型；新增 test_push_dir.py 测试 |
| v2.0.0.0 | 2026-10-27 | 全面企业化重构：面向企业办公场景，统一「接收端/发送端/发送者/接收者/工号/文件」术语；项目主目录更名 office_lan_transfer；更新图标、版本信息、README 与本文档 |
| v1.5 | 2026-10-26 | 合并为单程序双 Tab（文件接收端 / 文件发送端） |

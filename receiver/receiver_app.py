# -*- coding: utf-8 -*-
"""
接收端图形界面（GUI）
====================
【文件定位】本模块是"文件接收端"的图形界面层，负责把用户操作转发给
ReceiverServer（网络核心层），并把核心层产生的事件展示到界面上。

【设计思路】
  1. 界面与网络解耦：
     本模块只负责界面布局与交互，真正的网络收发、保存、调度都在 server_core.py。
     二者通过"事件队列 + on_event 回调"衔接，可分别独立测试。

  2. 两种运行模式：
     - container 为 None：作为独立窗口运行（自行设置标题/尺寸/图标/栏）；
     - container 传入 ttk.Frame：把界面构建到该容器内，供合并程序嵌入 tab 使用。
     这个设计让"接收端"既能独立运行，也能被 main.py 组装成双 Tab 的一部分。

  3. 线程模型（tkinter 非线程安全）：
     - 服务端在后台线程运行，产生的事件放入 queue.Queue（on_event=队列.put）；
     - 主线程用 self.parent.after(100, self._poll_events) 每 100ms 轮询一次队列，
       取出事件调用 _handle_event 更新界面。从而"后台线程不碰界面，界面线程处理事件"。

  4. 界面布局：
     顶部服务控制（IP/端口/启停/目录定制）、中部左侧在线发送者列表 + 右侧下发区、
     中部下方提交队列（实时）、底部提交记录 + 运行日志。

  5. 下发设计：
     - 支持下发单个文件（_choose_push_file）与整个文件夹（_choose_push_dir）；
     - 文件名缺省为所选文件/文件夹名（不含扩展名），可再修改；
     - 通过 selected_only 区分"发送给选中发送者"或"发送给全部发送者"。
"""
import os
import queue
import socket
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from common import app_style
from common.config import AppConfig
from common.help_dialog import show_about, show_help
from receiver.server_core import ReceiverServer


def get_local_ip():
    """获取本机局域网 IP 地址（用于展示给接收端）。

    【设计思路】
    - 用一个 UDP socket 连接外部地址（不真正发送数据），
      系统会据此返回本机"出口"网卡的 IP——这是探测本机局域网 IP 的常见技巧。
    - 失败时兜底返回回环地址 127.0.0.1（仅用于展示，不影响服务绑定）。
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 不真正发送数据，仅用于探测本机出口 IP
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class ReceiverApp:
    """接收端主窗口。

    【设计思路】
    - 持有：根窗口/容器、事件队列、ReceiverServer 实例、配置对象。
    - 界面构建与事件处理分离：_build_ui 建界面，_poll_events/_handle_event 处理事件。
    """

    def __init__(self, root, container=None):
        """
        :param root:      顶层 Tk 根窗口
        :param container: 若为 None，则本类作为独立窗口运行（自行设置标题/尺寸/图标/栏）；
                          若传入一个 Frame，则把界面构建到该容器内（供合并程序 tab 使用）。
        """
        self.root = root
        self.parent = container if container is not None else root
        standalone = container is None

        if standalone:
            # 独立窗口运行：设置标题、尺寸、样式、图标、标题栏与底栏
            self.root.title("接收端 - 局域网办公文件传输系统")
            self.root.geometry("1020x700")
            self.root.minsize(880, 600)
            self.style = app_style.apply_style(root)
            app_style.set_window_icon(root, "combined.ico")
            app_style.add_header(root, "接收端 · 文件接收",
                                 subtitle="局域网文件接收与发送")
            app_style.add_footer(root, "开发者：prh    版本 v2.1    局域网办公文件传输系统")

        # 文件保存基础目录：
        #  - 打包为独立 exe 运行时，保存在可执行程序所在目录，确保数据持久化
        #  - 直接运行源码时，保存在项目根目录下
        if getattr(sys, "frozen", False):
            base_dir_parent = os.path.dirname(sys.executable)
        else:
            base_dir_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.base_dir = os.path.join(base_dir_parent, "receiver_data")
        self.receive_dir = os.path.join(self.base_dir, "received")
        os.makedirs(self.receive_dir, exist_ok=True)

        # 事件队列：服务端线程投递事件，主线程轮询处理
        self.event_queue = queue.Queue()
        self.server = None   # ReceiverServer 实例（启动服务后创建）

        # 待下发文件的路径 与 是否文件夹
        self._push_filepath = None
        self._push_is_dir = False

        self._build_ui()
        # 读取上次设置的端口与接收目录并自动回填
        self.config = AppConfig("receiver_config.ini")
        self._load_config()
        # 每 100ms 轮询一次事件队列（线程安全衔接）
        self.parent.after(100, self._poll_events)

    # ================= 界面构建 =================
    def _build_ui(self):
        """构建整个接收端界面（按区域从上到下布局）。"""
        # ---- 顶部：服务控制 ----
        top = ttk.LabelFrame(self.parent, text="服务控制")
        top.pack(fill="x", padx=8, pady=6)

        # 本机 IP（只读展示）
        ttk.Label(top, text="本机IP:").grid(row=0, column=0, padx=(8, 4), pady=4, sticky="e")
        self.var_ip = tk.StringVar(value=get_local_ip())
        ttk.Entry(top, textvariable=self.var_ip, width=15, state="readonly").grid(row=0, column=1, padx=4)

        # 端口（可修改，默认 8888）
        ttk.Label(top, text="端口:").grid(row=0, column=2, padx=(8, 4), sticky="e")
        self.var_port = tk.StringVar(value="8888")
        ttk.Entry(top, textvariable=self.var_port, width=8).grid(row=0, column=3, padx=4)

        # 启动 / 停止服务按钮
        self.btn_start = ttk.Button(top, text="启动服务", command=self._start_server,
                                    style="Accent.TButton")
        self.btn_start.grid(row=0, column=4, padx=6, pady=4)
        self.btn_stop = ttk.Button(top, text="停止服务", command=self._stop_server, state="disabled")
        self.btn_stop.grid(row=0, column=5, padx=6, pady=4)

        # 服务状态
        self.var_status = tk.StringVar(value="● 未启动")
        ttk.Label(top, textvariable=self.var_status, foreground="#2563EB").grid(row=0, column=6, padx=10)

        # 打开文件目录 / 帮助 / 关于
        ttk.Button(top, text="打开文件目录", command=self._open_receive_dir).grid(row=0, column=7, padx=(10, 6))
        ttk.Button(top, text="使用帮助", command=lambda: show_help(self.parent, "receiver")).grid(row=0, column=8, padx=4)
        ttk.Button(top, text="关于", command=lambda: show_about(self.parent)).grid(row=0, column=9, padx=(4, 8))

        # 第二行：接收目录（可定制）
        ttk.Label(top, text="接收目录:").grid(row=1, column=0, padx=(8, 4), pady=(0, 6), sticky="e")
        self.var_recv_dir = tk.StringVar(value=self.receive_dir)
        ttk.Entry(top, textvariable=self.var_recv_dir, width=38).grid(row=1, column=1, columnspan=3, padx=4, pady=(0, 6), sticky="we")
        ttk.Button(top, text="浏览…", command=self._choose_recv_dir).grid(row=1, column=4, padx=6, pady=(0, 6))
        ttk.Label(top, text="收到的文件按 日期/发送者名 存入此目录",
                  foreground="#6B7280").grid(row=1, column=5, columnspan=5, padx=6, pady=(0, 6), sticky="w")

        # ---- 中部：左侧在线发送者 + 右侧下发 ----
        mid = ttk.Frame(self.parent)
        mid.pack(fill="both", expand=True, padx=8, pady=4)

        # 左：在线发送者列表（支持多选）
        left = ttk.LabelFrame(mid, text="在线发送者")
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.stu_list = tk.Listbox(left, selectmode="extended")   # extended 支持 Ctrl/Shift 多选
        self.stu_list.pack(fill="both", expand=True, padx=6, pady=6)
        btn_row = ttk.Frame(left)
        btn_row.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Button(btn_row, text="刷新列表", command=self._refresh_senders).pack(side="left")
        ttk.Label(btn_row, text="  提示：Ctrl/Shift 可多选").pack(side="left")

        # 右：下发文件区
        right = ttk.LabelFrame(mid, text="下发文件")
        right.pack(side="right", fill="both", expand=True, padx=(4, 0))

        # 文件名称（缺省为所选文件/文件夹名）
        ttk.Label(right, text="文件名称:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        self.var_task = tk.StringVar(value="")
        ttk.Entry(right, textvariable=self.var_task, width=30).grid(row=0, column=1, columnspan=3, padx=6, pady=8, sticky="we")

        # 已选文件/文件夹展示
        ttk.Label(right, text="文件:").grid(row=1, column=0, padx=6, pady=8, sticky="ne")
        self.var_push_file = tk.StringVar(value="（未选择文件）")
        ttk.Label(right, textvariable=self.var_push_file, wraplength=280, justify="left").grid(row=1, column=1, columnspan=3, padx=6, pady=8, sticky="w")

        # 选择文件 / 选择文件夹（支持下发单个文件与整个文件夹）
        ttk.Button(right, text="选择文件", command=self._choose_push_file).grid(row=2, column=1, padx=6, pady=4, sticky="w")
        ttk.Button(right, text="选择文件夹", command=self._choose_push_dir).grid(row=2, column=2, padx=6, pady=4, sticky="w")
        # 下发目标：选中发送者 / 全部发送者
        ttk.Button(right, text="发送给选中发送者", command=lambda: self._push_task(selected_only=True)).grid(row=3, column=1, padx=6, pady=4, sticky="w")
        ttk.Button(right, text="发送给全部发送者", command=lambda: self._push_task(selected_only=False)).grid(row=3, column=2, columnspan=2, padx=6, pady=4, sticky="w")

        # 下发记录（本机已下发的内容）
        ttk.Label(right, text="下发记录:").grid(row=4, column=0, padx=6, pady=(12, 4), sticky="ne")
        self.push_log = tk.Text(right, height=6, state="disabled")
        self.push_log.grid(row=4, column=1, columnspan=3, padx=6, pady=(12, 6), sticky="nsew")
        right.columnconfigure(1, weight=1)   # 让第 1 列随窗口伸缩

        # ---- 中部下方：提交队列（实时） ----
        qf = ttk.LabelFrame(self.parent, text="提交队列（实时）—— 发送者同时提交时自动排队，一次上传一个")
        qf.pack(fill="x", padx=8, pady=4)

        qcols = ("pos", "sender", "task", "status")
        self.queue_tree = ttk.Treeview(qf, columns=qcols, show="headings", height=5)
        self.queue_tree.heading("pos", text="排位")
        self.queue_tree.heading("sender", text="发送者")
        self.queue_tree.heading("task", text="文件")
        self.queue_tree.heading("status", text="状态")
        self.queue_tree.column("pos", width=60, anchor="center")
        self.queue_tree.column("sender", width=150)
        self.queue_tree.column("task", width=340)
        self.queue_tree.column("status", width=180, anchor="center")
        self.queue_tree.pack(fill="x", padx=6, pady=6)

        # ---- 底部：提交记录 ----
        bottom = ttk.LabelFrame(self.parent, text="提交记录（双击可打开文件）")
        bottom.pack(fill="both", expand=True, padx=8, pady=4)

        cols = ("time", "sender", "task", "filename", "size")
        self.tree = ttk.Treeview(bottom, columns=cols, show="headings")
        self.tree.heading("time", text="提交时间")
        self.tree.heading("sender", text="发送者")
        self.tree.heading("task", text="文件")
        self.tree.heading("filename", text="文件名")
        self.tree.heading("size", text="大小(KB)")
        self.tree.column("time", width=150)
        self.tree.column("sender", width=90)
        self.tree.column("task", width=140)
        self.tree.column("filename", width=240)
        self.tree.column("size", width=80)
        self.tree.pack(fill="both", expand=True, padx=6, pady=6)
        # 双击打开：在 tags 中保存了文件/文件夹的路径
        self.tree.bind("<Double-1>", self._open_submission)

        # ---- 运行日志 ----
        logf = ttk.LabelFrame(self.parent, text="运行日志")
        logf.pack(fill="x", padx=8, pady=(0, 6))
        self.log = tk.Text(logf, height=6, state="disabled")
        self.log.pack(fill="x", padx=6, pady=6)

    # ================= 事件轮询（线程安全） =================
    def _poll_events(self):
        """从队列取出服务端事件并更新界面，由 after 周期调用。

        【设计思路】
        - 一次把所有可取出的事件取完（get_nowait 直到 queue.Empty），
          避免每 100ms 只处理一条、堆积过多。
        - 处理完后再用 after 注册下一次轮询，形成持续的事件消费循环。
        """
        try:
            while True:
                ev = self.event_queue.get_nowait()
                self._handle_event(ev)
        except queue.Empty:
            pass
        self.parent.after(100, self._poll_events)

    def _handle_event(self, ev):
        """根据事件类型更新界面。

        【设计思路】
        - 这是"事件分发器"：网络核心层投递的事件在此一一对应到界面刷新动作。
        - 新增事件类型只需在此增加一个分支，扩展友好。
        """
        etype = ev.get("type")
        if etype == "server_started":
            self.var_status.set("● 服务已启动")
            self._log("服务已启动，监听 %s:%s" % (ev["host"], ev["port"]))
        elif etype == "server_stopped":
            self.var_status.set("● 已停止")
            self._log("服务已停止")
        elif etype == "client_connected":
            # 发送者上线：记日志并刷新列表
            self._log("发送者 %s（%s）上线，地址 %s" % (ev["name"], ev["employee_id"], ev["addr"]))
            self._refresh_senders()
        elif etype == "client_left":
            self._log("发送者 %s 已断开" % ev["name"])
            self._refresh_senders()
        elif etype == "submission":
            # 收到发送者提交（单文件或文件夹整体记录）
            self._add_submission(ev)
            self._log("收到 %s 提交的文件《%s》：%s" % (ev["sender"], ev["task_name"], ev["filename"]))
        elif etype == "queue_status":
            # 更新提交队列表格
            self._update_queue(ev.get("queue", []))
        elif etype == "task_pushed":
            # 本机已下发内容，记录到下发记录区
            self._append_push_log("[%s] 下发《%s》%s 给 %d 名发送者" % (ev["time"], ev["task_name"], ev["filename"], ev["count"]))
            self._log("已下发《%s》给 %d 名发送者" % (ev["task_name"], ev["count"]))
        elif etype == "error":
            messagebox.showerror("错误", ev.get("message", "未知错误"))
        elif etype == "log":
            self._log(ev.get("text", ""))

    def _update_queue(self, queue):
        """刷新提交队列表格（排位 / 发送者 / 文件 / 状态）。

        【设计思路】
        - 先清空再重建，保证表格与最新队列一致。
        - 用状态映射把英文状态翻译成中文（waiting→排队等待、transferring→正在上传）。
        - 文件夹任务在文件名后追加"（文件夹）"标记，便于识别。
        """
        self.queue_tree.delete(*self.queue_tree.get_children())
        status_map = {"waiting": "排队等待", "transferring": "正在上传"}
        for it in queue:
            task = it.get("task") or it.get("filename", "")
            # 文件夹任务在文件名后加"（文件夹）"标记
            if it.get("is_dir"):
                task += "（文件夹）"
            self.queue_tree.insert(
                "", "end",
                values=(it.get("pos", ""), it.get("name", ""), task,
                        status_map.get(it.get("status"), it.get("status", ""))),
            )

    # ================= 服务启停 =================
    def _load_config(self):
        """读取上次设置的端口与接收目录并自动回填。

        【设计思路】
        - 从 ini 读取端口和接收目录；若配置过目录，则切换到该目录并确保存在，
          实现"上次的设置下次自动带出"。
        """
        self.var_port.set(self.config.get("server", "port", "8888"))
        recv = self.config.get("server", "receive_dir")
        if recv:
            self.receive_dir = os.path.abspath(recv)
            self.var_recv_dir.set(self.receive_dir)
            os.makedirs(self.receive_dir, exist_ok=True)

    def _start_server(self):
        """启动接收端网络服务。

        【设计思路】
        - 校验端口为 1-65535 的数字。
        - 保存本次设置的端口与接收目录到 ini（下次自动带出）。
        - 创建 ReceiverServer 并 start()；成功则切换按钮状态，失败提示。
        """
        try:
            port = int(self.var_port.get().strip())
        except ValueError:
            messagebox.showerror("错误", "端口必须是数字")
            return
        if not (1 <= port <= 65535):
            messagebox.showerror("错误", "端口必须在 1-65535 之间")
            return
        # 保存本次设置的端口与接收目录，下次启动自动回填
        self.config.set("server", "port", self.var_port.get().strip())
        self.config.set("server", "receive_dir", self.receive_dir)
        self.config.save()

        # 创建并启动服务端；on_event 指向事件队列的 put（线程安全投递）
        self.server = ReceiverServer("0.0.0.0", port, self.receive_dir, on_event=self.event_queue.put)
        if self.server.start():
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.var_status.set("● 服务已启动")
        else:
            messagebox.showerror("错误", "启动失败，请检查端口是否被占用")

    def _stop_server(self):
        """停止接收端网络服务并复位按钮状态。"""
        if self.server:
            self.server.stop()
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    # ================= 下发 =================
    def _choose_push_file(self):
        """选择要下发的单个文件。

        【设计思路】
        - 文件名称缺省为所选文件名（不含扩展名）；若用户已填写则保留。
        """
        path = filedialog.askopenfilename(title="选择要下发的文件")
        if path:
            self._push_filepath = path
            self._push_is_dir = False
            self.var_push_file.set(os.path.basename(path))
            # 文件名称缺省为所选文件名（不含扩展名）；若用户已填写则保留
            if not self.var_task.get().strip():
                stem = os.path.splitext(os.path.basename(path))[0]
                self.var_task.set(stem)

    def _choose_push_dir(self):
        """选择要下发的整个文件夹（含其下所有子文件夹）。

        【设计思路】
        - 与选文件对称：置 _push_is_dir=True，文件名缺省为文件夹名。
        - 真正的下发由 server_core.push_task_dir 完成。
        """
        path = filedialog.askdirectory(title="选择要下发的文件夹（含子文件夹）")
        if path:
            self._push_filepath = path
            self._push_is_dir = True
            self.var_push_file.set(os.path.basename(path) + "（文件夹）")
            # 文件名称缺省为所选文件夹名；若用户已填写则保留
            if not self.var_task.get().strip():
                self.var_task.set(os.path.basename(path))

    # ================= 接收目录定制 =================
    def _choose_recv_dir(self):
        """浏览并设置文件接收目录。

        【设计思路】
        - 用户可自定义接收目录；若服务正在运行，实时更新服务端的 save_dir。
        - 保存配置到 ini，下次启动自动带出。
        """
        path = filedialog.askdirectory(title="选择文件接收目录")
        if path:
            self.receive_dir = os.path.abspath(path)
            os.makedirs(self.receive_dir, exist_ok=True)
            self.var_recv_dir.set(self.receive_dir)
            # 若服务正在运行，实时更新服务端的保存目录
            if self.server:
                self.server.save_dir = self.receive_dir
            # 保存接收目录配置，下次启动自动回填
            self.config.set("server", "receive_dir", self.receive_dir)
            self.config.save()
            self._log("文件接收目录已设置为：%s" % self.receive_dir)

    def _push_task(self, selected_only):
        """执行下发：向全部发送者或选中的发送者下发文件/文件夹。

        【设计思路】
        - 校验：服务已启动、已填写文件名称、已选择下发内容。
        - selected_only 为 True 时，从左侧列表取选中发送者作为 targets；
          为 False 时 targets=None（表示全部）。
        - 根据 _push_is_dir 决定调用 push_task_dir（文件夹）或 push_task（单文件）。
        """
        if not self.server or not self.server.running:
            messagebox.showwarning("提示", "请先启动服务")
            return
        task_name = self.var_task.get().strip()
        if not task_name:
            messagebox.showwarning("提示", "请填写文件名称")
            return
        if not self._push_filepath:
            messagebox.showwarning("提示", "请先选择要下发的文件")
            return

        targets = None
        if selected_only:
            # 从左侧列表取选中的发送者姓名
            sel = self.stu_list.curselection()
            if not sel:
                messagebox.showwarning("提示", "请先在左侧选择发送者（Ctrl/Shift 可多选）")
                return
            targets = [self.stu_list.get(i) for i in sel]

        if self._push_is_dir:
            # 下发整个文件夹（含其下所有子文件夹，原样保存目录结构）
            self.server.push_task_dir(os.path.basename(self._push_filepath),
                                      self._push_filepath, task_name, targets)
        else:
            # 下发单个文件
            self.server.push_task(os.path.basename(self._push_filepath),
                                  self._push_filepath, task_name, targets)

    # ================= 界面辅助 =================
    def _refresh_senders(self):
        """刷新"在线发送者"列表。"""
        self.stu_list.delete(0, tk.END)
        if self.server:
            for name in self.server.online_senders():
                self.stu_list.insert(tk.END, name)

    def _add_submission(self, ev):
        """向"提交记录"表格插入一条记录（tags 保存路径供双击打开）。"""
        size_kb = round(ev["size"] / 1024.0, 1)
        self.tree.insert("", 0, values=(ev["time"], ev["sender"], ev["task_name"], ev["filename"], size_kb),
                         tags=(ev["path"],))

    def _open_submission(self, _event):
        """双击提交记录：用系统默认程序打开对应文件/文件夹。"""
        item = self.tree.focus()
        if item:
            path = self.tree.item(item, "tags")[0]
            try:
                os.startfile(path)  # Windows 下用默认程序打开
            except Exception as e:
                messagebox.showerror("错误", "无法打开文件：%s" % e)

    def _open_receive_dir(self):
        """打开接收目录（用系统资源管理器）。"""
        try:
            os.startfile(self.receive_dir)
        except Exception as e:
            messagebox.showerror("错误", "无法打开目录：%s" % e)

    def _append_push_log(self, text):
        """向下发记录区追加一行（只读）。"""
        self.push_log.config(state="normal")
        self.push_log.insert(tk.END, text + "\n")
        self.push_log.see(tk.END)
        self.push_log.config(state="disabled")

    def _log(self, text):
        """向运行日志区追加一行（只读）。"""
        self.log.config(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

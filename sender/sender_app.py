# -*- coding: utf-8 -*-
"""
发送端图形界面（GUI）
====================
【文件定位】本模块是"文件发送端"的图形界面层，负责把用户操作转发给
SenderClient（网络核心层），并把核心层产生的事件展示到界面上。

【设计思路】
  1. 界面与网络解耦：
     本模块只负责界面布局与交互，真正的连接、提交、保存都在 client_core.py。
     二者通过"事件队列 + on_event 回调"衔接，可分别独立测试。

  2. 两种运行模式：
     - container 为 None：作为独立窗口运行；
     - container 传入 ttk.Frame：把界面构建到该容器内，供合并程序嵌入 tab 使用。

  3. 线程模型（tkinter 非线程安全）：
     - 客户端在后台线程运行，产生的事件放入 queue.Queue（on_event=队列.put）；
     - 主线程用 self.parent.after(100, self._poll_events) 每 100ms 轮询队列，
       取出事件调用 _handle_event 更新界面。后台线程不碰界面、界面线程处理事件。

  4. 无需注册账号：
     只需填写接收端 IP、姓名、工号即可连接，流程极简。

  5. 配置持久化：
     上次填写的 IP、姓名、工号、端口存入 ini，下次启动自动回填，免重复输入。

  6. 界面布局：
     顶部连接控制、中部接收端下发的文件列表、下部提交队列（实时）、
     提交文件区（选文件/选文件夹）、运行日志。
"""
import os
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from common import app_style
from common.config import AppConfig
from common.help_dialog import show_about, show_help
from sender.client_core import SenderClient


class SenderApp:
    """发送端主窗口。

    【设计思路】
    - 持有：根窗口/容器、事件队列、SenderClient 实例、配置对象。
    - 界面构建与事件处理分离：_build_ui 建界面，_poll_events/_handle_event 处理事件。
    """

    def __init__(self, root, container=None):
        """
        :param root:      顶层 Tk 根窗口
        :param container: 若为 None，则本类作为独立窗口运行；
                          若传入一个 Frame，则把界面构建到该容器内（供合并程序 tab 使用）。
        """
        self.root = root
        self.parent = container if container is not None else root
        standalone = container is None

        if standalone:
            # 独立窗口运行：设置标题、尺寸、样式、图标、标题栏与底栏
            self.root.title("发送端 - 局域网办公文件传输系统")
            self.root.geometry("980x680")
            self.root.minsize(860, 600)
            self.style = app_style.apply_style(root)
            app_style.set_window_icon(root, "combined.ico")
            app_style.add_header(root, "发送端 · 文件发送",
                                 subtitle="局域网文件接收与发送")
            app_style.add_footer(root, "开发者：prh    版本 v2.1    局域网办公文件传输系统")

        # 接收文件的本地保存目录（exe 所在目录或项目根目录下）
        if getattr(sys, "frozen", False):
            base_dir_parent = os.path.dirname(sys.executable)
        else:
            base_dir_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.base_dir = os.path.join(base_dir_parent, "sender_data")
        self.receive_dir = os.path.join(self.base_dir, "received")
        os.makedirs(self.receive_dir, exist_ok=True)

        # 事件队列：客户端线程投递事件，主线程轮询处理
        self.event_queue = queue.Queue()
        self.client = None   # SenderClient 实例（连接后创建）

        # 待提交文件路径 与 是否文件夹
        self._submit_path = None
        self._submit_is_dir = False

        self._build_ui()
        # 读取上次填写的 IP、姓名、工号、端口并自动回填
        self.config = AppConfig("sender_config.ini")
        self._load_config()
        # 每 100ms 轮询一次事件队列（线程安全衔接）
        self.parent.after(100, self._poll_events)

    # ================= 界面构建 =================
    def _build_ui(self):
        """构建整个发送端界面（按区域从上到下布局）。"""
        # ---- 顶部：连接控制 ----
        top = ttk.LabelFrame(self.parent, text="连接接收端（无需注册账号）")
        top.pack(fill="x", padx=8, pady=6)

        # 接收端 IP（必填）
        ttk.Label(top, text="接收端IP:").grid(row=0, column=0, padx=(8, 4), pady=6, sticky="e")
        self.var_ip = tk.StringVar(value="192.168.1.100")
        ttk.Entry(top, textvariable=self.var_ip, width=16).grid(row=0, column=1, padx=4)

        # 端口（默认 8888，与接收端一致）
        ttk.Label(top, text="端口:").grid(row=0, column=2, padx=(8, 4), sticky="e")
        self.var_port = tk.StringVar(value="8888")
        ttk.Entry(top, textvariable=self.var_port, width=8).grid(row=0, column=3, padx=4)

        # 姓名（必填）
        ttk.Label(top, text="姓名:").grid(row=0, column=4, padx=(8, 4), sticky="e")
        self.var_name = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.var_name, width=12).grid(row=0, column=5, padx=4)

        # 工号
        ttk.Label(top, text="工号:").grid(row=0, column=6, padx=(8, 4), sticky="e")
        self.var_emp = tk.StringVar(value="")
        ttk.Entry(top, textvariable=self.var_emp, width=12).grid(row=0, column=7, padx=4)

        # 连接 / 断开按钮
        self.btn_conn = ttk.Button(top, text="连接", command=self._connect, style="Success.TButton")
        self.btn_conn.grid(row=0, column=8, padx=8, pady=6)
        self.btn_disconn = ttk.Button(top, text="断开", command=self._disconnect, state="disabled")
        self.btn_disconn.grid(row=0, column=9, padx=4)

        # 连接状态
        self.var_status = tk.StringVar(value="● 未连接")
        ttk.Label(top, textvariable=self.var_status, foreground="#16A34A").grid(row=0, column=10, padx=10)

        # 帮助 / 关于
        ttk.Button(top, text="使用帮助", command=lambda: show_help(self.parent, "sender")).grid(row=0, column=11, padx=(10, 4))
        ttk.Button(top, text="关于", command=lambda: show_about(self.parent)).grid(row=0, column=12, padx=4)

        # 第二行：接收目录提示
        ttk.Label(top, text="接收的文件保存在：%s" % self.receive_dir,
                  foreground="#6B7280").grid(row=1, column=0, columnspan=11, padx=10, pady=(0, 6), sticky="w")

        # ---- 中部：接收端下发的文件 ----
        recv = ttk.LabelFrame(self.parent, text="接收端下发的文件（双击可打开）")
        recv.pack(fill="both", expand=True, padx=8, pady=4)

        cols = ("time", "task", "filename", "size")
        self.tree = ttk.Treeview(recv, columns=cols, show="headings")
        self.tree.heading("time", text="时间")
        self.tree.heading("task", text="文件")
        self.tree.heading("filename", text="文件名")
        self.tree.heading("size", text="大小(KB)")
        self.tree.column("time", width=150)
        self.tree.column("task", width=160)
        self.tree.column("filename", width=240)
        self.tree.column("size", width=80)
        self.tree.pack(fill="both", expand=True, padx=6, pady=6)
        # 双击打开：在 tags 中保存了文件/文件夹路径
        self.tree.bind("<Double-1>", self._open_received)

        # ---- 提交队列（实时） ----
        qf = ttk.LabelFrame(self.parent, text="提交队列（实时）—— 同时提交时自动排队，一次上传一个")
        qf.pack(fill="x", padx=8, pady=4)

        qcols = ("pos", "name", "task", "status")
        self.queue_tree = ttk.Treeview(qf, columns=qcols, show="headings", height=4)
        self.queue_tree.heading("pos", text="排位")
        self.queue_tree.heading("name", text="发送者")
        self.queue_tree.heading("task", text="文件")
        self.queue_tree.heading("status", text="状态")
        self.queue_tree.column("pos", width=60, anchor="center")
        self.queue_tree.column("name", width=120)
        self.queue_tree.column("task", width=320)
        self.queue_tree.column("status", width=160, anchor="center")
        self.queue_tree.pack(fill="x", padx=6, pady=6)

        # ---- 提交文件区 ----
        submit = ttk.LabelFrame(self.parent, text="提交文件（单个文件 或 整个文件夹）")
        submit.pack(fill="x", padx=8, pady=4)

        # 文件名称（缺省为所选文件/文件夹名）
        ttk.Label(submit, text="文件名称:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.var_task = tk.StringVar(value="")
        ttk.Entry(submit, textvariable=self.var_task, width=30).grid(row=0, column=1, padx=6, pady=6, sticky="w")

        # 已选文件/文件夹展示
        ttk.Label(submit, text="文件:").grid(row=1, column=0, padx=6, pady=6, sticky="ne")
        self.var_file = tk.StringVar(value="（未选择文件）")
        ttk.Label(submit, textvariable=self.var_file, wraplength=380, justify="left").grid(row=1, column=1, columnspan=4, padx=6, pady=6, sticky="w")

        # 选择文件 / 选择文件夹 / 提交按钮
        ttk.Button(submit, text="选择文件", command=self._choose_file).grid(row=2, column=1, padx=6, pady=6, sticky="w")
        ttk.Button(submit, text="选择文件夹", command=self._choose_dir).grid(row=2, column=2, padx=6, pady=6, sticky="w")
        ttk.Button(submit, text="提交文件", command=self._do_submit, style="Accent.TButton").grid(row=2, column=3, padx=6, pady=6, sticky="w")

        # ---- 运行日志 ----
        logf = ttk.LabelFrame(self.parent, text="运行日志")
        logf.pack(fill="x", padx=8, pady=(0, 6))
        self.log = tk.Text(logf, height=6, state="disabled")
        self.log.pack(fill="x", padx=6, pady=6)

    # ================= 事件轮询（线程安全） =================
    def _poll_events(self):
        """从队列取出客户端事件并更新界面，由 after 周期调用。

        【设计思路】
        - 一次把所有可取出的事件取完（get_nowait 直到 queue.Empty）。
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
        - 事件分发器：客户端投递的事件在此一一对应到界面刷新动作。
        - 新增事件类型只需在此增加一个分支。
        """
        etype = ev.get("type")
        if etype == "connected":
            self._set_connected(True)
            self._log("已连接接收端 %s:%s" % (ev["host"], ev["port"]))
        elif etype == "disconnected":
            self._set_connected(False)
            self._log("已断开连接")
        elif etype == "task_received":
            # 收到接收端下发的文件/文件夹
            self._add_received(ev)
            self._log("收到接收端下发《%s》：%s" % (ev["task_name"], ev["filename"]))
        elif etype == "queued":
            # 已入队：记录当前排队位置
            self._log("已进入排队，当前排第 %s 位（共 %s 个）" % (ev["pos"], ev["queue_len"]))
        elif etype == "submit_sending":
            # 轮到了，正在上传
            self._log("轮到上传：正在发送《%s》…" % (ev.get("filename") or ev.get("task_name", "")))
        elif etype == "submit_done":
            # 接收端确认接收完成
            self._log("提交成功：%s" % ev.get("msg", ""))
        elif etype == "submit_req_sent":
            self._log("已提交《%s》，等待排队…" % ev.get("task_name", ""))
        elif etype == "submit_sent":
            self._log("文件夹《%s》全部文件已发送，等待接收端确认…" % ev.get("task_name", ""))
        elif etype == "queue_status":
            # 实时更新提交队列表格
            self._update_queue(ev.get("queue", []))
        elif etype == "error":
            messagebox.showerror("错误", ev.get("message", "未知错误"))
        elif etype == "ack":
            self._log("接收端回执：%s" % ev.get("msg", ev.get("status", "")))
        elif etype == "log":
            self._log(ev.get("text", ""))

    def _update_queue(self, queue):
        """刷新提交队列表格。

        【设计思路】
        - 先清空再重建；状态映射为中文；文件夹任务加"（文件夹）"标记。
        """
        self.queue_tree.delete(*self.queue_tree.get_children())
        status_map = {"waiting": "排队等待", "transferring": "正在上传"}
        for it in queue:
            task = it.get("task") or it.get("filename", "")
            if it.get("is_dir"):
                task += "（文件夹）"
            self.queue_tree.insert(
                "", "end",
                values=(it.get("pos", ""), it.get("name", ""), task,
                        status_map.get(it.get("status"), it.get("status", ""))),
            )

    # ================= 连接 =================
    def _load_config(self):
        """读取上次填写的 IP、姓名、工号、端口并自动回填。

        【设计思路】
        - 实现"上次填的内容下次自动带出"，无需每次重复填写。
        - 用真实值（如已有 IP）覆盖默认占位值。
        """
        saved_ip = self.config.get("conn", "ip")
        if saved_ip:
            self.var_ip.set(saved_ip)
        saved_port = self.config.get("conn", "port", "8888")
        if saved_port:
            self.var_port.set(saved_port)
        self.var_name.set(self.config.get("conn", "name", ""))
        self.var_emp.set(self.config.get("conn", "employee_id", ""))

    def _connect(self):
        """连接接收端。

        【设计思路】
        - 校验 IP 格式（IPv4 四段点分十进制）与端口范围。
        - 校验姓名必填。
        - 保存本次填写的 IP/端口/姓名/工号到 ini（下次自动回填）。
        - 创建 SenderClient 并 connect()。
        """
        ip = self.var_ip.get().strip()
        # IP 规则校验：必须是合法的 IPv4 四段点分十进制
        if not self._valid_ip(ip):
            messagebox.showerror("错误", "IP 地址格式不正确，应为 192.168.1.100 这类格式")
            return
        try:
            port = int(self.var_port.get().strip())
        except ValueError:
            messagebox.showerror("错误", "端口必须是数字")
            return
        if not (1 <= port <= 65535):
            messagebox.showerror("错误", "端口必须在 1-65535 之间")
            return
        if not self.var_name.get().strip():
            messagebox.showerror("错误", "请填写姓名")
            return

        # 保存本次填写的连接信息，下次启动自动回填
        self.config.set("conn", "ip", ip)
        self.config.set("conn", "port", str(port))
        self.config.set("conn", "name", self.var_name.get().strip())
        self.config.set("conn", "employee_id", self.var_emp.get().strip())
        self.config.save()

        # 创建客户端并连接；on_event 指向事件队列的 put（线程安全投递）
        self.client = SenderClient(ip, port, self.receive_dir, on_event=self.event_queue.put)
        if self.client.connect(self.var_name.get().strip(), self.var_emp.get().strip()):
            self._set_connected(True)
            self._log("连接成功：%s（工号 %s）" % (self.var_name.get().strip(), self.var_emp.get().strip()))
        else:
            self.client = None

    @staticmethod
    def _valid_ip(ip):
        """
        校验是否为合法的 IPv4 地址（四段点分十进制，每段 0-255）。

        【设计思路】
        - 必须正好 4 段，用 "." 分隔。
        - 每段必须是 0-255 的数字（且不能是空串）。
        - 满足以上条件才视为合法，否则提示用户输入格式错误。
        """
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        for p in parts:
            if not p or not p.isdigit():
                return False
            if not (0 <= int(p) <= 255):
                return False
        return True

    def _disconnect(self):
        """断开连接并复位界面状态。"""
        if self.client:
            self.client.disconnect()
            self.client = None
        self._set_connected(False)
        self._log("已断开连接")

    def _set_connected(self, on):
        """切换连接状态对应的按钮与状态文字。"""
        if on:
            self.btn_conn.config(state="disabled")
            self.btn_disconn.config(state="normal")
            self.var_status.set("● 已连接")
        else:
            self.btn_conn.config(state="normal")
            self.btn_disconn.config(state="disabled")
            self.var_status.set("● 未连接")

    # ================= 提交 =================
    def _choose_file(self):
        """选择要提交的单个文件。

        【设计思路】
        - 文件名称缺省为所选文件名（不含扩展名）；若用户已填写则保留。
        """
        path = filedialog.askopenfilename(title="选择要提交的文件")
        if path:
            self._submit_path = path
            self._submit_is_dir = False
            self.var_file.set(os.path.basename(path))
            if not self.var_task.get().strip():
                stem = os.path.splitext(os.path.basename(path))[0]
                self.var_task.set(stem)

    def _choose_dir(self):
        """选择要提交的整个文件夹（含其下所有子文件夹）。

        【设计思路】
        - 与选文件对称：置 _submit_is_dir=True，文件名缺省为文件夹名。
        - 真正的提交由 client_core.submit(is_dir=True) 完成。
        """
        path = filedialog.askdirectory(title="选择要提交的文件夹（含子文件夹）")
        if path:
            self._submit_path = path
            self._submit_is_dir = True
            self.var_file.set(os.path.basename(path) + "（文件夹）")
            if not self.var_task.get().strip():
                self.var_task.set(os.path.basename(path))

    def _do_submit(self):
        """提交文件（单个文件 或 整个文件夹）。

        【设计思路】
        - 校验：已连接、已填写文件名称、已选择提交内容。
        - 根据 _submit_is_dir 调用 client.submit(..., is_dir=True/False)。
        """
        if not self.client or not self.client.connected:
            messagebox.showwarning("提示", "请先连接到接收端")
            return
        task_name = self.var_task.get().strip()
        if not task_name:
            messagebox.showwarning("提示", "请填写文件名称")
            return
        if not self._submit_path:
            messagebox.showwarning("提示", "请先选择要提交的文件")
            return
        self.client.submit(os.path.basename(self._submit_path), self._submit_path,
                           task_name, is_dir=self._submit_is_dir)

    # ================= 界面辅助 =================
    def _add_received(self, ev):
        """向"接收端下发的文件"表格插入一条记录（tags 保存路径供双击打开）。"""
        size_kb = round(ev["size"] / 1024.0, 1)
        self.tree.insert("", 0, values=(ev["time"], ev["task_name"], ev["filename"], size_kb),
                         tags=(ev["path"],))

    def _open_received(self, _event):
        """双击记录：用系统默认程序打开对应文件/文件夹。"""
        item = self.tree.focus()
        if item:
            path = self.tree.item(item, "tags")[0]
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showerror("错误", "无法打开文件：%s" % e)

    def _log(self, text):
        """向运行日志区追加一行（只读）。"""
        self.log.config(state="normal")
        self.log.insert(tk.END, text + "\n")
        self.log.see(tk.END)
        self.log.config(state="disabled")

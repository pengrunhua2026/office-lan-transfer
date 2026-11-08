# -*- coding: utf-8 -*-
"""
发送端网络客户端核心模块
========================
【文件定位】本模块实现发送端与接收端的 TCP 通信，是"发送端"最核心的业务逻辑层。

【设计思路】
  1. 职责边界：
     本模块只负责连接、收发、提交等"核心逻辑"，不画界面；
     界面（sender_app.py）通过 on_event 回调接收本模块产生的事件并展示。
     这样"网络层与界面层解耦"，核心逻辑可脱离 GUI 单独测试（见 tests/）。

  2. 线程模型：
     - connect() 成功后在后台线程运行 _recv_loop，持续读取接收端消息。
     - tkinter 非线程安全，因此本模块不直接操作界面控件，
       而是把事件放入 on_event 回调，由 GUI 主线程用 after 轮询取出。

  3. 排队提交设计：
     - 提交不是立即上传，而是先向接收端发 submit_req 申请入队；
       接收端分配排队号并回 submit_queued，放行后才真正上传。
     - 客户端用 _pending_submit 记录待上传内容，收到 submit_go 后才发送，
       这样"排队位置"和"上传时机"都清晰可控。

  4. 文件夹提交设计：
     - 提交整个文件夹时，先用 _collect_files 递归收集所有文件及相对路径；
     - 放行后逐个文件发送 submit_data（头部带 rel_path/seq/file_count），
       全部发完再发 submit_done 通知接收端完成。

  5. 接收下发设计：
     - 接收端下发单个文件：收到 push_task 后按当天日期目录 + 版本号保存；
     - 接收端下发整个文件夹：收到 push_dir_start 时用 unique_dir_path 确定
       顶层目标目录（整体版本隔离）并存入 _pending_push；
       push_dir_data 按 rel_path 还原子目录结构写入；
       push_dir_done 时投递一条整体接收记录并清空 _pending_push。
"""
import os
import socket
import threading

from common.fileutil import dated_dir, unique_path, unique_dir_path
from common.protocol import Protocol


class SenderClient:
    """发送端 TCP 客户端，负责连接、收发文件。

    【设计思路】
    - 维护：socket、连接状态、待提交任务、待接收的文件夹下发状态。
    - 对外暴露：connect/disconnect（连接）、submit（提交）、
      以及 _handle 内部处理接收端消息。
    """

    def __init__(self, host, port, receive_dir, on_event=None):
        """
        :param host:        接收端 IP 地址
        :param port:        接收端端口
        :param receive_dir: 接收文件的本地保存目录
        :param on_event:    事件回调函数，接收一个 dict 事件
        """
        self.host = host
        self.port = port
        self.receive_dir = receive_dir
        self.on_event = on_event or (lambda e: None)   # 事件回调，缺省为空函数

        self.sock = None
        self.connected = False            # 是否已连接
        self._recv_thread = None          # 后台接收线程
        self._lock = threading.Lock()
        # 排队提交：记录待上传的文件信息，等接收端放行（submit_go）后再发送
        # 结构：{filename, path, task_name, is_dir, files}，files 为 [(相对路径, 绝对路径), ...]
        self._pending_submit = None
        # 正在接收的文件夹下发：记录顶层目标目录等，供 push_dir_data / push_dir_done 使用
        # 结构：{filename, task_name, folder_dir, file_count, total_size}
        self._pending_push = None

    # ---------- 事件推送辅助 ----------
    def _emit(self, etype, **kw):
        """构造事件字典并回调 GUI。

        【设计思路】
        - 与 ReceiverServer._emit 对称：把事件类型与参数打包成 dict 交回调。
        - 回调内部异常不影响网络线程，try/except 兜底。
        """
        ev = {"type": etype}
        ev.update(kw)
        try:
            self.on_event(ev)
        except Exception:
            pass

    # ---------- 连接与断开 ----------
    def connect(self, name, employee_id):
        """
        连接接收端并注册。

        【设计思路】
        - 创建 TCP socket，连接阶段设置 5 秒超时，避免界面长时间无响应；
          连接成功后再取消超时（settimeout(None)），后续由 recv 自行阻塞。
        - 连接成功后发送 register 消息注册姓名与工号。
        - 启动后台接收线程 _recv_loop，持续读取接收端消息。

        :return: 连接是否成功
        """
        if self.connected:
            return True   # 已连接，直接返回成功
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # 连接阶段设置超时，避免界面长时间无响应
            self.sock.settimeout(5)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)   # 连接成功后恢复阻塞模式
            self.connected = True

            # 发送注册消息（姓名 + 工号）
            Protocol.send_msg(self.sock, {
                "type": "register",
                "name": name,
                "employee_id": employee_id,
            })

            # 启动接收线程，等待接收端下发文件等消息
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            self._emit("connected", host=self.host, port=self.port)
            return True
        except Exception as e:
            # 连接失败：复位状态、关闭 socket、通知界面
            self.connected = False
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
            self._emit("error", message="连接失败：%s" % e)
            return False

    def disconnect(self):
        """主动断开与接收端的连接。

        【设计思路】
        - 复位连接标志并关闭 socket，_recv_loop 会因连接断开而自然退出。
        - 通知界面断开状态。
        """
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self._emit("disconnected")

    # ---------- 接收循环 ----------
    def _recv_loop(self):
        """后台线程：持续读取接收端消息，直到断开。

        【设计思路】
        - 循环 recv_msg；连接断开（ConnectionError/OSError）时 break。
        - 每收到一条消息调用 _handle 分派处理。
        - 循环因断开退出后，通知界面断开状态。
        """
        while self.connected:
            try:
                header, data = Protocol.recv_msg(self.sock)
            except (ConnectionError, OSError):
                break  # 连接断开
            self._handle(header, data)
        # 异常退出时通知 GUI 更新状态
        self._emit("disconnected")

    def _handle(self, header, data):
        """处理一条来自接收端的消息。

        【设计思路】
        - 按消息类型分派：
          - push_task        ：下发单个文件，保存到当天日期目录（同名加版本）；
          - push_dir_start   ：下发整个文件夹开始，确定顶层目标目录（整体版本隔离）；
          - push_dir_data    ：文件夹中单个文件，按 rel_path 还原子目录结构保存；
          - push_dir_done    ：文件夹下发完成，投递一条整体接收记录并清空状态；
          - ack              ：接收端回执（注册成功 / 提交确认）；
          - submit_queued    ：已入队，告知排队位置；
          - submit_go        ：轮到上传，开始发送文件内容；
          - queue_status     ：接收端广播的实时队列状态；
          - pong             ：心跳应答，无需处理。
        """
        mtype = header.get("type")

        if mtype == "push_task":
            # 接收者下发文件（单个文件）
            filename = os.path.basename(header.get("filename", "未命名"))
            task_name = header.get("task_name", "未命名文件")
            try:
                # 1. 先建立"当天日期"目录，不同日期的文件互不重叠
                today_dir = dated_dir(self.receive_dir)
                # 2. 若同名文件已存在，自动加版本号，不覆盖原文件
                path = unique_path(today_dir, filename)
                with open(path, "wb") as f:
                    f.write(data)
                # 通知界面：收到一个文件（插入列表，双击可打开）
                self._emit("task_received", task_name=task_name, filename=filename,
                           path=path, size=len(data), time=header.get("time", ""))
            except Exception as e:
                self._emit("error", message="保存文件失败：%s" % e)
        elif mtype == "push_dir_start":
            # 接收者下发整个文件夹：先准备顶层目标目录（整体版本隔离，保证文件夹版本一致）
            filename = os.path.basename(header.get("filename", "未命名"))
            task_name = header.get("task_name", "未命名文件")
            try:
                # 当天日期目录下，若顶层文件夹名已存在则自动加版本号 _v2，不覆盖原文件夹
                today_dir = dated_dir(self.receive_dir)
                folder_dir = unique_dir_path(today_dir, filename)
                # 记录本次下发文件夹的状态，供后续 push_dir_data/done 使用
                self._pending_push = {
                    "filename": filename,
                    "task_name": task_name,
                    "folder_dir": folder_dir,       # 顶层目标目录（整体版本隔离）
                    "file_count": header.get("file_count", 0),
                    "total_size": header.get("total_size", 0),
                }
            except Exception as e:
                self._pending_push = None
                self._emit("error", message="准备文件夹保存目录失败：%s" % e)
        elif mtype == "push_dir_data":
            # 接收者下发文件夹中的单个文件：按相对路径还原子目录结构后保存
            try:
                rel_path = header.get("rel_path", "")
                if self._pending_push:
                    folder_dir = self._pending_push["folder_dir"]
                    # 还原相对路径中的子目录层级（如 doc/images → folder_dir/doc/images）
                    rel_dir = os.path.dirname(rel_path)
                    target_dir = folder_dir if not rel_dir else os.path.join(folder_dir, rel_dir)
                    os.makedirs(target_dir, exist_ok=True)
                    fname = os.path.basename(rel_path) or header.get("filename", "未命名")
                    target = os.path.join(target_dir, fname)
                else:
                    # 异常顺序兜底：当作单个文件保存（按当天日期 + 版本号）
                    target = unique_path(dated_dir(self.receive_dir),
                                         os.path.basename(header.get("filename", "未命名")))
                with open(target, "wb") as f:
                    f.write(data)
                # 逐文件仅记日志，不逐条插入接收记录（避免文件夹刷屏）
                self._emit("log", text="正在接收下发文件夹的文件：%s" % (rel_path or target))
            except Exception as e:
                self._emit("error", message="保存下发文件失败：%s" % e)
        elif mtype == "push_dir_done":
            # 整个文件夹下发完成：投递一条记录（双击可打开顶层文件夹），并复位状态
            try:
                if self._pending_push:
                    p = self._pending_push
                    self._emit("task_received",
                               task_name=p["task_name"],
                               filename=p["filename"]
                               + "（文件夹，%d个文件）" % header.get("file_count", p.get("file_count", 0)),
                               path=p["folder_dir"],
                               size=p.get("total_size", 0),
                               time=header.get("time", ""))
                    self._pending_push = None   # 清空状态，准备接收下一个文件夹
            except Exception as e:
                self._emit("error", message="完成文件夹接收失败：%s" % e)
        elif mtype == "ack":
            # 接收端回执（注册成功 / 提交确认）
            status = header.get("status")
            msg = header.get("msg", "")
            if status == "ok" and ("接收" in msg or "提交" in msg):
                # 文件已被接收端接收，排队上传完成
                self._pending_submit = None
                self._emit("submit_done", msg=msg)
            else:
                self._emit("ack", status=status, msg=msg)
        elif mtype == "submit_queued":
            # 已加入排队：告知当前排队位置
            self._emit("queued", pos=header.get("queue_pos", 0),
                       queue_len=header.get("queue_len", 0))
        elif mtype == "submit_go":
            # 轮到了：接收端放行，开始发送文件内容
            self._send_pending_submit()
        elif mtype == "queue_status":
            # 接收端广播的实时队列状态
            self._emit("queue_status", queue=header.get("queue", []))
        elif mtype == "pong":
            pass  # 心跳应答，无需处理

    # ---------- 提交文件 ----------
    def submit(self, filename, path, task_name, is_dir=False):
        """
        提交文件（单个文件 或 整个文件夹）。

        【设计思路】
        - 先做前置校验：已连接、无排队中的任务、所选文件/文件夹存在。
        - 收集待上传内容：单文件或文件夹（_collect_files 递归收集相对路径）。
        - 记录到 _pending_submit，然后发送 submit_req（只带元数据、不带文件体）
          申请入队；接收端回 submit_queued 告知排队位置，放行后才真正上传。
        - 注意：submit_req 头里不放 filesize，避免接收端 recv_msg 误以为有
          文件体而阻塞等待，导致入队失败。

        :param filename:  显示名称（单文件=文件名；文件夹=顶层文件夹名）
        :param path:      本地文件路径 或 文件夹路径
        :param task_name: 文件名称
        :param is_dir:    是否提交整个文件夹
        :return: 是否成功发送提交请求
        """
        if not self.connected or not self.sock:
            self._emit("error", message="尚未连接到接收端")
            return False
        if self._pending_submit is not None:
            self._emit("error", message="您已有一个文件在排队，请等待其完成后再提交")
            return False

        # 收集待上传内容：单文件 或 文件夹（递归所有文件及相对路径）
        if is_dir:
            if not os.path.isdir(path):
                self._emit("error", message="所选文件夹不存在：%s" % path)
                return False
            files = self._collect_files(path)
            if not files:
                self._emit("error", message="文件夹中没有可提交的文件")
                return False
            file_count = len(files)
            total_size = sum(os.path.getsize(a) for _, a in files)
        else:
            if not os.path.isfile(path):
                self._emit("error", message="无法读取文件：%s" % path)
                return False
            files = [(None, path)]  # 单文件：无相对路径
            file_count = 1
            total_size = os.path.getsize(path)

        # 记录待上传任务，等接收端放行（submit_go）后再真正发送
        self._pending_submit = {
            "filename": filename, "path": path, "task_name": task_name,
            "is_dir": is_dir, "files": files,
        }
        try:
            # 注意：submit_req 只携带元数据、不带文件体，因此头里不放 filesize
            # （若放了 filesize，服务端 recv_msg 会误以为有文件体而阻塞等待，导致入队失败）
            header = {"type": "submit_req", "filename": filename, "task_name": task_name}
            if is_dir:
                header["is_dir"] = True          # 标记为文件夹任务
                header["file_count"] = file_count
                header["total_size"] = total_size
            Protocol.send_msg(self.sock, header)
            # 通知界面：已提交，正在排队
            self._emit("submit_req_sent", filename=filename, task_name=task_name, is_dir=is_dir)
            return True
        except Exception as e:
            self._pending_submit = None
            self._emit("error", message="提交请求发送失败：%s" % e)
            return False

    def _collect_files(self, root):
        """
        递归收集文件夹下所有文件的 (相对路径, 绝对路径) 列表。

        【设计思路】
        - 用 os.walk 递归遍历所有子目录。
        - 用 os.path.relpath 计算相对根目录的路径，并把分隔符统一为 "/"，
          保证跨平台传输时相对路径格式一致（与接收端 _collect_dir_files 对称）。
        """
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                abs_path = os.path.join(dirpath, fn)
                rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
                files.append((rel_path, abs_path))
        return files

    def _send_pending_submit(self):
        """
        被接收端放行后，开始上传待提交的内容。

        【设计思路】
        - 单文件：发送一条 submit_data（含文件体）。
        - 文件夹：逐个文件发送 submit_data（头部带相对路径 rel_path、序号 seq、
          文件总数 file_count），全部发完后发送 submit_done 通知接收端整个文件夹已完成。
        - 完成后不清空 _pending_submit，等接收端 ack 确认后再清，
          保证"提交成功"以接收端回执为准。
        """
        if not self._pending_submit:
            return
        p = self._pending_submit
        filename, task_name, is_dir = p["filename"], p["task_name"], p["is_dir"]

        if not is_dir:
            # ---- 单文件 ----
            _, filepath = p["files"][0]
            try:
                with open(filepath, "rb") as f:
                    data = f.read()
                Protocol.send_msg(self.sock, {
                    "type": "submit_data",
                    "filename": filename,
                    "task_name": task_name,
                    "filesize": len(data),
                }, data)
                self._emit("submit_sending", filename=filename, task_name=task_name, is_dir=False)
                # 不清空 _pending_submit，等接收端 ack 确认后再清
            except Exception as e:
                self._pending_submit = None
                self._emit("error", message="文件上传失败：%s" % e)
            return

        # ---- 文件夹：逐个文件上传 ----
        try:
            total = len(p["files"])
            for idx, (rel_path, abs_path) in enumerate(p["files"], start=1):
                with open(abs_path, "rb") as f:
                    data = f.read()
                Protocol.send_msg(self.sock, {
                    "type": "submit_data",
                    "filename": filename,      # 顶层文件夹名
                    "task_name": task_name,
                    "rel_path": rel_path,      # 当前文件在文件夹内的相对路径
                    "filesize": len(data),
                    "seq": idx,                # 第几个文件
                    "file_count": total,       # 文件总数
                }, data)
                self._emit("submit_sending", filename=rel_path, task_name=task_name,
                           is_dir=True, seq=idx, file_count=total)
            # 全部文件上传完毕，发送完成信号，通知接收端整个文件夹已完成
            Protocol.send_msg(self.sock, {
                "type": "submit_done", "filename": filename, "task_name": task_name,
            })
            self._emit("submit_sent", filename=filename, task_name=task_name, is_dir=True)
            # 等接收端 ack 确认后再清空 _pending_submit
        except Exception as e:
            self._pending_submit = None
            self._emit("error", message="文件夹上传失败：%s" % e)

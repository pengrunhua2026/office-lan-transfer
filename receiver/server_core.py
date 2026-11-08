# -*- coding: utf-8 -*-
"""
接收端网络服务核心模块
======================
【文件定位】本模块实现接收端的 TCP 服务端，是"接收端"最核心的业务逻辑层。

【设计思路】
  1. 职责边界：
     本模块只负责网络收发、文件保存与队列调度等"核心逻辑"，不画界面；
     界面（receiver_app.py）通过 on_event 回调接收本模块产生的事件并展示。
     这样"网络层与界面层解耦"，核心逻辑可脱离 GUI 单独测试（见 tests/）。

  2. 线程模型：
     - 服务端在"后台线程"中运行：一个 accept 线程循环接受连接；
       每个已连接客户端再开一个独立的 client_loop 线程处理其全部消息。
     - 由于 tkinter 非线程安全，本模块绝不直接操作界面控件，
       而是把事件放入 on_event 回调，由 GUI 主线程用 after 轮询取出。
     - 多个线程并发访问共享数据（clients 注册表、submit_queue 队列），
       用 threading.Lock 保护，避免竞态条件。

  3. 集中排队调度（应对并发提交）：
     多个发送者同时提交大文件会造成网络拥堵。因此所有提交先进入 submit_queue，
     同一时刻只放行队首一个（_transferring 标志），传完再放行下一个，
     并向所有客户端广播实时队列状态（queue_status），两端都能看到排队变化。

  4. 文件保存规则（与 common.fileutil 一致）：
     - 单个文件：save_dir / 当天日期 / 发送者姓名 / 文件名（同名加 _vN）；
     - 整个文件夹：save_dir / 当天日期 / 发送者姓名 / 顶层文件夹名（整体 _vN）
       然后按相对路径把内部文件写入对应子目录，保证目录结构原样保留。

  5. 下发方向（接收端 → 发送者）：
     - push_task：下发单个文件；
     - push_task_dir：下发整个文件夹——先发 push_dir_start 声明元数据，
       再逐个文件发 push_dir_data（头部带 rel_path 保留相对路径），
       最后发 push_dir_done 表示完成。
"""
import os
import socket
import threading
from datetime import datetime

from common.fileutil import dated_dir, unique_path, unique_dir_path
from common.protocol import Protocol


class ReceiverServer:
    """接收端 TCP 服务端，负责监听、收发与保存文件。

    【设计思路】
    - 本类维护：监听 socket、客户端注册表、姓名→地址映射、提交队列。
    - 对外暴露：start/stop（启停）、push_task/push_task_dir（下发）、
      online_senders（查询在线发送者），界面层只与这些方法交互。
    """

    def __init__(self, host, port, save_dir, on_event=None):
        """
        :param host:     监听地址，通常为 "0.0.0.0"（表示本机所有网卡）
        :param port:     监听端口，例如 8888
        :param save_dir: 接收文件的保存根目录
        :param on_event: 事件回调函数，接收一个 dict 事件
        """
        self.host = host
        self.port = port
        self.save_dir = save_dir
        self.on_event = on_event or (lambda e: None)   # 事件回调，缺省为空函数

        # 主监听 socket（start 时创建，stop 时关闭）
        self._server_sock = None
        # 服务是否在运行（用于控制后台线程循环退出）
        self.running = False
        # 线程锁，保护客户端注册表（多线程并发访问需加锁）
        self._lock = threading.Lock()
        # 客户端注册表：addr -> {sock, addr, name, employee_id, conn_time}
        self.clients = {}
        # 发送者姓名 -> 客户端地址 的映射，便于按姓名定向下发
        self._name_to_addr = {}

        # 提交队列（集中调度，避免多发送者同时上传大文件导致网络拥堵）：
        #   每项：{addr, name, task_name, filename, filesize, status}
        #   status: waiting(排队中) / transferring(正在上传)
        self.submit_queue = []
        self._transferring = False          # 是否有任务正在上传
        self._queue_lock = threading.Lock() # 保护提交队列的锁

        # 每个客户端 socket 一把发送锁。
        # 【设计思路】服务端存在多个线程（各客户端线程 + 全局广播/调度线程）
        #   会向"同一个客户端 socket"写入数据（如同时发 queue_status 和 submit_go）。
        #   若不加锁并发 sendall，字节会交错，接收端会解码失败（偶发通信错误）。
        #   故为每个 addr 维护一把锁，所有写该 socket 的操作先获取对应锁。
        self._send_locks = {}               # addr -> threading.Lock
        self._send_locks_lock = threading.Lock()  # 保护 _send_locks 字典

    # ---------- 事件推送辅助 ----------
    def _emit(self, event_type, **kw):
        """构造事件字典并回调 GUI。

        【设计思路】
        - 把事件类型与附带参数打包成 dict，交给 on_event 回调。
        - 回调可能由界面层实现；回调内部异常不应影响网络线程，故 try/except 兜底。
        """
        ev = {"type": event_type}
        ev.update(kw)
        try:
            self.on_event(ev)
        except Exception:
            pass

    def _send_to(self, addr, header, data=b""):
        """向指定客户端 socket 加锁发送一条消息。

        【设计思路】
        - 所有向客户端 socket 的写操作统一走本方法，先取该 addr 的发送锁再 sendall，
          保证"多线程并发写同一 socket"串行化，杜绝字节交错污染。
        - 发送失败（客户端已断开）时抛异常，由调用方决定如何兜底。
        """
        # 获取该 addr 对应的发送锁（首次访问时创建）
        with self._send_locks_lock:
            lock = self._send_locks.setdefault(addr, threading.Lock())
        with lock:
            sock = self.clients[addr]["sock"]
            Protocol.send_msg(sock, header, data)

    # ---------- 服务启停 ----------
    def start(self):
        """启动服务端：创建监听 socket，并在后台线程中接受连接。

        【设计思路】
        - 创建 TCP socket 并绑定端口、开启监听（listen(128)）。
        - SO_REUSEADDR 允许端口重用，避免程序重启后端口仍被占用。
        - 监听 socket 设 1 秒超时：accept 循环可周期性醒来检查停止标志，
          从而能在 stop() 时及时退出后台线程。
        - 成功启动后在后台线程跑 _accept_loop。
        """
        if self.running:
            return False   # 已在运行，防止重复启动
        try:
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # 允许地址重用，避免程序重启后端口仍被占用
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind((self.host, self.port))
            self._server_sock.listen(128)
            # 设置 1 秒超时，便于接受循环中周期性检查停止标志
            self._server_sock.settimeout(1.0)
            self.running = True
        except Exception as e:
            self._emit("error", message="启动服务失败：%s" % e)
            return False

        # 后台线程：循环接受连接（daemon=True，主程序退出时自动结束）
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        self._emit("server_started", host=self.host, port=self.port)
        return True

    def stop(self):
        """停止服务端：关闭监听 socket 与所有客户端连接。

        【设计思路】
        - 置 running=False，关闭监听 socket，让 accept 循环退出。
        - 关闭所有已连接的客户端 socket，并清空注册表与姓名映射。
        - 清空提交队列、复位上传标志，保证下次启动状态干净。
        """
        self.running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None
        # 关闭所有客户端连接，通知其断开
        with self._lock:
            for addr in list(self.clients.keys()):
                try:
                    self.clients[addr]["sock"].close()
                except Exception:
                    pass
            self.clients.clear()
            self._name_to_addr.clear()
        # 清空提交队列
        with self._queue_lock:
            self.submit_queue.clear()
            self._transferring = False
        # 清空发送锁映射（下次启动重新创建）
        with self._send_locks_lock:
            self._send_locks.clear()
        self._emit("server_stopped")

    # ---------- 接受连接 ----------
    def _accept_loop(self):
        """循环接受新连接，为每个客户端启动独立的处理线程。

        【设计思路】
        - while self.running 使循环可被 stop() 退出。
        - socket.timeout 超时则 continue 继续循环（检查是否要停止）；
          OSError 表示监听 socket 已关闭，直接 break。
        - 每个客户端独立线程，互不阻塞，可同时服务多个发送者。
        """
        while self.running:
            try:
                conn, addr = self._server_sock.accept()
            except socket.timeout:
                continue  # 超时则继续循环，检查是否要求停止
            except OSError:
                break  # 监听 socket 已被关闭
            # 每个客户端单独一个线程处理其全部消息
            t = threading.Thread(target=self._client_loop, args=(conn, addr), daemon=True)
            t.start()

    # ---------- 处理单个客户端 ----------
    def _client_loop(self, conn, addr):
        """
        处理一个发送者客户端的完整生命周期。

        【设计思路】
        - 循环接收该客户端的消息，根据 type 分派处理。
        - register：登记上线（同姓名旧连接先关闭，保证一人一连接）；
        - submit_req：加入提交队列、分配排队号、尝试调度；
        - submit_data：被放行后开始收文件（单文件或文件夹中的某个文件）；
        - submit_done：文件夹任务全部传完，确认完成并调度下一个；
        - ping：心跳保活，回 pong。
        - 断开（ConnectionError/OSError）时进入 finally 清理注册表，
          若该客户端正在上传或仍在队列中，将其移出并重新调度。
        """
        client_info = None
        try:
            while self.running:
                header, data = Protocol.recv_msg(conn)
                mtype = header.get("type", "")

                if mtype == "register":
                    # 发送者上线，登记注册信息（姓名、工号、连接时间）
                    client_info = {
                        "sock": conn,
                        "addr": addr,
                        "name": header.get("name", "未知"),
                        "employee_id": header.get("employee_id", ""),
                        "conn_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    with self._lock:
                        # 若同一姓名的发送者已在线，先关闭其旧连接
                        # （避免重复注册导致新连接被旧连接消息干扰）
                        old = self._name_to_addr.get(client_info["name"])
                        if old and old in self.clients:
                            try:
                                self.clients[old]["sock"].close()
                            except Exception:
                                pass
                            del self.clients[old]
                        self.clients[addr] = client_info
                        self._name_to_addr[client_info["name"]] = addr
                    # 通知界面：发送者上线
                    self._emit("client_connected",
                               addr="%s:%d" % (addr[0], addr[1]),
                               name=client_info["name"],
                               employee_id=client_info["employee_id"],
                               time=client_info["conn_time"])
                    # 发送注册成功回执（加锁发送，避免多线程写同一 socket 交错）
                    self._send_to(addr, {"type": "ack", "status": "ok", "msg": "已连接"})

                elif mtype == "submit_req":
                    # 发送者提交文件：先加入队列，分配排队号，等待调度放行
                    self._enqueue_submission(conn, addr, client_info, header)

                elif mtype == "submit_data":
                    # 被调度放行后，发送者才开始发送文件内容
                    self._receive_submission_data(conn, addr, client_info, header, data)

                elif mtype == "submit_done":
                    # 文件夹任务：发送者已传完所有文件，确认完成并调度下一个
                    self._finish_dir_submission(conn, addr, client_info)

                elif mtype == "ping":
                    # 心跳消息，回复 pong 以保持连接（加锁发送）
                    self._send_to(addr, {"type": "pong"})

                else:
                    # 未知消息类型，仅记日志（不影响服务运行）
                    self._emit("log", text="[%s:%d] 未知消息类型：%s" % (addr[0], addr[1], mtype))

        except (ConnectionError, OSError):
            pass  # 客户端断开连接
        finally:
            # 清理注册表并关闭连接
            with self._lock:
                if addr in self.clients:
                    info = self.clients.pop(addr)
                    if self._name_to_addr.get(info["name"]) == addr:
                        del self._name_to_addr[info["name"]]
            # 若该客户端正在上传或仍在队列中，将其移出并重新调度
            was_transferring = False
            with self._queue_lock:
                was_transferring = any(
                    it["addr"] == addr and it["status"] == "transferring"
                    for it in self.submit_queue)
                self.submit_queue = [it for it in self.submit_queue if it["addr"] != addr]
                if was_transferring:
                    self._transferring = False
            # 若正在上传的客户端断开，广播队列状态并调度下一个
            if was_transferring:
                self._broadcast_queue()
                self._schedule()
            try:
                conn.close()
            except Exception:
                pass
            if client_info:
                self._emit("client_left", name=client_info["name"],
                           addr="%s:%d" % (addr[0], addr[1]))

    # ---------- 保存文件 ----------
    def _save_submission(self, conn_addr, sender_name, task_name, filename, data):
        """
        保存发送者提交的文件（单个文件）。

        【设计思路】
        - 目录结构：save_dir / 当天日期 / 发送者姓名 / 文件名。
        - 按"当天日期"分文件夹，不同日期的文件互不重叠；
        - 同名文件自动追加版本号 _v2、_v3 ...，不覆盖原文件（unique_path）。
        - 保存成功后向该发送者回 ack("文件已接收")，并投递 submission 事件给界面。

        :param conn_addr: 发送者客户端的地址（用于定位发送锁与回执）
        """
        try:
            # 1. 先建立"当天日期"目录
            today_dir = dated_dir(self.save_dir)
            # 2. 再为发送者建立独立目录
            sender_dir = os.path.join(today_dir, sender_name)
            os.makedirs(sender_dir, exist_ok=True)
            # 3. 若同名文件已存在，自动加版本号
            target = unique_path(sender_dir, filename)

            # 4. 写入文件内容（二进制）
            with open(target, "wb") as f:
                f.write(data)

            # 5. 投递提交记录给界面（双击可打开）
            self._emit("submission",
                       sender=sender_name,
                       task_name=task_name,
                       filename=filename,
                       path=target,
                       size=len(data),
                       time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            # 6. 回执告知发送者已接收（加锁发送）
            self._send_to(conn_addr, {"type": "ack", "status": "ok", "msg": "文件已接收"})
        except Exception as e:
            # 保存失败：记日志并回 ack(error)，让发送者知道结果
            self._emit("error", message="保存文件失败：%s" % e)
            try:
                self._send_to(conn_addr, {"type": "ack", "status": "error", "msg": str(e)})
            except Exception:
                pass

    # ---------- 提交队列（集中调度） ----------
    def _enqueue_submission(self, conn, addr, client_info, header):
        """发送者发起提交请求：加入队列、分配排队号、广播状态，并尝试调度。

        【设计思路】
        - 提取文件名、文件名称、是否文件夹、大小、文件数等元数据。
        - 若该客户端已在队列中，直接拒绝重复提交（避免同一客户端排队多个任务）。
        - 否则加入队列（status=waiting），计算排队位置，回复 submit_queued，
          随后广播队列状态并尝试调度。
        """
        filename = os.path.basename(header.get("filename", "未命名"))
        task_name = header.get("task_name", "未命名文件")
        # 单文件用 filesize；文件夹用 total_size 作为展示的总大小
        is_dir = bool(header.get("is_dir", False))
        filesize = int(header.get("filesize", 0) or 0)
        if is_dir:
            filesize = int(header.get("total_size", 0) or 0)
        file_count = int(header.get("file_count", 0) or 0)
        name = client_info["name"] if client_info else header.get("name", "未知")
        with self._queue_lock:
            # 同一客户端已有任务在排队/上传时，拒绝新的提交请求
            if any(it["addr"] == addr for it in self.submit_queue):
                try:
                    self._send_to(addr, {"type": "ack", "status": "error",
                                         "msg": "您已有一个文件在排队，请等待其完成后再提交"})
                except Exception:
                    pass
                return
            # 加入队列，记录等待上传所需的状态（文件夹模式下记录接收计数与目标目录）
            self.submit_queue.append({
                "addr": addr, "name": name, "task_name": task_name,
                "filename": filename, "filesize": filesize, "status": "waiting",
                "is_dir": is_dir, "file_count": file_count,
                "received_count": 0,      # 文件夹模式下已接收的文件数
                "folder_dir": None,       # 文件夹模式下顶层目标目录（首次保存时确定）
            })
            pos = len(self.submit_queue)  # 排队位置 = 队列长度（当前追加到队尾）
        # 告知该发送者当前排队位置（加锁发送）
        try:
            self._send_to(addr, {"type": "submit_queued", "queue_pos": pos, "queue_len": pos})
        except Exception:
            pass
        self._broadcast_queue()   # 广播新队列状态给所有发送者与接收端界面
        self._schedule()          # 尝试调度（若队列空闲则放行队首）

    def _broadcast_queue(self):
        """把当前提交队列状态广播给所有发送者，并投递给接收端界面。

        【设计思路】
        - 生成一个只含展示字段的队列摘要（pos/name/task/filename/status/...），
          不暴露内部地址等细节，界面层直接使用。
        - 遍历所有在线客户端逐个发送 queue_status 消息；
          发送失败（已断开）的客户端跳过，不影响整体广播。
        """
        with self._queue_lock:
            q = [{"pos": i + 1, "name": it["name"], "task": it["task_name"],
                  "filename": it["filename"], "status": it["status"],
                  "is_dir": it.get("is_dir", False), "file_count": it.get("file_count", 0)}
                 for i, it in enumerate(self.submit_queue)]
            qmsg = {"type": "queue_status", "queue": q}
        with self._lock:
            addrs = list(self.clients.keys())
        # 逐个客户端广播（加锁发送，防止并发写同一 socket 交错）
        for a in addrs:
            try:
                self._send_to(a, qmsg)
            except Exception:
                pass
        # 同时投递给接收端界面（用于展示排队表格）
        self._emit("queue_status", queue=q)

    def _schedule(self):
        """调度队列：当前无上传进行时，放行队首发送者开始发送文件。

        【设计思路】
        - 若 _transferring 为 True（有任务正在上传）或队列为空，则什么都不做。
        - 否则取队首任务，置为 transferring，向该客户端发送 submit_go 放行。
        - 通知失败（客户端不可用）时，将其移出队列、复位标志、广播并递归调度，
          保证调度不会卡死。
        """
        with self._queue_lock:
            if self._transferring or not self.submit_queue:
                return   # 正在传输 或 队列为空，无需调度
            item = self.submit_queue[0]
            item["status"] = "transferring"
            self._transferring = True
            addr = item["addr"]
        try:
            self._send_to(addr, {"type": "submit_go"})
        except Exception as e:
            # 通知失败，视为该发送者不可用，跳过并调度下一个
            self._emit("log", text="通知 %s 开始上传失败：%s" % (addr, e))
            with self._queue_lock:
                self.submit_queue = [it for it in self.submit_queue if it["addr"] != addr]
                self._transferring = False
            self._broadcast_queue()
            self._schedule()   # 递归调度下一个
            return
        self._broadcast_queue()   # 广播更新后的状态（队首变为"正在上传"）

    def _receive_submission_data(self, conn, addr, client_info, header, data):
        """
        收到被放行发送者的实际文件。

        【设计思路】
        - 先定位该客户端当前正在传输（transferring）的任务；
          找不到（如状态异常）则忽略。
        - 单文件：保存后立即移出队列、复位标志、广播并调度下一个。
        - 文件夹：只保存当前这个文件（含相对路径子目录），累计 received_count，
          等待 submit_done 到达后统一完成（见 _finish_dir_submission）。
        """
        # 定位该客户端当前正在传输的任务
        item = None
        with self._queue_lock:
            for it in self.submit_queue:
                if it["addr"] == addr and it["status"] == "transferring":
                    item = it
                    break
        if item is None:
            return  # 没有正在传输的任务，忽略

        if item.get("is_dir"):
            # ---- 文件夹模式：保存当前文件，累计计数，等 submit_done ----
            item["received_count"] = item.get("received_count", 0) + 1
            self._save_dir_file(item, header, data)
            return

        # ---- 单文件模式：保存后立即完成 ----
        filename = os.path.basename(header.get("filename", "未命名"))
        task_name = header.get("task_name", "未命名文件")
        sender_name = item["name"]
        self._save_submission(addr, sender_name, task_name, filename, data)
        with self._queue_lock:
            self.submit_queue = [it for it in self.submit_queue if it["addr"] != addr]
            self._transferring = False
        self._broadcast_queue()
        self._schedule()

    def _save_dir_file(self, item, header, data):
        """
        保存文件夹模式下的单个文件（含子目录结构）。

        【设计思路】
        - 目录结构：save_dir / 当天日期 / 发送者姓名 / 顶层文件夹名 / 相对路径...
        - 顶层文件夹名若已存在同名目录，用 unique_dir_path 自动加版本号 _v2，
          且只在"首次收到该文件夹的第一个文件"时确定一次并缓存到 item["folder_dir"]，
          之后所有文件都写入同一个顶层目录——保证整个文件夹版本一致。
        - 文件夹内部的文件按相对路径（rel_path）还原子目录层级后写入，
          不再逐个加版本号（因为顶层目录已做整体版本隔离）。
        - 逐文件仅记日志，不逐条插入提交记录（避免一个文件夹刷屏）。
        """
        try:
            sender_name = item["name"]
            folder_name = item["filename"]
            rel_path = header.get("rel_path", "")

            # 1. 当天日期目录 → 发送者目录
            today_dir = dated_dir(self.save_dir)
            sender_dir = os.path.join(today_dir, sender_name)
            os.makedirs(sender_dir, exist_ok=True)

            # 2. 首次保存时确定顶层文件夹目录（同名自动加版本号，保证整个文件夹版本一致）
            if not item.get("folder_dir"):
                item["folder_dir"] = unique_dir_path(sender_dir, folder_name)
            target_dir = item["folder_dir"]

            # 3. 按相对路径还原子目录结构（如 doc/images → target_dir/doc/images）
            rel_dir = os.path.dirname(rel_path)
            if rel_dir:
                target_dir = os.path.join(target_dir, rel_dir)
            os.makedirs(target_dir, exist_ok=True)

            # 4. 写入文件内容（文件名取相对路径中的文件名）
            fname = os.path.basename(rel_path) or header.get("filename", "未命名")
            target = os.path.join(target_dir, fname)
            with open(target, "wb") as f:
                f.write(data)

            # 逐文件仅记日志，不逐条插入提交记录（避免一个文件夹刷屏）
            self._emit("log", text="[%s/%s] 已保存文件：%s"
                       % (sender_name, folder_name, rel_path or fname))
        except Exception as e:
            self._emit("error", message="保存文件夹文件失败：%s" % e)

    def _finish_dir_submission(self, conn, addr, client_info):
        """
        文件夹任务：发送者已传完所有文件（submit_done），确认完成并调度下一个。

        【设计思路】
        - 找到该客户端正在传输的任务，若不存在则忽略。
        - 向接收端投递"一条文件夹提交记录"（文件名带"（文件夹，n个文件）"，
          双击可打开顶层文件夹），避免逐文件刷屏。
        - 回 ack 告知发送者完成，然后移出队列、复位上传标志、广播并调度下一个。
        """
        item = None
        with self._queue_lock:
            for it in self.submit_queue:
                if it["addr"] == addr and it["status"] == "transferring":
                    item = it
                    break
        if item is None:
            return

        # 向接收端投递文件夹提交记录（双击可打开顶层文件夹）
        try:
            # 顶层目标目录：优先用已缓存的 folder_dir，否则兜底用日期/姓名目录
            folder_dir = item.get("folder_dir") or os.path.join(dated_dir(self.save_dir),
                                                                item["name"])
            self._emit("submission",
                       sender=item["name"],
                       task_name=item["task_name"],
                       filename=item["filename"] + "（文件夹，%d个文件）" % item["file_count"],
                       path=folder_dir,
                       size=item["filesize"],
                       time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            self._send_to(addr, {"type": "ack", "status": "ok", "msg": "文件已接收"})
        except Exception as e:
            self._emit("error", message="确认文件夹文件失败：%s" % e)

        # 完成：移出队列、复位上传标志、广播并调度下一个
        with self._queue_lock:
            self.submit_queue = [it for it in self.submit_queue if it["addr"] != addr]
            self._transferring = False
        self._broadcast_queue()
        self._schedule()

    # ---------- 下发文件 ----------
    def push_task(self, filename, filepath, task_name, targets=None):
        """
        向发送者下发文件（单个文件）。

        【设计思路】
        - 读取本地文件内容，向目标发送者发送 push_task 消息（含文件体）。
        - targets 为 None/空时表示发送给"全部在线发送者"；
          否则按姓名解析地址，只发给在线的目标。
        - 逐个客户端发送，发送成功的计数返回；失败仅记日志不中断。
        - 完成后投递 task_pushed 事件（含成功数）给界面展示。

        :param filename:  发送给发送端显示的文件名
        :param filepath:  本地待发送文件的路径
        :param task_name: 文件名称
        :param targets:   目标发送者姓名列表；为 None 或空时表示发送给全部在线发送者
        :return: 实际发送成功的发送者数量
        """
        if not os.path.isfile(filepath):
            self._emit("error", message="下发的文件不存在：%s" % filepath)
            return 0

        # 一次性读入文件内容（下发文件通常不大，内存可承受）
        with open(filepath, "rb") as f:
            data = f.read()

        with self._lock:
            # 确定目标客户端地址列表
            if targets:
                addrs = []
                for name in targets:
                    addr = self._name_to_addr.get(name)
                    if addr and addr in self.clients:
                        addrs.append(addr)   # 只对在线的目标发送
            else:
                addrs = list(self.clients.keys())   # 全部在线发送者

            sent = 0
            for addr in addrs:
                try:
                    # 发送单文件消息（头部 + 文件体，加锁发送）
                    self._send_to(addr, {
                        "type": "push_task",
                        "filename": filename,
                        "task_name": task_name,
                        "filesize": len(data),
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }, data)
                    sent += 1
                except Exception as e:
                    self._emit("log", text="向 %s 下发失败：%s" % (addr, e))

        # 投递下发结果给界面（成功数）
        self._emit("task_pushed", task_name=task_name, filename=filename,
                   count=sent, time=datetime.now().strftime("%H:%M:%S"))
        return sent

    def push_task_dir(self, filename, dirpath, task_name, targets=None):
        """
        向发送者下发整个文件夹（含其下所有子文件夹，原样保存目录结构）。

        【设计思路】
        - 流程分三步，与发送端（client_core）对称配合：
          1) push_dir_start：声明下发文件夹元数据（文件数、总大小），
             发送端据此用 unique_dir_path 确定顶层目标目录（整体版本隔离）；
          2) 逐个 push_dir_data：每个文件头部带 rel_path（相对路径），
             发送端据此还原子目录结构写入；
          3) push_dir_done：表示整个文件夹下发完成，发送端投递一条整体接收记录。
        - 先递归收集文件夹所有文件（_collect_dir_files），
          空目录/不存在时返回 0 并提示。
        - 逐个目标发送者执行上述三步，成功的计数返回。

        :param filename:  发送给发送端显示的文件夹名（顶层文件夹名）
        :param dirpath:   本地待下发文件夹的路径
        :param task_name: 文件名称
        :param targets:   目标发送者姓名列表；为 None 或空时表示发送给全部在线发送者
        :return: 实际发送成功的发送者数量
        """
        # 1. 校验文件夹并递归收集其下所有文件（相对路径 + 绝对路径）
        if not os.path.isdir(dirpath):
            self._emit("error", message="下发的文件夹不存在：%s" % dirpath)
            return 0
        files = self._collect_dir_files(dirpath)
        if not files:
            self._emit("error", message="文件夹中没有可下发的文件：%s" % dirpath)
            return 0
        file_count = len(files)
        total_size = sum(os.path.getsize(a) for _, a in files)

        with self._lock:
            # 2. 确定目标客户端地址列表（同 push_task）
            if targets:
                addrs = []
                for name in targets:
                    addr = self._name_to_addr.get(name)
                    if addr and addr in self.clients:
                        addrs.append(addr)
            else:
                addrs = list(self.clients.keys())

            sent = 0
            for addr in addrs:
                try:
                    # 3. 先声明下发文件夹（只带元数据，不带文件体；加锁发送）
                    self._send_to(addr, {
                        "type": "push_dir_start",
                        "filename": filename,
                        "task_name": task_name,
                        "file_count": file_count,
                        "total_size": total_size,
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    # 4. 逐个文件下发（头部带相对路径，发送端据此还原目录结构）
                    for idx, (rel_path, abs_path) in enumerate(files, start=1):
                        with open(abs_path, "rb") as f:
                            data = f.read()
                        self._send_to(addr, {
                            "type": "push_dir_data",
                            "filename": filename,
                            "task_name": task_name,
                            "rel_path": rel_path,   # 相对路径，保留子目录层级
                            "seq": idx,             # 第几个文件
                            "file_count": file_count,
                            "filesize": len(data),
                        }, data)
                    # 5. 发送完成信号，通知发送端整个文件夹已下发完
                    self._send_to(addr, {
                        "type": "push_dir_done",
                        "filename": filename,
                        "task_name": task_name,
                        "file_count": file_count,
                    })
                    sent += 1
                except Exception as e:
                    self._emit("log", text="向 %s 下发文件夹失败：%s" % (addr, e))

        # 投递下发结果给界面（文件名带"文件夹，n个文件"标记）
        self._emit("task_pushed", task_name=task_name,
                   filename=filename + "（文件夹，%d个文件）" % file_count,
                   count=sent, time=datetime.now().strftime("%H:%M:%S"))
        return sent

    def _collect_dir_files(self, root):
        """
        递归收集文件夹下所有文件的 (相对路径, 绝对路径) 列表。

        【设计思路】
        - 用 os.walk 递归遍历所有子目录。
        - 对每个文件，用 os.path.relpath 计算相对根目录的路径，并把分隔符
          统一为 "/"，保证跨平台传输时相对路径格式一致。
        - 返回的列表供 push_task_dir 逐文件原样下发。
        """
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                abs_path = os.path.join(dirpath, fn)
                rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
                files.append((rel_path, abs_path))
        return files

    # ---------- 查询 ----------
    def online_senders(self):
        """返回当前在线发送者姓名列表。

        【设计思路】
        - 从姓名→地址映射取键，供界面刷新"在线发送者"列表。
        - 加锁保护并发访问。
        """
        with self._lock:
            return list(self._name_to_addr.keys())

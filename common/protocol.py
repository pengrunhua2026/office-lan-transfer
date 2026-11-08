# -*- coding: utf-8 -*-
"""
局域网办公文件传输系统的通信协议模块
================================
【文件定位】本模块封装 TCP 通信的基础协议，供接收端服务端与发送端客户端共同调用。

【设计思路】
  1. 为什么需要自定义报文协议？
     TCP 是"字节流"协议，本身不区分消息边界——连续发送多条消息时，
     接收方无法判断一条消息从哪里开始、到哪里结束（粘包/半包问题）。
     因此必须定义一种"消息封装格式"，让收发双方按同一规则组装与解析。
  2. 报文格式设计：
        [ 4字节 头部长度 ] [ JSON头部字节 ] [ 文件二进制数据(可选) ]
     - 头部长度：4 字节大端序整数，标明 JSON 头部占多少字节，
       接收方先读 4 字节得知头部大小，再精确读取头部，从而定位消息边界。
     - JSON 头部：utf-8 的 JSON 字典，携带消息类型、文件名、大小等元信息，
       便于后续扩展字段而不影响协议。
     - 文件数据：当头部 filesize > 0 时，紧随头部发送完整文件内容。
  3. 为什么头部用 JSON？
     JSON 可读、可扩展、Python 原生支持（json.dumps/loads），
     非常适合描述"变长元信息"，新增字段不需要改协议版本。
  4. 为什么头部长度用大端序（>I）？
     网络字节序统一约定为大端（network byte order），
     保证跨平台、跨架构解析一致。
  5. recv_exact 的作用：
     TCP 单次 recv 不一定能读满想要的字节数（半包），
     因此循环读取直到取满 n 字节，这是正确处理 TCP 流的关键。

JSON 头部常用字段：
    type       消息类型
               register / submit_req / submit_data / submit_done / ack / ping / pong
               push_task（下发单个文件）
               push_dir_start / push_dir_data / push_dir_done（下发整个文件夹）
    name       发送者姓名
    employee_id 发送者工号
    filename   文件名（文件夹任务中为顶层文件夹名）
    filesize   文件大小（字节），无文件时为 0 或省略
    task_name  文件名称
    time       时间字符串
    status     状态（ok / error）
    msg        提示信息
    is_dir     是否为文件夹任务（提交方向）
    file_count 文件夹内的文件总数
    total_size 文件夹内文件的总大小（字节）
    rel_path   文件夹内当前文件的相对路径（含子目录，如 "doc/images/pic1.png"）
    seq        文件夹内当前文件序号（第几个文件）
"""
import json
import struct

# 头部长度字段占用的字节数（固定 4 字节）
HEADER_LEN_BYTES = 4


class Protocol:
    """报文发送与接收工具，全部为静态方法。

    【设计思路】
    - 全部做成静态方法，便于收发双方无状态调用（Protocol.send_msg / recv_msg），
      不依赖对象实例，语义清晰、调用简洁。
    """

    @staticmethod
    def send_msg(sock, header, data=b""):
        """
        向 socket 发送一条完整消息。

        【设计思路】
        - 按"长度 + 头部 + 文件体"三段发送，是接收方 recv_msg 的逆过程。
        - header 先序列化为 UTF-8 JSON，再在前面加 4 字节大端长度，
          接收方据此精确读到头部边界。
        - 文件数据可空（纯控制消息如 register / ping），此时只发头部。

        :param sock:   已连接的 socket 对象
        :param header: dict 类型的报文头部，会被序列化为 JSON
        :param data:   二进制文件内容，可为空字节串
        """
        # 1. 将头部字典序列化为 utf-8 编码的 JSON 字节
        #    ensure_ascii=False 保证中文正常编码为 UTF-8（而非 \uXXXX 转义）
        header_bytes = json.dumps(header, ensure_ascii=False).encode("utf-8")

        # 2. 先发送 4 字节的头部长度（大端序无符号整数）
        sock.sendall(struct.pack(">I", len(header_bytes)))

        # 3. 发送 JSON 头部
        sock.sendall(header_bytes)

        # 4. 若携带文件数据，则紧随其后发送
        if data:
            sock.sendall(data)

    @staticmethod
    def recv_exact(sock, n):
        """
        从 socket 中精确读取 n 个字节。

        【设计思路】
        - TCP 是流式协议，单次 recv 可能读不满 n 字节（半包），
          也可能一次读到多条消息（粘包）。本函数循环读取直到取满 n 字节，
          是解决"半包"问题的标准做法。
        - 若 recv 返回空字节，说明对端已关闭连接，抛出 ConnectionError。

        :param sock: 已连接的 socket 对象
        :param n:    需要读取的字节数
        :return:     读取到的二进制数据
        :raises ConnectionError: 连接已断开
        """
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))   # 只读取还缺的字节数
            if not chunk:                      # 空字节 = 连接被对端关闭
                raise ConnectionError("连接已断开")
            data += chunk
        return data

    @staticmethod
    def recv_msg(sock):
        """
        从 socket 中读取一条完整消息（头部 + 可选文件内容）。

        【设计思路】
        - 与 send_msg 完全对称：先读 4 字节头部长度，再精确读头部 JSON，
          最后按 filesize 读文件体。
        - 一次 recv_msg 保证读回"恰好一条完整消息"，上层无需关心 TCP 粘包。

        :param sock: 已连接的 socket 对象
        :return: (header, data) 二元组：
                 header: dict 类型的报文头部
                 data:   二进制文件内容（若头部 filesize > 0）
        :raises ConnectionError: 连接已断开
        """
        # 1. 读取 4 字节的头部长度，解包为大端无符号整数
        hlen = struct.unpack(">I", Protocol.recv_exact(sock, HEADER_LEN_BYTES))[0]

        # 2. 读取 JSON 头部并解析为字典
        header = json.loads(Protocol.recv_exact(sock, hlen).decode("utf-8"))

        # 3. 若头部声明有文件数据，则继续读取完整文件
        data = b""
        filesize = header.get("filesize", 0) or 0   # 兼容缺失/为0的情况
        if filesize > 0:
            data = Protocol.recv_exact(sock, filesize)

        return header, data

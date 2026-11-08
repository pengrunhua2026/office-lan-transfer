# -*- coding: utf-8 -*-
"""
排队机制集成测试
================
【设计思路】
- 用本地回环地址起一个真实 TCP 服务，三名发送者"无间隔并发"提交大文件，
  人为制造网络拥堵，验证集中排队调度：
    第 1 名直接放行上传；第 2、3 名收到排队号；前一名完成后再放行下一名。
- 断言关键点：服务端最终收到 3 个提交、保存 3 个文件、
  后提交者确实收到排队通知且队列曾发生积压（max_qlen >= 2）。

流程：
1. 启动接收端服务。
2. 三名发送者并发提交文件（20MB 级别用 2KB 模拟，验证流程即可）。
3. 验证：第 1 名发送者直接放行上传；第 2、3 名收到排队号（第 2、3 位）；
   前一名上传完成后再放行下一名；最终全部文件被接收。
"""
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from receiver.server_core import ReceiverServer
from sender.client_core import SenderClient

PORT = 18899
recv_root = tempfile.mkdtemp(prefix="qtest_")
server_evs = []
server = ReceiverServer("0.0.0.0", PORT, recv_root, on_event=lambda e: server_evs.append(e))
server.start()
time.sleep(0.5)


def make_file(name, size=2048):
    p = os.path.join(tempfile.gettempdir(), name)
    with open(p, "wb") as f:
        f.write(b"x" * size)
    return p


senders = []


def make_handler(nm):
    seq = []
    state = {"pos": 0}

    def h(e):
        seq.append(e["type"])
        if e["type"] == "queued":
            state["pos"] = e.get("pos")
            print("  [%s] 入队 排第 %s 位（共 %s 个）" % (nm, e.get("pos"), e.get("queue_len")), flush=True)
        if e["type"] == "submit_sending":
            print("  [%s] 轮到上传：发送文件…" % nm, flush=True)
        if e["type"] == "submit_done":
            print("  [%s] 提交成功：%s" % (nm, e.get("msg")), flush=True)
        if e["type"] == "error":
            print("  [%s] 错误：%s" % (nm, e.get("message")), flush=True)

    h.seq = seq
    return h, state


handlers = []
states = []
for i, nm in enumerate(["员工甲", "员工乙", "员工丙"], start=1):
    h, state = make_handler(nm)
    handlers.append(h)
    states.append(state)
    c = SenderClient("127.0.0.1", PORT, tempfile.gettempdir(), on_event=h)
    c.connect(nm, "E%03d" % i)
    senders.append(c)
time.sleep(0.5)

print(">>> 三名发送者同时提交 20MB 大文件")
for i, c in enumerate(senders):
    f = make_file("file_%d.txt" % i, 20 * 1024 * 1024)
    c.submit(os.path.basename(f), f, "文件%d" % i)
    # 无间隔并发提交，制造网络拥堵，验证排队

time.sleep(8)

# 服务端队列曾经达到的最大长度
max_qlen = 0
for e in server_evs:
    if e["type"] == "queue_status":
        max_qlen = max(max_qlen, len(e.get("queue", [])))

print("=== 各发送者事件序列 ===")
for nm, h in zip(["员工甲", "员工乙", "员工丙"], handlers):
    print("  %s: %s" % (nm, " -> ".join(h.seq)))
print("=== 服务端全部事件 ===")
for e in server_evs:
    print("  ", e.get("type"), e.get("msg", e.get("name", "")))
print("=== 服务端 submission 次数: %d" % sum(1 for e in server_evs if e["type"] == "submission"))
found = []
for root, _, files in os.walk(recv_root):
    for fn in files:
        found.append(os.path.basename(fn))
print("=== 接收文件: %s" % sorted(found))

# 断言
submissions = sum(1 for e in server_evs if e["type"] == "submission")
assert submissions == 3, "应收到 3 个提交，实际 %d" % submissions
assert len(found) == 3, "应保存 3 个文件，实际 %d" % len(found)
assert "queued" in handlers[1].seq, "员工乙未收到排队通知"
assert "submit_done" in handlers[1].seq, "员工乙未提交成功"
assert "submit_done" in handlers[2].seq, "员工丙未提交成功"
print("=== 服务端队列曾达到的最大长度: %d" % max_qlen)
assert max_qlen >= 2, "队列未发生积压（最大长度 %d），应 >=2 以证明排队机制生效" % max_qlen
# 至少有一个发送者排在第 2 位之后（证明后提交者确实在排队等待）
pos_list = [st["pos"] for st in states]
print("=== 各发送者最终排队位置: %s" % pos_list)
assert any(p >= 2 for p in pos_list), "没有发送者排在第2位之后，排队未生效: %s" % pos_list
server.stop()
print("\nQUEUE INTEGRATION TEST OK")

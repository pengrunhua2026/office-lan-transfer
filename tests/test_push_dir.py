# -*- coding: utf-8 -*-
"""
无界面集成测试：验证接收端下发整个文件夹（含子文件夹）到发送端。
不依赖 tkinter，可直接运行：  python tests/test_push_dir.py

【设计思路】
- 用本地回环地址起一个真实 TCP 服务，模拟"接收端 + 一名发送端"。
- 构造含多层子目录的测试文件夹，用 push_task_dir 下发，
  验证发送端按 日期/顶层文件夹名/相对路径 原样保存、子目录结构保留、
  文件内容一致，且文件夹只生成一条接收记录。
- 第二次下发同名文件夹，验证发送端自动加版本号 _v2，不覆盖原文件夹。

覆盖场景：
  1. 启动接收端服务，一名发送者连接并注册。
  2. 接收端下发一个含子目录、多个文件的文件夹。
  3. 发送端按 当天日期/顶层文件夹名/相对路径 原样保存，
     子目录结构保留、文件内容一致。
  4. 文件夹下发完成后发送端只生成一条接收记录（整体一条，不逐文件刷屏）。
  5. 接收端再次下发同名文件夹，发送端自动加版本号 _v2，不覆盖原文件夹。
"""
import os
import sys
import time
import shutil
from datetime import datetime

# 将项目根目录加入模块搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from receiver.server_core import ReceiverServer
from sender.client_core import SenderClient

TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_pushdir")
PORT = 18890
TODAY = datetime.now().strftime("%Y-%m-%d")


def wait_for(predicate, timeout=8):
    """轮询等待某个条件成立，避免网络异步导致测试不稳定。"""
    start = time.time()
    while time.time() - start < timeout:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def build_test_folder(root, name):
    """构造一个含子目录、多文件的测试文件夹，返回 (文件夹路径, {相对路径:内容})。"""
    folder = os.path.join(root, name)
    os.makedirs(os.path.join(folder, "方案", "附件"), exist_ok=True)
    os.makedirs(os.path.join(folder, "素材"), exist_ok=True)
    files = {
        "说明.txt": b"top readme",
        "方案/报告.md": b"report body",
        "方案/附件/图片1.png": b"\x89PNG-fake-content",
        "素材/演示.pptx": b"ppt-content",
    }
    for rel, content in files.items():
        with open(os.path.join(folder, rel), "wb") as f:
            f.write(content)
    return folder, files


def dir_record_count(events):
    """统计发送端收到的文件夹接收记录条数。"""
    return sum(1 for e in events if e.get("type") == "task_received"
               and "文件夹" in e.get("filename", ""))


def main():
    receive_dir = os.path.join(TEST_DIR, "received")
    push_dir = os.path.join(TEST_DIR, "push")
    snd_dir = os.path.join(TEST_DIR, "senders")
    os.makedirs(receive_dir, exist_ok=True)
    os.makedirs(push_dir, exist_ok=True)
    os.makedirs(snd_dir, exist_ok=True)

    events = {"server": [], "snd1": []}

    # 启动接收端服务
    server = ReceiverServer("127.0.0.1", PORT, receive_dir, on_event=events["server"].append)
    assert server.start(), "接收端服务启动失败"
    print("[OK] 接收端服务已启动")

    # 一名发送者连接并注册
    c1 = SenderClient("127.0.0.1", PORT, snd_dir, on_event=events["snd1"].append)
    assert c1.connect("员工甲", "E20260001"), "发送者连接失败"
    assert wait_for(lambda: len(server.online_senders()) >= 1)
    print("[OK] 发送者已连接并注册")

    # 构造测试文件夹并下发（push_task_dir）
    folder, files = build_test_folder(push_dir, "项目方案")
    sent = server.push_task_dir(os.path.basename(folder), folder, "项目方案资料")
    assert sent == 1, "应下发成功 1 名发送者，实际 %d" % sent

    # 等待发送端收到文件夹完成记录
    assert wait_for(lambda: dir_record_count(events["snd1"]) >= 1, timeout=10), \
        "发送端未收到文件夹完成记录"
    print("[OK] 发送端已收到文件夹完成记录")

    # 校验保存路径与原样内容
    saved_root = os.path.join(snd_dir, TODAY, "项目方案")
    assert os.path.isdir(saved_root), "发送端未按 日期/顶层文件夹名 保存"
    for rel, content in files.items():
        p = os.path.join(saved_root, rel)
        assert os.path.isfile(p), "缺少文件：%s" % rel
        with open(p, "rb") as f:
            assert f.read() == content, "文件内容不一致：%s" % rel
    print("[OK] 下发文件夹含子目录原样保存成功，共 %d 个文件内容一致" % len(files))

    # 接收记录只生成一条（文件夹整体一条，不逐文件刷屏）
    assert dir_record_count(events["snd1"]) == 1, \
        "文件夹应只生成一条接收记录，实际 %d" % dir_record_count(events["snd1"])
    print("[OK] 文件夹接收记录只有一条")

    # 再次下发同名文件夹 → 发送端自动加版本号 _v2，不覆盖原文件夹
    sent2 = server.push_task_dir(os.path.basename(folder), folder, "项目方案资料")
    assert sent2 == 1, "第二次下发应成功 1 名发送者"
    assert wait_for(lambda: dir_record_count(events["snd1"]) >= 2, timeout=10), \
        "第二次下发未完成"
    saved_root_v2 = os.path.join(snd_dir, TODAY, "项目方案_v2")
    assert wait_for(lambda: os.path.isdir(saved_root_v2)), "重复下发未生成 _v2 版本"
    assert os.path.isdir(os.path.join(saved_root_v2, "方案", "附件")), "_v2 目录未保留子目录结构"
    print("[OK] 重复下发同名文件夹自动保存为 _v2，不覆盖原文件夹")

    # 断开并停止
    c1.disconnect()
    server.stop()
    print("[OK] 文件夹下发测试全部通过")

    # 清理临时目录
    shutil.rmtree(TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()

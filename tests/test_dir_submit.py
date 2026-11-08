# -*- coding: utf-8 -*-
"""
无界面集成测试：验证发送端提交整个文件夹（含子文件夹）的传输与保存。
不依赖 tkinter，可直接运行：  python tests/test_dir_submit.py

【设计思路】
- 用本地回环地址起一个真实 TCP 服务，模拟"接收端 + 一名发送端"。
- 构造含多层子目录的测试文件夹，用 is_dir=True 提交，
  验证接收端按 日期/发送者/文件夹名/相对路径 原样保存、子目录结构保留、
  文件内容一致，且文件夹只生成一条提交记录。
- 第二次提交同名文件夹，验证接收端自动加版本号 _v2，不覆盖原文件夹。

覆盖场景：
  1. 启动接收端服务，一名发送者连接并注册。
  2. 发送端提交一个含子目录、多个文件的文件夹。
  3. 接收端按 当天日期/发送者姓名/顶层文件夹名/相对路径 原样保存，
     子目录结构保留、文件内容一致。
  4. 文件夹任务完成后提交记录只生成一条（整体一条，不逐文件刷屏）。
  5. 再次提交同名文件夹，接收端自动加版本号 _v2，不覆盖原文件夹。
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

TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp_dir")
PORT = 18889
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
    os.makedirs(os.path.join(folder, "doc", "images"), exist_ok=True)
    os.makedirs(os.path.join(folder, "code"), exist_ok=True)
    files = {
        "readme.txt": b"top readme",
        "doc/report.md": b"report body",
        "doc/images/pic1.png": b"\x89PNG-fake-content",
        "code/main.py": b"print('hi')",
    }
    for rel, content in files.items():
        with open(os.path.join(folder, rel), "wb") as f:
            f.write(content)
    return folder, files


def dir_record_count(events):
    """统计接收端收到的文件夹提交记录条数。"""
    return sum(1 for e in events if e.get("type") == "submission"
               and "文件夹" in e.get("filename", ""))


def main():
    receive_dir = os.path.join(TEST_DIR, "received")
    snd_dir = os.path.join(TEST_DIR, "senders")
    work = os.path.join(TEST_DIR, "work")
    os.makedirs(receive_dir, exist_ok=True)
    os.makedirs(snd_dir, exist_ok=True)
    os.makedirs(work, exist_ok=True)

    events = {"server": [], "snd1": []}

    # 启动接收端服务
    server = ReceiverServer("127.0.0.1", PORT, receive_dir, on_event=events["server"].append)
    assert server.start(), "接收端服务启动失败"
    print("[OK] 接收端服务已启动")

    # 一名发送者连接并注册
    c1 = SenderClient("127.0.0.1", PORT, snd_dir, on_event=events["snd1"].append)
    assert c1.connect("员工丙", "E20260003"), "发送者连接失败"
    assert wait_for(lambda: len(server.online_senders()) >= 1)
    print("[OK] 发送者已连接并注册")

    # 构造测试文件夹并提交（is_dir=True）
    folder, files = build_test_folder(work, "项目资料")
    assert c1.submit(os.path.basename(folder), folder, "季度资料", is_dir=True), "文件夹提交失败"

    # 等待接收端完成（出现文件夹提交记录）
    assert wait_for(lambda: dir_record_count(events["server"]) >= 1, timeout=10), \
        "接收端未收到文件夹完成记录"
    print("[OK] 接收端已收到文件夹完成记录")

    # 校验保存路径与原样内容
    saved_root = os.path.join(receive_dir, TODAY, "员工丙", "项目资料")
    assert os.path.isdir(saved_root), "接收端未按 日期/发送者/文件夹名 保存"
    for rel, content in files.items():
        p = os.path.join(saved_root, rel)
        assert os.path.isfile(p), "缺少文件：%s" % rel
        with open(p, "rb") as f:
            assert f.read() == content, "文件内容不一致：%s" % rel
    print("[OK] 文件夹含子目录原样保存成功，共 %d 个文件内容一致" % len(files))

    # 提交记录只生成一条（文件夹整体一条，不逐文件刷屏）
    assert dir_record_count(events["server"]) == 1, \
        "文件夹应只生成一条提交记录，实际 %d" % dir_record_count(events["server"])
    print("[OK] 文件夹提交记录只有一条")

    # 再次提交同名文件夹 → 接收端自动加版本号 _v2，不覆盖原文件夹
    assert c1.submit(os.path.basename(folder), folder, "季度资料", is_dir=True), "第二次文件夹提交失败"
    assert wait_for(lambda: dir_record_count(events["server"]) >= 2, timeout=10), "第二次文件夹未完成"
    saved_root_v2 = os.path.join(receive_dir, TODAY, "员工丙", "项目资料_v2")
    assert wait_for(lambda: os.path.isdir(saved_root_v2)), "重复提交未生成 _v2 版本"
    assert os.path.isdir(os.path.join(saved_root_v2, "doc", "images")), "_v2 目录未保留子目录结构"
    print("[OK] 重复提交同名文件夹自动保存为 _v2，不覆盖原文件夹")

    # 断开并停止
    c1.disconnect()
    server.stop()
    print("[OK] 文件夹上传测试全部通过")

    # 清理临时目录
    shutil.rmtree(TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
无界面集成测试：验证接收端服务端与发送端客户端的核心通信逻辑。
不依赖 tkinter，可直接运行：  python tests/test_integration.py

【设计思路】
- 本测试直接驱动 server_core / client_core（不经过 GUI），
  用本地回环地址 127.0.0.1 起一个真实 TCP 服务，模拟"接收端 + 两名发送端"，
  验证端到端的收发、保存、版本控制等核心流程。
- 由于网络是异步的，断言前用 wait_for 轮询等待事件/文件就绪，避免时序抖动。
- 覆盖"重复提交/下发同一文件自动 _v2 不覆盖""跨日期目录互不干扰"等关键规则。

覆盖场景：
  1. 启动接收端服务。
  2. 两个发送端客户端连接并注册。
  3. 接收端向全部发送者下发文件，发送端按当天日期目录保存。
  4. 发送端提交文件，接收端按当天日期目录保存。
  5. 重复发送/提交同一文件时，自动追加版本号 _v2，不覆盖原文件。
  6. 停止服务，断开连接。
"""
import os
import sys
import time
from datetime import datetime

# 将项目根目录加入模块搜索路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.fileutil import dated_dir, unique_path
from receiver.server_core import ReceiverServer
from sender.client_core import SenderClient

TEST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")
PORT = 18888
TODAY = datetime.now().strftime("%Y-%m-%d")


def wait_for(predicate, timeout=6):
    """轮询等待某个条件成立，避免网络异步导致测试不稳定。"""
    start = time.time()
    while time.time() - start < timeout:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def main():
    """集成测试主流程。

    【设计思路】
    - 依次验证：启动服务 → 两名发送者注册 → 下发文件到全部 → 重复下发自动 _v2
      → 发送者提交 → 重复提交自动 _v2 → unique_path 跨日期隔离单元验证 → 清理。
    - 每步成功后打印 [OK]，全部通过后在末尾打印总结果并清理临时目录。
    """
    # 准备临时目录
    receive_dir = os.path.join(TEST_DIR, "received")
    push_dir = os.path.join(TEST_DIR, "push")
    snd_dir = os.path.join(TEST_DIR, "senders")
    os.makedirs(receive_dir, exist_ok=True)
    os.makedirs(push_dir, exist_ok=True)
    os.makedirs(snd_dir, exist_ok=True)

    # 准备一个待下发的文件
    push_file = os.path.join(push_dir, "办公通知要求.txt")
    push_content = "请查收办公通知，本周五前反馈。".encode("utf-8")
    with open(push_file, "wb") as f:
        f.write(push_content)

    # 发送端各自接收目录
    snd1_dir = os.path.join(snd_dir, "snd1")
    snd2_dir = os.path.join(snd_dir, "snd2")
    os.makedirs(snd1_dir, exist_ok=True)
    os.makedirs(snd2_dir, exist_ok=True)

    events = {"server": [], "snd1": [], "snd2": []}

    # 启动接收端服务
    server = ReceiverServer("127.0.0.1", PORT, receive_dir, on_event=events["server"].append)
    assert server.start(), "接收端服务启动失败"
    print("[OK] 接收端服务已启动")

    # 两个发送端连接并注册
    c1 = SenderClient("127.0.0.1", PORT, snd1_dir, on_event=events["snd1"].append)
    c2 = SenderClient("127.0.0.1", PORT, snd2_dir, on_event=events["snd2"].append)
    assert c1.connect("员工甲", "E20260001"), "发送者1连接失败"
    assert c2.connect("员工乙", "E20260002"), "发送者2连接失败"
    assert wait_for(lambda: len(server.online_senders()) >= 2), "在线发送者数未达 2"
    print("[OK] 两名发送者已连接并注册：", server.online_senders())

    # 接收端向全部发送者下发文件
    sent = server.push_task(os.path.basename(push_file), push_file, "办公通知")
    assert sent == 2, "应下发成功 2 个发送者，实际 %d" % sent
    assert wait_for(lambda: any(e.get("type") == "task_received" for e in events["snd1"])), "发送者1未收到文件"
    assert wait_for(lambda: any(e.get("type") == "task_received" for e in events["snd2"])), "发送者2未收到文件"
    # 校验发送端按"当天日期"目录保存，且内容一致
    saved1 = os.path.join(snd1_dir, TODAY, os.path.basename(push_file))
    assert os.path.exists(saved1), "发送者1保存的文件不在当天日期目录中"
    with open(saved1, "rb") as f:
        assert f.read() == push_content, "发送者1收到的文件内容不一致"
    print("[OK] 接收端已向全部发送者下发文件，发送端按当天日期目录保存成功")

    # 接收端再次下发同一文件 → 发送端应自动生成 _v2，不覆盖
    sent2 = server.push_task(os.path.basename(push_file), push_file, "办公通知")
    assert sent2 == 2, "第二次下发应成功 2 个发送者"
    saved1_v2 = os.path.join(snd1_dir, TODAY, "办公通知要求_v2.txt")
    assert wait_for(lambda: os.path.exists(saved1_v2)), "发送端重复下发未生成 _v2 版本"
    print("[OK] 接收端重复下发同一文件，发送端自动保存为 _v2 版本：",
          os.path.basename(saved1_v2))

    # 发送者提交文件（第一次）
    sub_file = os.path.join(snd1_dir, "员工甲_办公反馈.docx")
    sub_content = ("员工甲提交的反馈文件内容...").encode("utf-8")
    with open(sub_file, "wb") as f:
        f.write(sub_content)
    assert c1.submit(os.path.basename(sub_file), sub_file, "办公反馈"), "发送者1提交失败"
    assert wait_for(lambda: any(e.get("type") == "submission" for e in events["server"])), "接收端未收到提交"
    # 校验接收端按"当天日期/发送者姓名"目录保存，且内容一致
    saved_sub = os.path.join(receive_dir, TODAY, "员工甲", os.path.basename(sub_file))
    assert os.path.exists(saved_sub), "接收端保存的文件不在当天日期/发送者目录中"
    with open(saved_sub, "rb") as f:
        assert f.read() == sub_content, "接收端保存的文件内容不一致"
    print("[OK] 发送者1已提交文件，接收端按当天日期/发送者目录保存成功：", saved_sub)

    # 发送者再次提交同一文件 → 接收端应自动生成 _v2，不覆盖
    assert c1.submit(os.path.basename(sub_file), sub_file, "办公反馈"), "发送者1第二次提交失败"
    saved_sub_v2 = os.path.join(receive_dir, TODAY, "员工甲", "员工甲_办公反馈_v2.docx")
    assert wait_for(lambda: os.path.exists(saved_sub_v2)), "接收端重复接收未生成 _v2 版本"
    print("[OK] 发送者重复提交同一文件，接收端自动保存为 _v2 版本：",
          os.path.basename(saved_sub_v2))

    # 单元验证 unique_path：跨日期目录互不干扰
    d1 = dated_dir(receive_dir, "2026-10-24")
    d2 = dated_dir(receive_dir, "2026-10-25")
    p1 = unique_path(d1, "a.txt")
    with open(p1, "w") as f:
        f.write("x")
    p2 = unique_path(d2, "a.txt")  # 不同日期目录，同名不冲突
    assert p2 != p1 and os.path.basename(p2) == "a.txt", "不同日期目录应互不冲突"
    p1_v2 = unique_path(d1, "a.txt")  # 同目录第二次，应加版本号
    assert os.path.basename(p1_v2) == "a_v2.txt", "同目录重复保存应加版本号"
    print("[OK] unique_path 版本号与跨日期隔离单元验证通过")

    # 断开并停止
    c1.disconnect()
    c2.disconnect()
    server.stop()
    print("[OK] 全部测试通过")

    # 清理临时目录
    import shutil
    shutil.rmtree(TEST_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
局域网办公文件传输系统（合并主程序）
====================================
【文件定位】本文件是整个程序的入口，负责把"文件接收端"与"文件发送端"
两个功能模块合并到同一个窗口的两个标签页（Tab）中。

【设计思路】
  1. 为什么合并成一个程序？
     早期版本接收端与发送端是各自独立的程序，使用者需要分别启动、分别维护。
     考虑到同一局域网内一台电脑既可能要"接收"也要"发送"，合并成单程序、双 Tab
     能显著降低使用门槛——只需启动一个 exe，即可切换两种角色。
  2. 如何合并？
     两个功能模块（ReceiverApp / SenderApp）都支持传入一个 container 参数：
       - 传入 ttk.Frame 时，界面构建到该容器内（被合并程序嵌入到 tab 中）；
       - 不传时，各自作为独立窗口运行（保留独立启动能力）。
     主程序正是利用这个设计，把两个模块分别装进两个 Tab 容器。
  3. 线程模型：
     GUI 主线程负责绘制与交互，网络逻辑由两个模块各自的后台线程负责，
     二者通过"事件队列 + after 轮询"解耦（tkinter 非线程安全，后台线程不能直接操作界面）。
  4. 统一的界面风格：
     通过 common.app_style 为窗口应用统一的配色、字体、头栏与底栏，
     保证接收端与发送端在同一个窗口内视觉一致。

运行方式（在项目根目录下）：
  python main.py
"""
import tkinter as tk
from tkinter import ttk

from common import app_style
from common.help_dialog import APP_VERSION, DEVELOPER
from sender.sender_app import SenderApp
from receiver.receiver_app import ReceiverApp


class MainApp:
    """局域网办公文件传输系统主窗口：双 Tab 承载文件接收端与文件发送端。

    【设计思路】
    - 本类只负责"窗口 + 双 Tab 容器"的组装，不写任何业务逻辑。
    - 具体的接收、发送、网络处理全部下沉到 ReceiverApp / SenderApp 两个模块，
      体现"高内聚、低耦合"：主窗口只做装配，功能模块各自独立可测。
    - 通过 container 参数把两个模块嵌入 Tab，复用其"可独立运行"的能力。
    """

    def __init__(self, root):
        # root：顶层 Tk 根窗口，整个程序唯一的窗口实例
        self.root = root
        self.root.title("局域网办公文件传输系统")
        self.root.geometry("1100x800")   # 初始窗口尺寸（宽 x 高）
        self.root.minsize(960, 680)      # 最小窗口尺寸，防止界面被压缩变形

        # 应用统一界面风格与窗口图标
        self.style = app_style.apply_style(root)
        app_style.set_window_icon(root, "combined.ico")

        # 顶部标题栏 + 底部开发者信息栏（统一风格，由公共模块绘制）
        app_style.add_header(root, "局域网办公文件传输系统",
                             subtitle="同一局域网文件接收与发送")
        app_style.add_footer(root, "开发者：%s    版本 v%s    局域网办公文件传输系统"
                              % (DEVELOPER, APP_VERSION))

        # 双 Tab 容器：ttk.Notebook 提供标签页切换能力
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=6)

        # 分别创建"文件接收端""文件发送端"两个标签页 Frame
        self.tab_recv = ttk.Frame(self.notebook)
        self.tab_send = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_recv, text="文件接收端")
        self.notebook.add(self.tab_send, text="文件发送端")

        # 两个功能模块构建到各自 tab 容器中（各自维护自己的事件轮询循环）
        self.receiver = ReceiverApp(root, container=self.tab_recv)
        self.sender = SenderApp(root, container=self.tab_send)


def main():
    """程序入口：创建主窗口并进入 tkinter 主事件循环。

    【设计思路】
    - tkinter 采用"单事件循环"模型：root.mainloop() 会一直运行，
      监听鼠标、键盘、窗口事件以及 after() 注册的周期任务，
      直到用户关闭窗口才返回。因此界面线程 = 主线程 = 唯一操作界面的线程。
    - 网络等耗时逻辑必须在后台线程运行，并通过事件队列回传结果。
    """
    root = tk.Tk()
    MainApp(root)          # 组装窗口与双 Tab
    root.mainloop()        # 启动 GUI 主事件循环，阻塞直到窗口关闭


# 保证只有直接运行本文件时才执行 main()，
# 被 import 时不会意外启动程序（便于测试与二次开发）
if __name__ == "__main__":
    main()

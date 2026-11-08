# -*- coding: utf-8 -*-
"""
帮助与关于对话框
================
【文件定位】提供"中文使用说明"对话框（接收端 / 发送端分别给出对应说明）
与"关于"对话框（软件信息）。

【设计思路】
  1. 为什么把说明文字集中到这里？
     使用说明作为长文本常量（RECEIVER_HELP / SENDER_HELP）集中放在本模块，
     界面层只需调用 show_help(parent, mode) 即可弹出，无需在界面代码里
     维护大段文字，便于统一维护与改版。
  2. 软件通用信息集中定义：
     APP_NAME / APP_VERSION / DEVELOPER / COPYRIGHT 等作为全局常量，
     界面、帮助、关于对话框统一引用，改版本时只改一处。
  3. 两个对话框统一使用 Toplevel 独立子窗口：
     - 通过 win.transient(parent) 让子窗口依附于父窗口（最小化父窗时一起隐藏）；
     - win.grab_set() 设为模态，用户在关闭前无法操作父窗口，
       保证说明阅读的专注性。
"""

# ---------------- 导入 ----------------
import tkinter as tk
from tkinter import ttk

from common.app_style import COLOR, FONT

# 软件通用信息（全局常量，供界面/帮助/关于统一引用）
APP_NAME = "局域网办公文件传输系统"
APP_VERSION = "2.1.0"
DEVELOPER = "prh"
COPYRIGHT = "Copyright (C) 2026 prh"

# 接收端使用说明（中文长文本常量，供"使用帮助"对话框展示）
RECEIVER_HELP = """【接收端使用说明】

一、启动服务
  1. 窗口顶部显示本机局域网 IP，端口默认 8888（可修改）。
  2. 点击「启动服务」，等待发送者连接。
  3. 请确保电脑防火墙放行该 TCP 端口，否则发送者无法连接。

二、查看发送者
  · 左侧「在线发送者」实时显示已连接的发送者，Ctrl/Shift 可多选。

三、下发文件
  1. 在右侧「下发文件」选择要下发的内容：
     · 下发单个文件：点击「选择文件」选择本地文件；
     · 下发整个文件夹：点击「选择文件夹」，连同其下所有子文件夹一并原样下发。
     文件名称会自动填写为所选文件/文件夹名（可再修改）。
  2. 点击「发送给全部发送者」，或先在左侧选中发送者再点「发送给选中发送者」。

四、接收目录定制
  · 顶部「接收目录」显示文件保存位置，点「浏览…」可自定义为任意文件夹。
  · 收到的文件按 日期/发送者名 自动分目录保存。

五、管理文件
  · 下方「提交记录」实时显示发送者提交的文件，双击可打开；
    发送者提交的是文件夹时，会显示"（文件夹，n个文件）"，双击可打开该文件夹。
  · 点击顶部「打开文件目录」可查看全部已收到的文件。

六、文件保存位置
  · 收到的文件保存在「接收目录」（默认 exe 所在目录下的
    receiver_data\\received\\）中的 日期/发送者名/ 子目录里。
  · 发送者提交文件夹时，按 日期/发送者名/文件夹名/ 原样保存，
    内部子文件夹结构一并保留，双击该记录可打开文件夹。
"""

# 发送端使用说明（中文长文本常量，供"使用帮助"对话框展示）
SENDER_HELP = """【发送端使用说明】

一、连接接收端（无需注册账号）
  1. 向接收端获取其 IP 地址。
  2. 在「接收端IP」处填写该 IP，端口默认 8888（与接收端一致）。
  3. 填写姓名、工号，点击「连接」即可。

二、接收文件
  · 接收端下发文件后，会自动显示在「接收端下发的文件」列表中，
    双击可打开查看。文件保存在 exe 所在目录下的 sender_data\\received\\。
  · 接收端下发整个文件夹时，会显示"（文件夹，n个文件）"，
    双击可打开该文件夹；文件夹连同其下所有子文件夹一并原样保存。

三、提交文件
  1. 在下方「提交文件」选择要提交的内容：
     · 提交单个文件：点击「选择文件」选择本地文件；
     · 提交整个文件夹：点击「选择文件夹」，连同其下所有子文件夹一并原样上传。
     文件名称会自动填写为所选文件/文件夹名（可再修改）。
  2. 点击「提交文件」，稍等片刻接收端确认后即完成。

四、注意事项
  · 需与接收端处于同一局域网。
  · 若提示「连接失败」，请检查 IP 是否正确、接收端是否已启动服务。
"""


def _scrolled_text(parent, text, height):
    """带滚动条、只读的文本区。

    【设计思路】
    - 用于展示较长说明文字，右侧带垂直滚动条。
    - 插入文本后设为只读（state="disabled"），防止用户误改说明内容。
    :return: 包含文本区的 Frame
    """
    frame = ttk.Frame(parent)
    frame.pack(fill="both", expand=True, padx=14, pady=6)
    # 多行文本控件：自动换行、白底、无边框
    txt = tk.Text(frame, wrap="word", height=height, font=FONT["normal"],
                  bg=COLOR["card"], fg=COLOR["text"],
                  relief="flat", padx=10, pady=10, borderwidth=0)
    # 滚动条与文本区联动
    sb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    txt.insert("1.0", text)          # 把说明文本写入控件
    txt.config(state="disabled")     # 设为只读，防止编辑
    return frame


def show_help(parent, mode):
    """
    打开中文使用说明对话框。

    【设计思路】
    - 根据 mode 选择展示接收端或发送端的说明文本。
    - 独立 Toplevel 子窗口 + 模态（grab_set），阅读时不会被主窗口干扰。

    :param parent: 父窗口
    :param mode:   'receiver'（接收端）或 'sender'（发送端），分别显示对应说明
    """
    # 创建独立子窗口并设置尺寸、最小尺寸、依附父窗口
    win = tk.Toplevel(parent)
    win.title("使用说明")
    win.geometry("620x560")
    win.minsize(560, 480)
    win.transient(parent)            # 依附父窗口（随父窗最小化而隐藏）
    win.configure(bg=COLOR["bg"])

    # 顶部标题（主色蓝底白字，与全局风格一致）
    tk.Label(win, text="使用说明", bg=COLOR["primary"], fg="white",
             font=FONT["title"]).pack(fill="x", pady=(0, 8), ipady=10)

    # 按 mode 选择对应说明文本，放入带滚动条的只读文本区
    body = RECEIVER_HELP if mode in ("receiver", "receiver") else SENDER_HELP
    _scrolled_text(win, body, height=24)

    # 关闭按钮
    ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(4, 12))
    win.grab_set()    # 模态：阻塞父窗口操作，直到关闭
    win.focus_set()   # 聚焦到说明窗口


def show_about(parent):
    """打开"关于"对话框，显示开发者信息与版本。

    【设计思路】
    - 用两列标签（键 + 值）展示软件名、版本、开发者、场景、技术、版权。
    - 与使用说明类似的模态子窗口，保证展示专注。
    """
    # 创建独立子窗口，固定尺寸不可缩放
    win = tk.Toplevel(parent)
    win.title("关于")
    win.geometry("360x300")
    win.resizable(False, False)
    win.transient(parent)
    win.configure(bg=COLOR["bg"])

    # 顶部软件名（主色底）
    tk.Label(win, text=APP_NAME, bg=COLOR["primary"], fg="white",
             font=FONT["title"]).pack(fill="x", ipady=12)

    # 信息区：两列布局（键 加粗 / 值 普通）
    info = ttk.Frame(win, padding=20)
    info.pack(fill="both", expand=True)
    rows = [
        ("软件名称", APP_NAME),
        ("版本", APP_VERSION),
        ("开发者", DEVELOPER),
        ("适用场景", "同一局域网内的文件接收与发送"),
        ("技术", "Python · tkinter · TCP Socket"),
        ("版权", COPYRIGHT),
    ]
    # 逐行生成键值对标签
    for i, (k, v) in enumerate(rows):
        ttk.Label(info, text=k, font=FONT["section"], background=COLOR["bg"]).grid(
            row=i, column=0, sticky="w", pady=3)
        # wraplength 限制换行宽度，避免长文本撑开窗口
        ttk.Label(info, text=v, background=COLOR["bg"], wraplength=210).grid(
            row=i, column=1, sticky="w", pady=3, padx=(12, 0))

    # 关闭按钮
    ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 12))
    win.grab_set()    # 模态
    win.focus_set()

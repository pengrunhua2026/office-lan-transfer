# -*- coding: utf-8 -*-
"""
界面样式与通用辅助
==================
【文件定位】本模块集中管理整个程序的外观（配色、字体、控件样式）与
通用界面辅助能力（头栏、底栏、资源路径解析、窗口图标设置）。

【设计思路】
  1. 为什么把样式集中到一个模块？
     接收端与发送端共用同一套界面风格。若各自写死颜色与字体，会导致
     两处不一致、后续难以统一调整。把所有样式常量（COLOR / FONT）和
     样式应用逻辑集中到本模块，做到"一处定义、全局生效"，
     修改主题时只需改动这一个文件。
  2. 控件样式如何应用？
     使用 ttk 的 Style 机制，为不同控件注册具名样式（如 Accent.TButton /
     Success.TButton），界面层按需引用样式名即可，避免重复设置属性。
  3. 资源路径与图标：
     - 源码运行时，资源（如 combined.ico）位于模块同目录；
     - 打包为 exe 时，PyInstaller 会把资源解压到临时目录 sys._MEIPASS，
       因此必须用 resource_path() 统一解析，保证两种运行方式下都能找到资源。
  4. 头栏/底栏：
     头栏显示软件名与副标题，底栏显示开发者与版本，两者固定高度，
     使窗口结构稳定、风格统一。
"""
import os
import sys
import tkinter as tk
from tkinter import ttk

# ---------------- 全局配色 ----------------
# 用字典集中定义颜色，界面各组件按语义引用（如 COLOR["primary"]），
# 便于统一更换主题色。
COLOR = {
    "primary": "#2563EB",      # 主色（蓝）：接收端/主要操作
    "primary_dark": "#1D4ED8",  # 主色深：按钮按下/悬停状态
    "green": "#16A34A",         # 成功/发送端主题（绿）
    "green_dark": "#15803D",
    "bg": "#F5F7FA",            # 页面背景（浅灰）
    "card": "#FFFFFF",          # 卡片/输入框背景（白）
    "text": "#1F2937",          # 正文文字（深灰）
    "muted": "#6B7280",         # 次要文字（灰）
    "border": "#E5E7EB",        # 边框（浅灰）
    "heading_bg": "#EEF2F7",    # 表头背景
    "header_fg": "#FFFFFF",     # 标题栏文字（白）
}

# ---------------- 全局字体 ----------------
# 集中定义各类文本的字体，界面按语义引用，保证字号、字重统一。
FONT = {
    "title": ("Microsoft YaHei UI", 15, "bold"),   # 标题
    "section": ("Microsoft YaHei UI", 11, "bold"), # 分组标题
    "normal": ("Microsoft YaHei UI", 10),          # 正文
    "small": ("Microsoft YaHei UI", 9),            # 小字/辅助
    "muted": ("Microsoft YaHei UI", 9),            # 次要文字
}


def resource_path(rel):
    """
    解析打包后资源文件的绝对路径。

    【设计思路】
    - 打包为 exe 时，PyInstaller 会把 --add-data 指定的资源解压到
      临时目录 sys._MEIPASS（仅存在于 frozen 状态）。
    - 直接运行源码时，资源与模块在同一目录。
    - 本函数统一处理这两种情况，界面层无需关心当前是否打包。

    :param rel: 资源相对路径，如 "combined.ico"
    :return: 资源的绝对路径
    """
    if getattr(sys, "frozen", False):
        # frozen 为 True 表示运行的是打包后的 exe
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    else:
        # 源码运行：资源在模块所在目录
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)


def set_window_icon(root, icon_name):
    """为窗口设置图标（打包时图标已通过 --add-data 内置）。

    【设计思路】
    - 用 try/except 包裹：图标设置失败（例如图标文件缺失）不影响程序正常运行，
      属于"尽力而为"的非关键步骤。
    :param root:      顶层 Tk 窗口
    :param icon_name: 图标文件名（相对资源目录）
    """
    try:
        path = resource_path(icon_name)
        if os.path.isfile(path):
            root.iconbitmap(path)
    except Exception:
        pass  # 图标设置失败不影响程序运行


def apply_style(root):
    """
    为窗口应用统一的现代风格。

    【设计思路】
    - ttk 的样式通过 Style 对象统一管理。clam 主题支持自定义背景色，
      若当前平台不可用则回退到默认主题（try/except 兜底）。
    - 注册"具名样式"（Accent.TButton / Success.TButton），
      界面层用 style="..." 直接引用，实现按钮颜色、字体、内边距的复用。
    :param root: tk.Tk 主窗口
    :return: ttk.Style 实例（供需要更多样式定制的调用方使用）
    """
    style = ttk.Style(root)
    # 使用 clam 主题（支持自定义颜色），若不可用则保持默认
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    # 整个窗口使用统一的背景色，保证视觉一致
    root.configure(bg=COLOR["bg"])

    # 基础控件：默认字体、前景色、背景色
    style.configure(".", font=FONT["normal"], foreground=COLOR["text"],
                    background=COLOR["bg"])
    style.configure("TLabel", background=COLOR["bg"], foreground=COLOR["text"],
                    font=FONT["normal"])
    style.configure("TFrame", background=COLOR["bg"])

    # 分组框（LabelFrame）：浅色边框 + 加粗分组标题
    style.configure("TLabelframe", background=COLOR["bg"], bordercolor=COLOR["border"])
    style.configure("TLabelframe.Label", background=COLOR["bg"],
                    foreground=COLOR["text"], font=FONT["section"])

    # 按钮：普通样式
    style.configure("TButton", padding=(12, 6), font=FONT["normal"])
    # 按钮：主色（蓝色，用于"启动服务"等主要操作）
    style.configure("Accent.TButton", background=COLOR["primary"], foreground="white",
                    font=FONT["normal"], padding=(12, 6), borderwidth=0)
    # 鼠标悬停/按下时切换为主色深，增强操作反馈
    style.map("Accent.TButton", background=[("active", COLOR["primary_dark"])])
    # 按钮：成功色（绿色，用于"提交/连接"等操作）
    style.configure("Success.TButton", background=COLOR["green"], foreground="white",
                    font=FONT["normal"], padding=(12, 6), borderwidth=0)
    style.map("Success.TButton", background=[("active", COLOR["green_dark"])])

    # 输入框：白底、浅色边框、内边距
    style.configure("TEntry", fieldbackground=COLOR["card"],
                    bordercolor=COLOR["border"], padding=4)

    # 表格（Treeview）：白底、浅色表头、选中行高亮（浅蓝）
    style.configure("Treeview", background=COLOR["card"], fieldbackground=COLOR["card"],
                    foreground=COLOR["text"], rowheight=28, bordercolor=COLOR["border"])
    style.configure("Treeview.Heading", background=COLOR["heading_bg"],
                    foreground=COLOR["text"],
                    font=("Microsoft YaHei UI", 10, "bold"), padding=6)
    style.map("Treeview", background=[("selected", "#DBEAFE")],
              foreground=[("selected", COLOR["primary_dark"])])
    return style


def add_header(parent, title, subtitle=""):
    """
    在窗口顶部添加一条彩色标题栏。

    【设计思路】
    - 头栏用普通 Frame + 固定高度（pack_propagate(False) 防止内容撑开高度），
      颜色取主色蓝，左侧显示软件名，右侧显示副标题。
    - 把标题栏做成独立函数，接收端/发送端/合并主程序都可复用，保证全程序一致。
    :return: 头栏 Frame
    """
    frame = tk.Frame(parent, bg=COLOR["primary"], height=58)
    frame.pack(fill="x")            # 横向铺满窗口宽度
    frame.pack_propagate(False)     # 固定高度，不让子控件改变高度

    # 软件名（主标题）
    tk.Label(frame, text=title, bg=COLOR["primary"], fg=COLOR["header_fg"],
             font=FONT["title"]).pack(side="left", padx=(18, 8), pady=8)
    if subtitle:
        # 副标题（浅蓝色，弱化显示）
        tk.Label(frame, text=subtitle, bg=COLOR["primary"], fg="#D7E3FF",
                 font=FONT["normal"]).pack(side="left", padx=(2, 0), pady=(12, 0))
    return frame


def add_footer(parent, text):
    """
    在窗口底部添加一条底栏（显示开发者信息等）。

    【设计思路】
    - 底栏固定高度、铺满宽度，颜色与头栏区分（浅灰底、灰字），
      用于展示开发者、版本等信息，避免遮挡正文区域。
    :return: 底栏 Frame
    """
    frame = tk.Frame(parent, bg="#EFF3F8", height=28)
    frame.pack(fill="x", side="bottom")   # 底部、横向铺满
    frame.pack_propagate(False)           # 固定高度

    tk.Label(frame, text=text, bg="#EFF3F8", fg=COLOR["muted"],
             font=FONT["small"]).pack(side="left", padx=14, pady=4)
    return frame

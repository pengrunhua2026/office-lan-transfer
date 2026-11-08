# -*- coding: utf-8 -*-
"""
程序配置持久化模块（ini）
========================
【文件定位】把用户最近一次填写的信息保存到程序目录下的 ini 文件，
下次启动时自动读取并回填，避免每次重复输入。

【设计思路】
  1. 为什么要持久化配置？
     发送端每次都要填写接收端 IP、姓名、工号，接收端每次都要填端口、接收目录。
     若每次都重填，体验很差且容易填错。把"最近一次填写"存成 ini，
     下次启动自动带出，只需在需要时修改。
  2. 配置文件放在哪里？
     - 打包为独立 exe 运行时：ini 与 exe 同目录，保证数据随程序持久化，
       且用户可方便找到/备份；
     - 直接运行源码时：放在项目根目录下。
  3. 为什么不使用系统注册表/环境变量？
     用轻量的 configparser + 文本 ini 文件即可满足需求，无需管理员权限、
     跨机器拷贝程序时配置跟随程序，简单、透明、易维护。
  4. 异常处理原则：
     读取/写入失败（如文件损坏、无权限）都不应导致程序崩溃，
     所以用 try/except 静默兜底，配置缺失时使用默认值。

配置文件位置：
  - 打包为独立 exe 运行时：保存在可执行程序所在目录
  - 直接运行源码时：保存在项目根目录下
"""
import configparser
import os
import sys


def app_base_dir():
    """返回程序所在目录（exe 所在目录 或 项目根目录）。

    【设计思路】
    - frozen 为 True 表示运行的是打包后的 exe，此时配置/数据应放在 exe 同目录；
    - 源码运行时返回项目根目录（本文件位于 common/，向上两级即项目根）。
    :return: 程序所在的绝对目录路径
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)   # exe 所在目录
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 项目根


class AppConfig:
    """基于 configparser 的轻量 ini 配置读写工具。

    【设计思路】
    - 封装 configparser 的标准读写，对外只暴露 get / set / save 三个方法，
      界面层无需关心 ini 文件的具体格式。
    - 提供默认值机制：某个键尚未配置时，get 返回默认值，界面可安全使用。
    - 读 / 写都做了异常兜底：配置损坏或缺权限都不影响程序启动。
    """

    def __init__(self, filename):
        """
        :param filename: ini 文件名，例如 "sender_config.ini"
        """
        # 拼接出 ini 文件的完整绝对路径（位于程序所在目录）
        self.path = os.path.join(app_base_dir(), filename)
        self._cfg = configparser.ConfigParser()
        self._load()   # 初始化时立即读取磁盘上的既有配置

    def _load(self):
        """从磁盘读取 ini 文件（若存在）。

        【设计思路】
        - 文件不存在（首次运行）时静默跳过，使用空配置 + 默认值。
        - 读取失败（编码或格式异常）也不中断，保证程序总能启动。
        """
        if os.path.isfile(self.path):
            try:
                self._cfg.read(self.path, encoding="utf-8")
            except Exception:
                pass

    def get(self, section, key, default=""):
        """读取配置项，不存在时返回默认值。

        【设计思路】
        - fallback 机制：小节或键不存在时返回 default，
          使调用方不必判断"是否配置过"，简化界面代码。
        :return: 配置项的字符串值，未配置时返回 default
        """
        try:
            return self._cfg.get(section, key, fallback=default)
        except Exception:
            return default

    def set(self, section, key, value):
        """写入一个配置项（自动创建小节）。

        【设计思路】
        - 小节不存在时先 add_section 创建，再写入键值，
          保证任意命名的小节都能正常工作。
        """
        if not self._cfg.has_section(section):
            self._cfg.add_section(section)
        self._cfg.set(section, key, str(value))

    def save(self):
        """把当前配置写回 ini 文件。

        【设计思路】
        - 用 utf-8 编码写出，保证中文（姓名、目录等）正常保存。
        - 写失败（磁盘只读、被占用等）静默忽略，下次运行仍可从默认值起步。
        """
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                self._cfg.write(f)
        except Exception:
            pass

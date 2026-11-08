# -*- coding: utf-8 -*-
"""
文件保存工具
============
【文件定位】本模块集中管理文件的存储与命名规则，提供三个通用函数：
  1. dated_dir       —— 在接收目录下按当天日期建立子文件夹，使不同日期的文件互不重叠。
  2. unique_path     —— 文件同名时自动追加版本号 _v2 / _v3 ...，绝不覆盖原文件。
  3. unique_dir_path —— 文件夹同名时自动追加版本号 _v2 / _v3 ...，绝不覆盖原文件夹。

【设计思路】
  1. 为什么要"按日期分目录"？
     所有收到的文件若都堆在同一个目录，几天之后将难以区分和查找。
     按"当天日期"建立一级子目录，使不同日期的文件天然隔离、互不覆盖，
     也便于按时间归档。
  2. 为什么要"同名不覆盖 + 版本号"？
     多人/多次发送同名文件时，若直接覆盖会造成旧数据丢失。
     通过在文件名后追加 _v2、_v3 ... 找到第一个不冲突的名字保存，
     保证"既保留旧文件，又保存新文件"。
  3. 为什么文件夹也做版本控制？
     提交/下发整个文件夹时，若顶层文件夹同名，直接覆盖会破坏整个目录。
     对顶层文件夹做整体版本隔离（_v2），文件夹内部文件按相对路径写入，
     不再逐个加版本——保证一个文件夹整体版本一致、结构完整。
  4. 版本号耗尽兜底：
     极端情况下（同文件重复极多次），用毫秒时间戳保证最终一定不冲突。

接收端与发送端共用本模块，保证两端的接收文件命名规则一致。
"""
import os
import re
from datetime import datetime


def dated_dir(base, date_str=None):
    """
    在 base 目录下建立"当天日期"子文件夹，并返回其路径。

    【设计思路】
    - 用系统当天日期（YYYY-MM-DD）作为目录名，使不同日期的文件互不重叠。
    - os.makedirs(..., exist_ok=True) 保证目录存在（不存在则创建），幂等安全。
    例：base = received，当天为 2026-10-24 → 返回 received\\2026-10-24

    :param base:      接收根目录
    :param date_str:  日期字符串，默认取系统当天日期（YYYY-MM-DD）
    :return: 当天日期子文件夹的绝对路径（不存在则自动创建）
    """
    # 未指定日期时，取系统当天日期作为目录名
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    day_dir = os.path.join(base, date_str)
    os.makedirs(day_dir, exist_ok=True)   # 目录不存在则自动创建（幂等）
    return day_dir


def unique_path(directory, filename):
    """
    返回一个不冲突的文件保存路径（同名自动加版本号）。

    【设计思路】
    - 目标文件不存在时直接返回原路径（最快路径）。
    - 已存在时，用正则识别主名是否已带 _vN 后缀；若是则从 N+1 继续编号，
      否则从 _v2 开始，直到找到不冲突的名字——这样多次保存同一文件时
      版本号依次为 _v2、_v3、_v4 ...，旧文件永不丢失。
    - 版本号理论上限 100000 后改用毫秒时间戳兜底，保证极端情况必不冲突。

    例：
      report.docx 已存在 → 返回 report_v2.docx
      report_v2.docx 也已存在 → 返回 report_v3.docx

    :param directory: 目标保存目录
    :param filename:  想要保存的文件名
    :return: 不冲突的完整保存路径
    """
    os.makedirs(directory, exist_ok=True)
    candidate = os.path.join(directory, filename)
    if not os.path.exists(candidate):
        return candidate  # 目标不存在，直接使用原名，无需加版本

    # 拆分主名与扩展名（如 report.docx → base=report, ext=.docx）
    base, ext = os.path.splitext(filename)

    # 若主名本身以 _vN 结尾（例如 report_v1），则从 N+1 继续编号，避免重复
    m = re.search(r"_v(\d+)$", base)
    start = int(m.group(1)) + 1 if m else 2
    stem = base

    # 从起始版本号起递增查找，直到找到可用文件名
    for i in range(start, 100000):
        new_name = "%s_v%d%s" % (stem, i, ext)
        candidate = os.path.join(directory, new_name)
        if not os.path.exists(candidate):
            return candidate

    # 兜底：极端情况下版本号耗尽，使用毫秒时间戳保证唯一
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return os.path.join(directory, "%s_%s%s" % (stem, ts, ext))


def unique_dir_path(directory, name):
    """
    返回一个不冲突的文件夹路径（用于提交整个文件夹时，为顶层文件夹做版本控制）。

    【设计思路】
    - 与 unique_path 逻辑对称，但针对"文件夹名"做版本控制。
    - 顶层文件夹名若已存在同名目录，追加 _v2、_v3 ...，绝不覆盖原文件夹；
      文件夹内部的子目录结构由调用方按相对路径写入，这里只保证顶层不冲突。
    - 这样多次提交同一文件夹时，会依次生成 名称、名称_v2、名称_v3 ...，
      每个文件夹整体版本一致、结构完整。

    例：
      folder 已存在     → 返回 folder_v2
      folder_v2 已存在  → 返回 folder_v3

    :param directory: 目标父目录
    :param name:      想要的文件夹名（顶层文件夹名）
    :return: 不冲突的完整文件夹路径
    """
    os.makedirs(directory, exist_ok=True)
    candidate = os.path.join(directory, name)
    if not os.path.exists(candidate):
        return candidate  # 顶层目录不存在，直接使用原名

    # 若文件夹名本身以 _vN 结尾，则从 N+1 继续编号
    m = re.search(r"_v(\d+)$", name)
    start = int(m.group(1)) + 1 if m else 2
    stem = name

    # 从起始版本号起递增查找，直到找到可用文件夹名
    for i in range(start, 100000):
        new_name = "%s_v%d" % (stem, i)
        candidate = os.path.join(directory, new_name)
        if not os.path.exists(candidate):
            return candidate

    # 兜底：极端情况下版本号耗尽，使用毫秒时间戳保证唯一
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    return os.path.join(directory, "%s_%s" % (stem, ts))

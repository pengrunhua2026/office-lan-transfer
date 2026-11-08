# -*- coding: utf-8 -*-
"""
生成 PyInstaller 版本资源文件（.txt）
======================================
用于为打包的 exe 写入"文件属性"信息（右键 → 属性 → 详细信息）：
  产品名、文件说明、版本号、公司名、版权、开发者等。

【设计思路】
  1. 为什么用代码生成版本资源？
     PyInstaller 的 --version-file 需要特定 VSVersionInfo 语法文本，
     手写易错、且版本升级时需多处同步。用常量（VERSION/VERSION_STR/DEVELOPER）
     一处定义、生成完整资源文件，改版本只改 gen_version.py 顶部常量。
  2. 版本号与产品信息集中管理：
     VERSION 用于 filevers/prodvers（四段），VERSION_STR 用于展示字符串，
     本文件是 exe 版本信息的唯一事实来源。

运行方式（在项目根目录下）：
  python tools/gen_version.py
输出到 build_assets/ 目录。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "build_assets")
os.makedirs(OUT_DIR, exist_ok=True)

# ===== 版本与产品信息（唯一事实来源，改版本只需改这里） =====
VERSION = (2, 1, 0, 0)          # 四段版本号（用于文件属性）
VERSION_STR = "2.1.0.0"         # 展示用版本字符串
DEVELOPER = "prh"               # 开发者
PRODUCT = "局域网办公文件传输系统"   # 产品名
COPYRIGHT = "Copyright (C) 2026 prh"  # 版权


def version_template(desc, product_name, internal_name, original_name):
    """按 PyInstaller 的 VSVersionInfo 语法构造版本资源文本。

    【设计思路】
    - FixedFileInfo 固定文件信息（filevers/prodvers 取 VERSION 四段）；
    - StringTable 用中文代码页 0804 + 1200 编码，保证中文属性正常显示；
    - 返回整段资源文本，供 write_version_files 写盘。
    """
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({", ".join(str(v) for v in VERSION)}),
    prodvers=({", ".join(str(v) for v in VERSION)}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', '{DEVELOPER}'),
        StringStruct('FileDescription', '{desc}'),
        StringStruct('FileVersion', '{VERSION_STR}'),
        StringStruct('InternalName', '{internal_name}'),
        StringStruct('LegalCopyright', '{COPYRIGHT}'),
        StringStruct('OriginalFilename', '{original_name}'),
        StringStruct('ProductName', '{product_name}'),
        StringStruct('ProductVersion', '{VERSION_STR}')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def write_version_files():
    main = version_template(
        desc="局域网办公文件传输系统",
        product_name=PRODUCT,
        internal_name="OfficeLanTransfer",
        original_name="OfficeLanTransfer.exe",
    )
    main_path = os.path.join(OUT_DIR, "version_main.txt")
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(main)
    print("已生成版本资源：")
    print(" ", main_path)


if __name__ == "__main__":
    write_version_files()

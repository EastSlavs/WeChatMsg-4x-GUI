# -*- coding: utf-8 -*-
"""Image-key extraction for the local WeChat account.

Adapted from the locally installed wechatauto project.
Version-sensitive Windows memory offsets.
"""
from __future__ import annotations

import ctypes
import hashlib
import struct
from ctypes import wintypes
from typing import Optional, Tuple

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.ReadProcessMemory.restype = wintypes.BOOL
_k32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL

MASTER_DLL_PATTERN = bytes.fromhex(
    "83ec404889d64889cb0f57c00f1142100f11024c8bb1c8020000"
    "4883b9d0020000107209488b9bb8020000eb074881c3b8020000"
    "4d85f60f880a0200004983fe10736d4c89761048c746180f0000"
    "000f10030f110648b8"
)

MASTER_DLL_VERIFY = (b"488944242048b8", b"488944242848b8", b"488944243048b8")

CFG_LANDMARK = b"global_config"

CFG_PTR_BACK = 0x138

CFG_OFFSET = 0x68

CFG_DWORD_OFF = 0x40

CFG_WXID_OFF = 0x48

CFG_CIPHER_OFF = 0x2B8

class _MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_wchar * 256),
        ("szExePath", ctypes.c_wchar * 260),
    ]

def _find_weixin_module(pid: int) -> Optional[Tuple[int, int, str]]:
    """返回 (模块基址, 模块大小, 路径); weixin.dll 为微信 4.x 主模块"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MODULEENTRY32W)]
    k32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MODULEENTRY32W)]
    snap = k32.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
    if not snap or snap == -1 or snap == (1 << 64) - 1:
        return None
    try:
        me = _MODULEENTRY32W()
        me.dwSize = ctypes.sizeof(me)
        ok = k32.Module32FirstW(snap, ctypes.byref(me))
        while ok:
            if me.szModule and me.szModule.lower() == "weixin.dll":
                return (me.modBaseAddr or 0), me.modBaseSize, me.szExePath
            me.dwSize = ctypes.sizeof(me)
            ok = k32.Module32NextW(snap, ctypes.byref(me))
    finally:
        k32.CloseHandle(snap)
    return None

def _extract_movabs_xor_key(dll_path: str) -> Optional[bytes]:
    """从 weixin.dll 特征码后提取 4×movabs 立即数拼接成 32 字节 XOR 材料。

    特征码(sub_1803308D0 前缀)后紧跟 4 个 '48 b8 <imm64>' movabs 指令,
    立即数即主密钥的 XOR 材料。小版本通常不改此代码段, 大版本需重采。
    """
    try:
        with open(dll_path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    hit = data.find(MASTER_DLL_PATTERN)
    if hit < 0:
        return None
    take = min(200, len(data) - hit)
    hex_txt = data[hit:hit + take].hex()
    hex_txt = hex_txt[len(MASTER_DLL_PATTERN) * 2:]  # 丢弃特征码自身
    key = ""
    for vf in MASTER_DLL_VERIFY:
        if len(hex_txt) < 30 or hex_txt[16:30] != vf.decode():
            return None
        key += hex_txt[0:16]
        hex_txt = hex_txt[30:]
    if len(hex_txt) < 16:
        return None
    key += hex_txt[0:16]
    try:
        return bytes.fromhex(key)
    except ValueError:
        return None

def _read_remote_string(h, read, addr: int) -> str:
    """跨进程读 MSVC x64 std::string(SSO: size<=15 内联, 否则堆指针)"""
    sz_buf = read(addr + 16, 8)
    if not sz_buf:
        return ""
    size = struct.unpack_from("<Q", sz_buf)[0]
    if size <= 0 or size > 0x7FFFFFFF:
        return ""
    if size <= 15:
        data = read(addr, size)
    else:
        p_buf = read(addr, 8)
        if not p_buf:
            return ""
        data = read(struct.unpack_from("<Q", p_buf)[0], size)
    if not data:
        return ""
    return data[:size].decode("utf-8", "replace")

def _read_remote_bytes(h, read, addr: int) -> Optional[bytes]:
    """跨进程读字节缓冲(std::string 布局: data@+0, size@+16, cap@+24)"""
    sz_buf = read(addr + 16, 8)
    if not sz_buf:
        return None
    size = struct.unpack_from("<Q", sz_buf)[0]
    if size <= 0 or size > 0x400:
        return None
    cap_buf = read(addr + 24, 4)
    cap = struct.unpack_from("<I", cap_buf)[0] if cap_buf else 0
    if (cap | 0xF) == 0xF:
        data = read(addr, size)          # SSO 内联
    else:
        p_buf = read(addr, 8)
        if not p_buf:
            return None
        data = read(struct.unpack_from("<Q", p_buf)[0], size)
    if not data or len(data) != size:
        return None
    return data[:size]

def extract_master_key_from_cfg(pid: int) -> Optional[Tuple[str, int, str]]:
    """从 Weixin.exe 进程提取 (主密钥hex, cfgDword, wxId)。

    流程(ReadWeixinKey-rev 同源): 整块读 weixin.dll 映像 → 扫 global_config
    SSO 地标 → 指针链 cfg → 读 cfg+0x2B8 密文与 cfg+0x40 cfgDword →
    密文 XOR DLL movabs 材料得主密钥。锚点(CFG_PTR_BACK/CFG_OFFSET/特征码)
    每版本重采; 提取失败返回 None。
    """
    base, mod_size, dll_path = _find_weixin_module(pid) or (0, 0, "")
    if not base or not dll_path or mod_size <= 0 or mod_size >= 0x40000000:
        return None
    h = _k32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        return None
    try:
        def read(addr: int, n: int):
            buf = ctypes.create_string_buffer(n)
            br = ctypes.c_size_t(0)
            if _k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(br)) and br.value:
                return buf.raw[: br.value]
            return None

        image = read(base, mod_size)
        if not image or len(image) != mod_size:
            return None
        # 扫 global_config SSO 地标(size==13@+16, cap==15@+24, 内容内联@+0)
        pos = -1
        for i in range(len(image) - 8, 0, -8):
            if struct.unpack_from("<I", image, i)[0] == len(CFG_LANDMARK):
                cap = struct.unpack_from("<I", image, i + 8)[0]
                if cap and (cap | 0xF) == 0xF and i - 16 >= 0:
                    if image[i - 16:i - 16 + len(CFG_LANDMARK)] == CFG_LANDMARK:
                        pos = i
                        break
        if pos < 0:
            return None
        # 指针链: v18 = *(base + pos - CFG_PTR_BACK); cfg = *(v18 + CFG_OFFSET)
        v18_buf = read(base + pos - CFG_PTR_BACK, 8)
        if not v18_buf:
            return None
        v18 = struct.unpack_from("<Q", v18_buf)[0]
        cfg_buf = read(v18 + CFG_OFFSET, 8)
        if not cfg_buf:
            return None
        cfg = struct.unpack_from("<Q", cfg_buf)[0]
        if not (0x10000 <= cfg < 0x800000000000):
            return None
        # cfgDword + wxId
        dw_buf = read(cfg + CFG_DWORD_OFF, 4)
        cfg_dword = struct.unpack_from("<I", dw_buf)[0] if dw_buf else 0
        wxid = _read_remote_string(h, read, cfg + CFG_WXID_OFF)
        # dbKey 密文
        cipher = _read_remote_bytes(h, read, cfg + CFG_CIPHER_OFF)
        if not cipher:
            return None
        material = _extract_movabs_xor_key(dll_path)
        if not material or len(material) != len(cipher):
            return None
        master = bytes(a ^ b for a, b in zip(cipher, material))
        return master.hex(), cfg_dword, wxid
    finally:
        _k32.CloseHandle(h)


def derive_image_keys(cfg_dword: int, wxid: str):
    """Return (AES key, XOR key) without logging secrets."""
    if not wxid or not cfg_dword:
        return None
    aes_key = hashlib.md5(
        (str(cfg_dword) + wxid).encode("utf-8")
    ).hexdigest()[:16].encode("ascii")
    xor_key = cfg_dword & 0xFF
    return aes_key, xor_key


def get_image_keys(expected_wxid: str = None):
    """Locate keys for one logged-in WeChat account."""
    from .key import find_weixin_processes

    processes = find_weixin_processes()
    for proc in processes:
        pid = proc.get("pid")
        if not pid:
            continue
        try:
            result = extract_master_key_from_cfg(pid)
        except (OSError, ValueError, TypeError, struct.error):
            continue

        if not result:
            continue

        _master, cfg_dword, wxid = result

        if expected_wxid and wxid != expected_wxid:
            continue

        keys = derive_image_keys(cfg_dword, wxid)
        if keys:
            return keys

    return None

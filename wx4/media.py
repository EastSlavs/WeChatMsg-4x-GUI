# -*- coding: utf-8 -*-
"""媒体附件导出：图片(.dat) / 语音(silk) / 视频 / 文件。

图片（`msg/attach/<md5(会话)>/<年月>/Img/*.dat`）在微信 4.x 里是加密的：

    V1  头 `07 08 56 31 08 07`，AES-128-ECB，密钥固定 = md5("0")[:16]
    V2  头 `07 08 56 32 08 07`，AES-128-ECB，密钥每次随机，只在内存里短暂存在
    旧  单字节 XOR

结构：`[6B 头][4B aes_size LE][4B xor_size LE][1B 异或键][AES 密文][明文段][XOR 段]`

**关于 V2**：密钥不是常驻内存的，只在微信渲染该图片时临时生成。因此本工具
默认**不**尝试自动破解 V2，而是把图片按消息索引原样导出（`--copy-dat`），
并写出 `images.txt` 对照表。V1 会自动解密。想尝试自动找 V2 密钥可以用
`find_dat_aes_key()`（需要先在微信里点开过该图片，且较慢）。

语音（SILK）、视频（mp4）、文件（docx/xlsx/pdf…）都不加密，直接导出。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import re
import shutil
import struct
from dataclasses import dataclass, field

from Cryptodome.Cipher import AES

SIG_V1 = bytes.fromhex("070856310807")
SIG_V2 = bytes.fromhex("070856320807")
V1_KEY = hashlib.md5(b"0").hexdigest()[:16].encode()

IMG_EXT = ((b"\xff\xd8\xff", ".jpg"), (b"\x89PNG", ".png"), (b"GIF8", ".gif"),
           (b"RIFF", ".webp"), (b"BM", ".bmp"), (b"wxgf", ".wxgf"))

kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
READABLE = {0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80}


class _MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_uint64), ("AllocationBase", ctypes.c_uint64),
                ("AllocationProtect", wt.DWORD), ("_p1", wt.DWORD),
                ("RegionSize", ctypes.c_uint64), ("State", wt.DWORD),
                ("Protect", wt.DWORD), ("Type", wt.DWORD), ("_p2", wt.DWORD)]


# ---------------------------------------------------------------------------
# dat 解码
# ---------------------------------------------------------------------------
def sniff_ext(data: bytes) -> str:
    for magic, ext in IMG_EXT:
        if data.startswith(magic):
            return ext
    return ".bin"


def _pkcs7_strip(data: bytes) -> bytes:
    if data and 1 <= data[-1] <= 16 and data[-data[-1]:] == bytes([data[-1]]) * data[-1]:
        return data[:-data[-1]]
    return data


def dat_layout(data: bytes):
    """返回 (aes_ct, mid, xor_ct, xor_key_hint)；不符合结构返回 None。"""
    if len(data) < 15:
        return None
    aes_size, xor_size = struct.unpack_from("<LL", data, 6)
    if aes_size <= 0 or aes_size > len(data):
        return None
    aligned = ((aes_size + 15) // 16) * 16
    start = 15
    end = start + aligned
    if end > len(data):
        return None
    xor_start = len(data) - xor_size if xor_size else len(data)
    if xor_start < end:
        return None
    return data[start:end], data[end:xor_start], data[xor_start:], data[14]


def decode_dat(data: bytes, aes_key: bytes | None = None,
               xor_key: int | None = None) -> bytes | None:
    """解出一个 .dat；失败返回 None（V2 没密钥时会返回 None）。"""
    sig = data[:6]
    if sig == SIG_V1:
        key = V1_KEY
    elif sig == SIG_V2:
        key = aes_key
        if not key:
            return None
    else:
        for k in range(256):
            head = bytes(b ^ k for b in data[:4])
            if sniff_ext(head) != ".bin":
                return bytes(b ^ k for b in data)
        return None
    lay = dat_layout(data)
    if not lay:
        return None
    aes_ct, mid, xor_ct, hint = lay
    try:
        pt = _pkcs7_strip(AES.new(key, AES.MODE_ECB).decrypt(aes_ct))
    except ValueError:
        return None
    xk = xor_key if xor_key is not None else hint
    # V2: ??16???????????????
    if sig == SIG_V2:
        out = pt + bytes(b ^ (xk & 0xFF) for b in xor_ct)
    else:
        out = pt + mid + bytes(b ^ (xk & 0xFF) for b in xor_ct)
    i = out.find(b"\xff\xd9")
    if out.startswith(b"\xff\xd8") and i > 0:
        out = out[:i + 2]
    i = out.rfind(b"IEND")
    if out.startswith(b"\x89PNG") and i > 0:
        out = out[:i + 8]  # ?? IEND ???4?? CRC
    return out


# ---------------------------------------------------------------------------
# 可选：从内存里找 V2 密钥（慢，且需要该图片最近被渲染过）
# ---------------------------------------------------------------------------
def _regions(h):
    out, addr, mbi = [], 0, _MBI()
    while addr < 0x7FFF_FFFF_FFFF:
        if kernel32.VirtualQueryEx(h, ctypes.c_uint64(addr), ctypes.byref(mbi),
                                   ctypes.sizeof(mbi)) == 0:
            break
        if (mbi.State == MEM_COMMIT and mbi.Protect in READABLE
                and 0 < mbi.RegionSize < 500 * 1024 * 1024):
            out.append((mbi.BaseAddress, mbi.RegionSize))
        nxt = mbi.BaseAddress + mbi.RegionSize
        if nxt <= addr:
            break
        addr = nxt
    return out


def _read(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    n = ctypes.c_size_t(0)
    if kernel32.ReadProcessMemory(h, ctypes.c_uint64(addr), buf, size, ctypes.byref(n)):
        return buf.raw[: n.value]
    return None


def find_dat_aes_key(sample_path: str, pids=None, progress=None):
    """用样本 .dat 在微信内存里搜索 V2 的 AES 密钥。

    判据：候选密钥必须是 16 字节可打印 ASCII，且用它解出的第一段密文，
    前缀要与其后紧跟的**明文段**一致。
    """
    progress = progress or (lambda m: None)
    with open(sample_path, "rb") as f:
        data = f.read()
    if data[:6] != SIG_V2:
        progress("样本不是 V2 格式")
        return None
    lay = dat_layout(data)
    if not lay:
        return None
    aes_ct, mid, _xor, _hint = lay
    if len(mid) < 16:
        progress("样本没有内嵌明文段，无法校验候选密钥（试试 _t.dat）")
        return None
    expect = mid[:16]

    if pids is None:
        from .key import find_weixin_processes
        pids = [p["pid"] for p in find_weixin_processes()]
    for pid in pids:
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            continue
        try:
            for base, size in _regions(h):
                buf = _read(h, base, size)
                if not buf or len(buf) < 64:
                    continue
                # 只按 16 字节对齐滑动，并先做可打印判断，避免大量无效 AES
                for i in range(0, len(buf) - 16 + 1, 16):
                    cand = buf[i:i + 16]
                    if not all(0x20 <= b < 0x7F for b in cand):
                        continue
                    try:
                        out = AES.new(cand, AES.MODE_ECB).decrypt(aes_ct[:16])
                    except ValueError:
                        continue
                    if out[:len(expect)] == expect:
                        progress("找到图片密钥 %r (PID=%d @0x%X)" % (cand, pid, base + i))
                        return cand
        finally:
            kernel32.CloseHandle(h)
    progress("未在内存中找到图片 AES 密钥")
    return None


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------
@dataclass
class MediaStats:
    images: int = 0
    images_raw: int = 0
    voices: int = 0
    videos: int = 0
    files: int = 0
    extras: list = field(default_factory=list)



def _silk_to_mp3(silk_path: str, mp3_path: str) -> bool:
    """将SILK转换成MP3，成功返回True。"""
    import subprocess
    import tempfile
    from pathlib import Path

    try:
        import pilk
        with tempfile.TemporaryDirectory(prefix="wechat_voice_") as tmp:
            pcm = Path(tmp) / "voice.pcm"
            pilk.decode(silk_path, str(pcm), pcm_rate=24000)

            result = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
                    "-i", str(pcm),
                    "-codec:a", "libmp3lame", "-q:a", "4",
                    mp3_path
                ],
                capture_output=True,
                timeout=60
            )
            return (
                result.returncode == 0
                and os.path.isfile(mp3_path)
                and os.path.getsize(mp3_path) > 0
            )
    except (ImportError, OSError, ValueError, RuntimeError,
            subprocess.TimeoutExpired):
        return False


def export_voice(data, msgs, out_dir: str, progress=None) -> int:
    """导出语音为 .silk（SILK 格式，可用 silk-v3-decoder 转 mp3）。"""
    progress = progress or (lambda m: None)
    n = 0
    os.makedirs(out_dir, exist_ok=True)
    for m in msgs:
        if m["type"] != 34 or not m["server_id"]:
            continue
        blob = data.voice_blob(m["session"], m["server_id"])
        if not blob:
            continue
        stamp = m["time_str"].replace(":", "").replace("-", "").replace(" ", "_")
        path = os.path.join(out_dir, "voice_%s_%s.silk" % (stamp, m["server_id"]))
        with open(path, "wb") as f:
            f.write(blob)
        m["extra"]["voice_file"] = path
        mp3_path = os.path.splitext(path)[0] + ".mp3"
        if _silk_to_mp3(path, mp3_path):
            m["extra"]["voice_mp3"] = mp3_path
        else:
            progress("语音MP3转换失败，已保留SILK原文件")
        n += 1
    if n:
        progress("语音 %d 条 -> %s" % (n, out_dir))
    return n


def _session_attach_index(attach_dir: str) -> dict:
    idx = {}
    if not attach_dir or not os.path.isdir(attach_dir):
        return idx
    for root, _dirs, files in os.walk(attach_dir):
        for f in files:
            if f.endswith(".dat"):
                idx.setdefault(os.path.splitext(f)[0], os.path.join(root, f))
    return idx



def convert_wxgf(data: bytes) -> bytes | None:
    """Convert WXGF HEVC content into a browser-compatible JPEG.

    Decode available frames and select a nonblank frame.
    Return None when conversion is unavailable or unsuccessful.
    """
    if not data.startswith(b"wxgf"):
        return None

    import subprocess
    import tempfile
    from pathlib import Path

    try:
        from PIL import Image, ImageStat

        candidates = []
        for match in re.finditer(
            rb"\x00\x00\x00\x01|\x00\x00\x01", data
        ):
            pos = match.end()
            if pos < len(data) and ((data[pos] >> 1) & 63) == 32:
                candidates.append(match.start())

        if not candidates:
            return None

        with tempfile.TemporaryDirectory(prefix="wxgf_") as temp:
            folder = Path(temp)
            pattern = folder / "frame_%03d.png"

            proc = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-y", "-f", "hevc", "-i", "pipe:0",
                    "-frames:v", "20", "-vsync", "0",
                    str(pattern),
                ],
                input=data[candidates[0]:],
                capture_output=True,
                timeout=60,
            )

            frames = sorted(folder.glob("frame_*.png"))
            if proc.returncode != 0 or not frames:
                return None

            best_score = float("-inf")
            best_path = None

            for frame in frames:
                with Image.open(frame) as img:
                    sample = img.convert("RGB").resize((128, 128))
                    stats = ImageStat.Stat(sample)
                    variation = sum(stats.stddev) / 3
                    pixels = sample.getdata()
                    nonwhite = sum(
                        1 for r, g, b in pixels
                        if min(r, g, b) < 245
                    ) / (128 * 128)
                    score = variation + nonwhite * 100

                if score > best_score:
                    best_score = score
                    best_path = frame

            with Image.open(best_path) as img:
                import io
                result = io.BytesIO()
                img.convert("RGB").save(
                    result, format="JPEG", quality=94
                )
                return result.getvalue()

    except (OSError, ValueError, RuntimeError, ImportError,
            subprocess.TimeoutExpired):
        return None


def export_images(data, session: str, msgs, out_dir: str,
                  aes_key: bytes | None = None, copy_dat: bool = True,
                  progress=None, xor_key: int | None = None) -> int:
    """按消息里的 md5 把图片找出来；V1 自动解密，V2 视 copy_dat 决定是否原样复制。"""
    progress = progress or (lambda m: None)

    # Auto-detect image keys for this WeChat account.
    # Explicitly supplied keys always take priority.
    if aes_key is None or xor_key is None:
        account_wxid = getattr(data, "wxid", "")
        if account_wxid:
            try:
                from .image_key import get_image_keys
                detected = get_image_keys(expected_wxid=account_wxid)
                if detected:
                    if aes_key is None:
                        aes_key = detected[0]
                    if xor_key is None:
                        xor_key = detected[1]
                    progress("Image key detected for current account")
                else:
                    progress("Image key unavailable; continuing normally")
            except (OSError, ValueError, RuntimeError, ImportError) as exc:
                progress("Image key detection unavailable: %s" % exc)

    attach_dir = data.attach_dir(session)
    if not attach_dir:
        return 0
    index = _session_attach_index(attach_dir)
    if not index:
        return 0
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for m in msgs:
        if m["type"] != 3:
            continue
        # packed_hex ?????????????????????? MD5
        packed = m.get("packed_hex") or ""
        try:
            packed_text = bytes.fromhex(packed).decode("ascii", errors="ignore")
        except (ValueError, TypeError):
            packed_text = ""

        md5s = re.findall(r"[0-9a-fA-F]{32}", packed_text)
        md5s += re.findall(r"[0-9a-fA-F]{32}", m.get("content") or "")
        md5s = [x.lower() for x in md5s]
        for md5 in dict.fromkeys(md5s):
            src = (index.get(md5 + "_h") or index.get(md5) or index.get(md5 + "_t"))
            if not src:
                continue
            with open(src, "rb") as f:
                raw = f.read()
            out = decode_dat(raw, aes_key, xor_key)
            if out is not None and sniff_ext(out) == ".wxgf":
                converted = convert_wxgf(out)
                if converted is not None:
                    out = converted
                else:
                    progress("WXGF conversion failed; original retained: %s" % src)
            stamp = m["time_str"].replace(":", "").replace("-", "").replace(" ", "_")
            if out is not None:
                dst = os.path.join(out_dir, "img_%s_%s%s" % (stamp, md5[:8], sniff_ext(out)))
                with open(dst, "wb") as f:
                    f.write(out)
            elif copy_dat:
                dst = os.path.join(out_dir, "%s.dat" % md5)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
            else:
                continue
            m["extra"].setdefault("images", []).append(dst)
            n += 1
            break
    if n:
        progress("图片 %d 张 -> %s" % (n, out_dir))
    return n



def export_files(data, session: str, msgs, out_dir: str,
                 progress=None) -> int:
    """只导出指定会话消息中能可靠匹配的本地文件附件。"""
    from pathlib import Path
    from datetime import datetime
    import re
    import shutil

    progress = progress or (lambda msg: None)
    base = Path(data.msg_dir()) / "file"

    if not base.is_dir():
        progress("本地文件目录不存在")
        return 0

    # 扫描本账号文件目录，仅建立索引，不批量复制。
    index = {}
    for path in base.rglob("*"):
        if path.is_file():
            index.setdefault(path.name.casefold(), []).append(path)

    def normalized(name):
        # 微信重复下载时会自动添加 (1)、(2) 等后缀。
        p = Path(name)
        stem = re.sub(r"\(\d+\)$", "", p.stem)
        return (stem + p.suffix).casefold()

    normalized_index = {}
    for paths in index.values():
        for path in paths:
            normalized_index.setdefault(
                normalized(path.name), []
            ).append(path)

    output = Path(out_dir)
    count = 0

    for msg in msgs:
        if msg.get("type") != 49:
            continue

        extra = msg.get("extra") or {}
        filename = extra.get("filename")

        if not filename or not str(msg.get("text", "")).startswith("[文件]"):
            continue

        filename = Path(str(filename).replace("\\\\", "/")).name
        if not filename or filename in (".", ".."):
            continue

        try:
            size = int(extra.get("filesize") or 0)
        except (TypeError, ValueError):
            size = 0

        # 文件大小必须存在，避免误匹配同名不同内容。
        if size <= 0:
            progress("无法验证文件大小，跳过：" + filename)
            continue

        exact = index.get(filename.casefold(), [])
        candidates = exact or normalized_index.get(
            normalized(filename), []
        )

        verified = []
        for candidate in candidates:
            try:
                if candidate.stat().st_size == size:
                    verified.append(candidate)
            except OSError:
                continue

        if not verified:
            progress("本地缺失：" + filename)
            continue

        # 先用原始文件名优先，再用消息时间选最接近的副本。
        try:
            message_time = datetime.strptime(
                msg["time_str"], "%Y-%m-%d %H:%M:%S"
            ).timestamp()
        except (KeyError, ValueError, TypeError):
            message_time = None

        def rank(path):
            exact_name = path.name.casefold() == filename.casefold()
            if message_time is None:
                distance = float("inf")
            else:
                distance = abs(path.stat().st_mtime - message_time)
            return (0 if exact_name else 1, distance)

        verified.sort(key=rank)

        if len(verified) > 1:
            first, second = rank(verified[0]), rank(verified[1])
            # 相同优先级、修改时间极接近时，无法可靠区分。
            if first[0] == second[0] and abs(first[1] - second[1]) < 60:
                progress("存在多个候选，跳过：" + filename)
                continue

        source = verified[0]
        output.mkdir(parents=True, exist_ok=True)

        # 使用消息ID命名，避免不同消息的同名文件互相覆盖。
        sid = re.sub(
            r"[^0-9A-Za-z_-]", "_",
            str(msg.get("server_id") or msg.get("local_id") or count)
        )
        destination = output / (sid + "_" + filename)

        try:
            shutil.copy2(source, destination)
            extra["file_file"] = str(destination)
            msg["extra"] = extra
            count += 1
            progress("文件匹配成功：" + filename)
        except OSError as exc:
            progress("复制失败：%s (%s)" % (filename, exc))

    return count


def copy_plain_media(data, out_dir: str, progress=None) -> tuple:
    """视频/文件在 msg/video、msg/file 下是明文，整体复制。"""
    progress = progress or (lambda m: None)
    nv = nf = 0
    for sub in ("video", "file"):
        base = os.path.join(data.msg_dir(), sub)
        if not os.path.isdir(base):
            continue
        dst_dir = os.path.join(out_dir, sub)
        for root, _dirs, files in os.walk(base):
            for f in files:
                src = os.path.join(root, f)
                dst = os.path.join(dst_dir, os.path.relpath(src, base))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    continue
                if sub == "video":
                    nv += 1
                else:
                    nf += 1
    if nv or nf:
        progress("视频 %d 个、文件 %d 个 -> %s" % (nv, nf, out_dir))
    return nv, nf


def export_session_media(data, session: str, msgs, out_root: str,
                         aes_key=None, copy_dat=True, progress=None, xor_key=None) -> MediaStats:
    """导出某个会话的全部媒体，返回统计。"""
    progress = progress or (lambda m: None)
    os.makedirs(out_root, exist_ok=True)
    st = MediaStats()
    st.images = export_images(data, session, msgs, os.path.join(out_root, "image"),
                              aes_key=aes_key, copy_dat=copy_dat, progress=progress, xor_key=xor_key)
    st.voices = export_voice(data, msgs, os.path.join(out_root, "voice"), progress=progress)
    st.files = export_files(data, session, msgs, os.path.join(out_root, "file"), progress=progress)
    return st

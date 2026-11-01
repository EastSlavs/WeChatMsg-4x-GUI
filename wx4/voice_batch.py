# -*- coding: utf-8 -*-
"""按会话与日期批量导出微信语音，保存SILK、MP3、CSV和ZIP。"""

from datetime import datetime, timedelta
from pathlib import Path
import csv
import re
import subprocess
import zipfile


def export_voice_batch(data, session, start, end, export_dir, progress=print):
    import pilk

    start_date = datetime.strptime(start, "%Y-%m-%d")
    end_date = datetime.strptime(end, "%Y-%m-%d")

    if start_date > end_date:
        raise ValueError("开始日期不能晚于结束日期")

    start_ts = int(start_date.timestamp())
    end_ts = int((end_date + timedelta(days=1)).timestamp()) - 1

    # 避免会话名被当作文件路径
    safe_session = re.sub(r"[^a-zA-Z0-9_@.-]", "_", session)
    folder = Path(export_dir) / safe_session / (start + "_to_" + end)
    mp3_dir = folder / "mp3"
    silk_dir = folder / "silk"

    mp3_dir.mkdir(parents=True, exist_ok=True)
    silk_dir.mkdir(parents=True, exist_ok=True)

    msgs = list(data.messages(session, start=start_ts, end=end_ts))
    voices = [m for m in msgs if m.get("type") == 34]

    progress("匹配语音：%d 条" % len(voices))

    success = 0
    failed = 0
    missing = 0
    records = []
    exported_mp3 = []

    for index, msg in enumerate(voices, 1):
        server_id = msg.get("server_id")
        if not server_id:
            missing += 1
            continue

        blob = data.voice_blob(session, server_id)
        if not blob:
            missing += 1
            progress("[%d] 本地语音数据缺失" % index)
            continue

        stamp = re.sub(r"[^0-9]", "", msg["time_str"])
        name = "%s_%s_%03d" % (stamp, server_id, index)

        silk_file = silk_dir / (name + ".silk")
        pcm_file = folder / (name + ".pcm")
        mp3_file = mp3_dir / (name + ".mp3")

        try:
            silk_file.write_bytes(blob)

            pilk.decode(
                str(silk_file),
                str(pcm_file),
                pcm_rate=24000
            )

            result = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-y",
                    "-f", "s16le", "-ar", "24000", "-ac", "1",
                    "-i", str(pcm_file),
                    "-codec:a", "libmp3lame", "-q:a", "4",
                    str(mp3_file)
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr[-300:])

            if not mp3_file.exists() or mp3_file.stat().st_size == 0:
                raise RuntimeError("生成的MP3为空")

            records.append({
                "时间": msg["time_str"],
                "发送方": "我" if msg.get("is_sender") else "对方",
                "MP3文件": mp3_file.name,
                "SILK文件": silk_file.name
            })
            exported_mp3.append(mp3_file)
            success += 1
            progress("[%d/%d] OK" % (index, len(voices)))

        except Exception as exc:
            failed += 1
            if mp3_file.exists():
                mp3_file.unlink()
            progress("[%d/%d] FAILED: %s" %
                     (index, len(voices), exc))

        finally:
            if pcm_file.exists():
                pcm_file.unlink()

    csv_path = folder / "语音清单.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["时间", "发送方", "MP3文件", "SILK文件"]
        )
        writer.writeheader()
        writer.writerows(records)

    zip_path = folder / "全部语音_MP3.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for file in exported_mp3:
            z.write(file, arcname=file.name)
        z.write(csv_path, arcname=csv_path.name)

    progress("===== SUMMARY =====")
    progress("MATCHED: %d" % len(voices))
    progress("SUCCESS: %d" % success)
    progress("FAILED: %d" % failed)
    progress("MISSING: %d" % missing)
    progress("ZIP: %s" % zip_path.resolve())
    progress("BATCH_EXPORT_DONE")

    return 0 if failed == 0 and missing == 0 else 2

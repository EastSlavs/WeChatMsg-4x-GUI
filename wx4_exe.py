# -*- coding: utf-8 -*-
import os
import sys

if getattr(sys, "frozen", False):
    base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    ffmpeg_dir = os.path.join(base, "ffmpeg")
    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")

from wx4.cli import main

if __name__ == "__main__":
    sys.exit(main())
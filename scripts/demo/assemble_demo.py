# -*- coding: utf-8 -*-
"""把片头 + 演示 + 片尾合成最终无声视频。"""
import os
import subprocess

WORK = r"C:\Users\llj13\Documents\deepseek-harness\default-workspace\rec"
FF = r"E:\传智杯作品\backend\.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
OUT_FINAL = r"E:\传智杯作品\docs\智汇研途-演示视频-无声.mp4"


def run(args, quiet=True):
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-800:])
    return r


def card(src, dst, seconds):
    run([FF, "-y", "-loop", "1", "-i", src, "-t", str(seconds),
         "-r", "30", "-vf", "scale=1920:1080,setsar=1",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", dst])


def main():
    intro = os.path.join(WORK, "intro.mp4")
    outro = os.path.join(WORK, "outro.mp4")
    demo = os.path.join(WORK, "demo_silent.mp4")

    print("生成片头 / 片尾 ...")
    card(os.path.join(WORK, "intro.png"), intro, 4)
    card(os.path.join(WORK, "outro.png"), outro, 5)

    lst = os.path.join(WORK, "concat.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in (intro, demo, outro):
            f.write("file '%s'\n" % p.replace("\\", "/"))

    print("合成 ...")
    run([FF, "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c:v", "libx264", "-preset", "medium", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30",
         "-movflags", "+faststart", OUT_FINAL])

    size = os.path.getsize(OUT_FINAL)
    info = subprocess.run([FF, "-i", OUT_FINAL], stderr=subprocess.PIPE)
    text = info.stderr.decode("utf-8", "ignore")
    dur = ""
    for line in text.splitlines():
        if "Duration" in line:
            dur = line.split("Duration:")[1].split(",")[0].strip()
            break
    print("完成:", OUT_FINAL)
    print("大小: %.1f MB  时长: %s" % (size / 1024 / 1024, dur))


if __name__ == "__main__":
    main()

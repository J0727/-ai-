# -*- coding: utf-8 -*-
from PIL import Image, ImageDraw, ImageFont
import os
OUT = r"C:\Users\llj13\Documents\deepseek-harness\default-workspace\rec"
os.makedirs(OUT, exist_ok=True)
FR = r"C:\Windows\Fonts\msyh.ttc"
FB = r"C:\Windows\Fonts\msyhbd.ttc"
W, H = 1920, 1080
PURPLE = (124, 58, 237)
INK = (31, 45, 61)
MUTED = (107, 114, 128)

# 片头
im = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(im)
# 顶部渐变色块
for i in range(10):
    c = tuple(int(PURPLE[j] + (255 - PURPLE[j]) * (1 - (i + 1) / 10)) for j in range(3))
    d.rectangle([0, i * 4, W, (i + 1) * 4], fill=c)
d.text((W/2, 430), "智 汇 研 途", font=ImageFont.truetype(FB, 96), fill=PURPLE, anchor="mm")
d.text((W/2, 540), "可核验的科研对话助手", font=ImageFont.truetype(FR, 42), fill=INK, anchor="mm")
d.text((W/2, 640), "第九届传智杯 · AI 大模型创新应用挑战赛", font=ImageFont.truetype(FR, 28), fill=MUTED, anchor="mm")
im.save(os.path.join(OUT, "intro.png"))

# 片尾
im = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(im)
d.text((W/2, 330), "在线演示", font=ImageFont.truetype(FB, 54), fill=PURPLE, anchor="mm")
d.text((W/2, 440), "http://139.224.206.77:8000", font=ImageFont.truetype(FB, 44), fill=INK, anchor="mm")
d.text((W/2, 540), "演示账号：demo / demo123456", font=ImageFont.truetype(FR, 32), fill=MUTED, anchor="mm")
d.text((W/2, 660), "每一条结论都能点回原文 · 每一个译名都能对到国标", font=ImageFont.truetype(FR, 28), fill=MUTED, anchor="mm")
d.text((W/2, 740), "拿不准的，它会诚实地说拿不准", font=ImageFont.truetype(FR, 28), fill=MUTED, anchor="mm")
im.save(os.path.join(OUT, "outro.png"))
print("ok")
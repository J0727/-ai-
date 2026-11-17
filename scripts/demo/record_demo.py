# -*- coding: utf-8 -*-
"""用 CDP 驱动 Edge 并逐帧捕获，生成无声演示视频（后期自行配音）。

用法：
    python record_demo.py test      # 15 秒冒烟测试
    python record_demo.py full      # 完整演示（约 6 分钟）
"""
import base64
import json
import os
import subprocess
import sys
import threading
import time

import requests
import websocket  # websocket-client

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9333
W, H = 1920, 1080
URL = os.environ.get("DEMO_URL", "http://127.0.0.1:8000/")
WORK = r"C:\Users\llj13\Documents\deepseek-harness\default-workspace\rec"
FRAMES = os.path.join(WORK, "frames")
PROFILE = os.path.join(WORK, "profile")


class Driver:
    def __init__(self):
        self.proc = None
        self.ws = None
        self.mid = 0
        self.target = None
        self.capturing = False
        self.frames = []
        self.lock = threading.Lock()
        self.io_lock = threading.Lock()

    # ---------- 浏览器 ----------
    def launch(self):
        os.makedirs(WORK, exist_ok=True)
        for d in (FRAMES, PROFILE):
            if os.path.isdir(d):
                for f in os.listdir(d):
                    try:
                        os.remove(os.path.join(d, f))
                    except Exception:
                        pass
            else:
                os.makedirs(d, exist_ok=True)
        self.proc = subprocess.Popen(
            [
                EDGE,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--hide-scrollbars",
                "--force-device-scale-factor=1",
                f"--window-size={W},{H}",
                f"--remote-debugging-port={PORT}",
                f"--user-data-dir={PROFILE}",
                "--autoplay-policy=no-user-gesture-required",
                "--disable-features=Translate,MediaRouter",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(60):
            try:
                tabs = requests.get(f"http://127.0.0.1:{PORT}/json/list", timeout=1).json()
                pages = [t for t in tabs if t.get("type") == "page"]
                if pages:
                    self.target = pages[0]
                    break
            except Exception:
                pass
            time.sleep(0.3)
        if not self.target:
            raise RuntimeError("未找到浏览器调试目标")
        self.ws = websocket.create_connection(
            self.target["webSocketDebuggerUrl"], timeout=30, max_size=64 * 1024 * 1024
        )
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False},
        )
        self.send("Emulation.setVisibleSize", {"width": W, "height": H})

    def send(self, method, params=None):
        # CDP 是「一问一答」协议，录制线程与操作线程必须串行化，
        # 否则两边同时 send 会互相吞掉响应，表现为永久阻塞。
        with self.io_lock:
            self.mid += 1
            mid = self.mid
            self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(self.ws.recv())
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"{method} 失败: {msg['error']}")
                    return msg.get("result", {})

    def evaluate(self, expr):
        r = self.send(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        return r.get("result", {}).get("value")

    def goto(self, url):
        self.send("Page.navigate", {"url": url})
        time.sleep(1.2)

    def shot(self):
        r = self.send(
            "Page.captureScreenshot",
            {"format": "jpeg", "quality": 82, "captureBeyondViewport": False},
        )
        return base64.b64decode(r["data"])

    # ---------- 录像 ----------
    def start_capture(self, fps=12):
        self.capturing = True
        self.frames = []

        def loop():
            interval = 1.0 / fps
            n = 0
            t0 = time.time()
            while self.capturing:
                st = time.time()
                try:
                    img = self.shot()
                    with self.lock:
                        n += 1
                        path = os.path.join(FRAMES, f"f{n:06d}.jpg")
                        with open(path, "wb") as f:
                            f.write(img)
                        self.frames.append(time.time() - t0)
                except Exception:
                    pass
                dt = time.time() - st
                if dt < interval:
                    time.sleep(interval - dt)

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()

    def stop_capture(self):
        self.capturing = False
        self.thread.join(timeout=10)
        with self.lock:
            ts = list(self.frames)
        dur = ts[-1] if ts else 0
        with open(os.path.join(WORK, "timing.json"), "w") as f:
            json.dump({"frames": len(ts), "duration": dur,
                       "fps": (len(ts) / dur) if dur > 0 else 0}, f)
        return len(ts), dur

    # ---------- 交互 ----------
    def type_text(self, text, cps=22):
        self.evaluate("document.getElementById('input').focus()")
        for ch in text:
            self.send("Input.insertText", {"text": ch})
            time.sleep(1.0 / cps)

    def click_send(self):
        self.evaluate("document.getElementById('sendBtn').click()")

    def upload_pdf(self, path):
        """绕过文件选择框，直接把本地文件注入 #fileInput 并触发 change。"""
        self.send("DOM.enable")
        doc = self.send("DOM.getDocument", {"depth": -1})
        node = self.send(
            "DOM.querySelector",
            {"nodeId": doc["root"]["nodeId"], "selector": "#fileInput"},
        )
        node_id = node.get("nodeId")
        if not node_id:
            raise RuntimeError("未找到 #fileInput")
        self.send("DOM.setFileInputFiles", {"files": [path], "nodeId": node_id})
        return True

    def new_chat(self):
        self.evaluate("document.getElementById('newChat') && document.getElementById('newChat').click()")
        time.sleep(0.8)

    def scroll_chat(self, px):
        self.evaluate(
            "(()=>{const c=document.querySelector('.thread, #thread, .messages, main')||document.scrollingElement;"
            f"c.scrollBy({{top:{px},behavior:'smooth'}});return 1;}})()"
        )

    def close(self):
        try:
            self.stop_capture()
        except Exception:
            pass
        try:
            self.ws.close()
        except Exception:
            pass
        if self.proc:
            self.proc.terminate()


def ffmpeg_exe():
    p = os.path.join(
        r"E:\传智杯作品\backend\.venv\Lib\site-packages",
        "imageio_ffmpeg", "binaries", "ffmpeg-win-x86_64-v7.1.exe",
    )
    return p if os.path.exists(p) else "ffmpeg"


def encode(out_path, fps):
    ff = ffmpeg_exe()
    cmd = [
        ff, "-y", "-framerate", str(max(1, round(fps, 2))),
        "-i", os.path.join(FRAMES, "f%06d.jpg"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-movflags", "+faststart", out_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ==================== 场景 ====================
def scenario_test(d):
    d.goto(URL)
    time.sleep(2)
    d.type_text("检索 transformer 在医学影像中的文献", cps=30)
    time.sleep(0.4)
    d.click_send()
    time.sleep(12)


def scenario_full(d):
    log = lambda m: print(f"[{time.time()-T0:6.1f}s] {m}", flush=True)

    # --- 1 首页（已在 main 中导航到首页）---
    log("首页")
    time.sleep(2.0)
    d.scroll_chat(320)
    time.sleep(2.2)
    d.scroll_chat(-320)
    time.sleep(1.8)

    # --- 2 文献检索 ---
    log("文献检索：输入")
    d.type_text("检索 transformer 在医学影像中的文献")
    time.sleep(0.6)
    log("文献检索：提交")
    d.click_send()
    time.sleep(38)
    log("文献检索：滚动结果")
    d.scroll_chat(520)
    time.sleep(4)
    d.scroll_chat(-260)
    time.sleep(2)

    # --- 3 翻译核验 ---
    log("翻译：新会话")
    d.new_chat()
    time.sleep(1.5)
    d.type_text("把这句话译成英语并核验：卷积神经网络在图像识别中效果很好")
    time.sleep(0.6)
    d.click_send()
    time.sleep(30)
    d.scroll_chat(320)
    time.sleep(3)

    # --- 4 引用核验 ---
    log("引用核验")
    d.new_chat()
    time.sleep(1.2)
    d.type_text("核验这条引用：10.1038/nature12373")
    time.sleep(0.6)
    d.click_send()
    time.sleep(22)
    d.scroll_chat(300)
    time.sleep(3)

    # --- 5 术语 ---
    log("术语速查")
    d.new_chat()
    time.sleep(1.2)
    d.type_text("「深度学习」的标准英译是什么")
    time.sleep(0.6)
    d.click_send()
    time.sleep(18)
    d.scroll_chat(260)
    time.sleep(3)

    # --- 6 官方 PDF 问答 ---
    log("上传官方测试 PDF")
    d.new_chat()
    time.sleep(1.5)
    try:
        d.upload_pdf(r"E:\科研小助手-解压\pdf\1706.03762v7.pdf")
        log("已注入文件，等待解析")
    except Exception as e:
        log(f"上传失败: {e}")
    time.sleep(9)
    log("就文档提问")
    d.type_text("这篇论文的第 6 作者是谁，在哪个机构工作？")
    time.sleep(0.6)
    d.click_send()
    time.sleep(36)
    d.scroll_chat(360)
    time.sleep(3)

    # --- 7 多篇对比 ---
    log("多篇对比")
    d.new_chat()
    time.sleep(1.2)
    d.type_text("对比 BERT 和 GPT 的相关研究")
    time.sleep(0.6)
    d.click_send()
    time.sleep(38)
    d.scroll_chat(420)
    time.sleep(3)

    # --- 8 综述框架 ---
    log("综述框架")
    d.new_chat()
    time.sleep(1.2)
    d.type_text("基于检索结果写一个关于 Transformer 的综述框架")
    time.sleep(0.6)
    d.click_send()
    time.sleep(34)
    d.scroll_chat(400)
    time.sleep(3)

    # --- 9 安全面板 ---
    log("安全面板")
    r = d.evaluate(
        "(()=>{const b=document.getElementById('policyBtn')||document.getElementById('secMiniBtn');"
        "if(b){b.click();return 'clicked';}return 'none';})()"
    )
    log(f"安全入口: {r}")
    time.sleep(10)
    d.evaluate(
        "(()=>{const b=document.getElementById('policyClose')||document.querySelector('[data-close]');"
        "if(b)b.click();return 1;})()"
    )
    time.sleep(2)

    # --- 10 收尾 ---
    log("收尾")
    d.scroll_chat(-4000)
    time.sleep(6)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    T0 = time.time()
    d = Driver()
    try:
        d.launch()
        time.sleep(1.0)
        d.goto(URL)
        time.sleep(3.0)          # 等首屏加载完再开录，避免片头白屏
        d.start_capture(fps=12)
        if mode == "test":
            scenario_test(d)
            out = os.path.join(WORK, "test.mp4")
        else:
            scenario_full(d)
            out = os.path.join(WORK, "demo_silent.mp4")
        time.sleep(1.0)          # 结尾停留
        n, dur = d.stop_capture()
        fps = (n / dur) if dur else 12
        print(f"捕获 {n} 帧，时长 {dur:.1f}s，平均 {fps:.2f} fps")
        encode(out, fps)
        print("输出:", out, os.path.getsize(out) // 1024, "KB")
    finally:
        d.close()

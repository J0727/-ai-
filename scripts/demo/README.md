# 演示视频自动录制

用 Chrome DevTools Protocol 驱动 Edge 逐帧捕获，生成无声演示视频（后期自行配音）。

| 文件 | 作用 |
| ---- | ---- |
| `record_demo.py` | 驱动浏览器执行演示脚本并逐帧截图 |
| `gen_cards.py` | 生成片头 / 片尾卡片 |
| `assemble_demo.py` | 合成片头 + 演示 + 片尾 |

## 用法

```bash
python scripts/demo/gen_cards.py
python scripts/demo/record_demo.py full     # 约 5 分钟素材
python scripts/demo/assemble_demo.py
```

依赖：`websocket-client`、`requests`、`Pillow`、ffmpeg（imageio-ffmpeg 自带）。

可通过环境变量 `DEMO_URL` 指定演示站点，默认 `http://127.0.0.1:8000/`。
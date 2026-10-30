#!/usr/bin/env python3
"""生成应用图标：纯 Python 绘制 PNG（无第三方依赖）→ 供 iconutil 打包为 .icns。

用法：python make_icon.py <输出 iconset 目录>
"""
import os
import struct
import sys
import zlib

BG = (79, 110, 247, 255)        # 蓝色底
CLIPBOARD = (255, 255, 255, 255)  # 白色板身
CLIP = (222, 229, 245, 255)     # 顶部夹子
BAR = (176, 190, 224, 255)      # 文字条
GREEN = (52, 199, 89, 255)      # 对勾圆
WHITE = (255, 255, 255, 255)

SIZE = 1024


def inside_rounded(x, y, rx0, ry0, rx1, ry1, r):
    """点 (x, y) 是否在圆角矩形内。"""
    if x < rx0 or x > rx1 or y < ry0 or y > ry1:
        return False
    cx = min(max(x, rx0 + r), rx1 - r)
    cy = min(max(y, ry0 + r), ry1 - r)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= r * r


def inside_circle(x, y, cx, cy, r):
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def build_pixels(n):
    k = n / SIZE
    px = bytearray(n * n * 4)

    # 形状参数（按 1024 基准设计，k 缩放）
    br = 224 * k                    # 底板圆角
    bx0, by0, bx1, by1 = 0, 0, n - 1, n - 1
    cx0, cy0, cx1, cy1 = 256 * k, 168 * k, 768 * k, 872 * k
    cr = 56 * k                     # 板身圆角
    clipx0, clipy0, clipx1, clipy1 = 402 * k, 122 * k, 622 * k, 232 * k
    clipr = 28 * k
    bars = [(320, 380, 704), (320, 500, 620), (320, 620, 704)]  # (x0, y, x1)
    bar_h = 34 * k
    gcx, gcy, gr = 700 * k, 700 * k, 132 * k
    # 对勾线段（粗线，用点到线段距离）
    check = [(636, 706, 686, 758), (686, 758, 772, 646)]
    check_w = 30 * k

    def seg_dist(px_, py_, x0, y0, x1, y1):
        vx, vy = x1 - x0, y1 - y0
        wx, wy = px_ - x0, py_ - y0
        t = max(0.0, min(1.0, (vx * wx + vy * wy) / max(vx * vx + vy * vy, 1e-9)))
        dx, dy = px_ - (x0 + t * vx), py_ - (y0 + t * vy)
        return (dx * dx + dy * dy) ** 0.5

    for y in range(n):
        row = y * n * 4
        for x in range(n):
            c = None
            if inside_rounded(x, y, bx0, by0, bx1, by1, br):
                c = BG
                if inside_rounded(x, y, cx0, cy0, cx1, cy1, cr):
                    c = CLIPBOARD
                if inside_rounded(x, y, clipx0, clipy0, clipx1, clipy1, clipr):
                    c = CLIP
                for (lx0, ly, lx1) in bars:
                    if lx0 * k <= x <= lx1 * k and ly * k <= y <= ly * k + bar_h:
                        c = BAR
                if inside_circle(x, y, gcx, gcy, gr):
                    c = GREEN
                    for (sx0, sy0, sx1, sy1) in check:
                        if seg_dist(x, y, sx0 * k, sy0 * k, sx1 * k, sy1 * k) <= check_w:
                            c = WHITE
            if c is not None:
                i = row + x * 4
                px[i:i + 4] = bytes(c)
    return px


def write_png(path, n, pixels):
    raw = b"".join(b"\x00" + pixels[y * n * 4:(y + 1) * n * 4] for y in range(n))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "app.iconset"
    os.makedirs(out, exist_ok=True)
    for n in (16, 32, 128, 256, 512, 1024):
        print(f"渲染 {n}x{n} …")
        write_png(os.path.join(out, f"icon_{n}x{n}.png"), n, build_pixels(n))
        if n <= 512:
            write_png(os.path.join(out, f"icon_{n}x{n}@2x.png"), n * 2, build_pixels(n * 2))
    print("iconset 完成 →", os.path.abspath(out))


if __name__ == "__main__":
    main()

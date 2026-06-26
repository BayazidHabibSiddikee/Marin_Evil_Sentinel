#!/usr/bin/env python3
# media/draw.py — Camera photo + turtle drawing, runs as its own process
import os
import sys
import time
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress ALSA noise
_dn = os.open(os.devnull, os.O_WRONLY)
_se = os.dup(2)
os.dup2(_dn, 2)
try:
    from turtle import *
    from tkinter import messagebox
    from time import sleep
    from PIL import Image
finally:
    os.dup2(_se, 2)
    os.close(_se)
    os.close(_dn)

from utils.platform import open_camera, kill_camera

COLORS = [
    (255,182,193),(173,216,230),(152,251,152),(230,230,250),(255,218,185),
    (255,255,224),(135,206,235),(240,128,128),(200,162,200),(211,211,211),
]


def take_photo():
    open_camera()
    time.sleep(2)
    try:
        import pyautogui
        screenshot = pyautogui.screenshot()
    except Exception as e:
        print(f"Screenshot failed: {e}")
        sys.exit(1)
    kill_camera()
    return screenshot


def draw_photo(screenshot):
    scale = 0.25
    dot_size = 2
    img = screenshot.convert("L").resize(
        (int(screenshot.width * scale), int(screenshot.height * scale))
    ).convert("RGB")
    width, height = img.size

    screen = Screen()
    screen.colormode(255)
    screen.setup(width * dot_size + 50, height * dot_size + 50, 100, 50)
    screen.bgcolor('light yellow')
    screen.tracer(False)

    x_offset = -width * dot_size / 2
    y_offset = height * dot_size / 2

    bright = ['white', 'light yellow']
    dark   = ['black', 'darkblue']

    pen = Turtle(); pen.hideturtle(); pen.up(); pen.speed(0)

    print("Drawing...")
    for y in range(height):
        for x in range(width):
            r, g, b = img.getpixel((x, y))
            pen.goto(x * dot_size + x_offset, y_offset - y * dot_size)
            pen.dot(dot_size, random.choice(bright if r > 127 else dark))
        if y % 10 == 0:
            screen.update()

    screen.tracer(True); screen.update()
    messagebox.showinfo("Done", "Drawing complete!")
    screen.mainloop()


if __name__ == '__main__':
    screenshot = take_photo()
    draw_photo(screenshot)

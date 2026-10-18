#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Цветокоррекция (матрица 3×3) для ВСЕГО экрана Windows через Magnification API.
С поддержкой свертывания в системный трей (возле часов).

Запуск без консоли CMD: переименуйте этот файл в *.pyw или запускайте через pythonw.exe
"""

import ctypes
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg
import winsound
from ctypes import wintypes
from tkinter import messagebox, ttk

# Для работы с системным треем
try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    messagebox.showerror(
        "Ошибка библиотек",
        "Для работы трея требуются библиотеки pystray и Pillow.\nУстановите их через CMD: pip install pystray Pillow"
    )
    sys.exit(1)

# ═══════════════════════════ НАСТРОЙКИ ═══════════════════════════

CORRECTION = [
    [ 0.89899400, -0.74830800, 0.84931400],
    [-0.01095300,  0.36857000, 0.64238300],
    [-0.01067100,  0.07964300, 0.93102800],
]

STRENGTH      = 1.0    # 1.0 — полная коррекция по матрице
KEEP_WHITE    = False  # не изменять значения матрицы нормализацией
CHECK_EVERY   = 2.0    # проверять эффект каждые 2 секунды
START_ENABLED = True   # включать фильтр сразу при запуске

# Горячие клавиши: Ctrl+Alt+F9 (фильтр) и Ctrl+Alt+F10 (автозапуск)
HOTKEY_MODS = 0x0002 | 0x0001 | 0x4000   # MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
FILTER_VK = 0x78                          # F9
AUTOSTART_VK = 0x79                       # F10

AUTOSTART_NAME = "ScreenColorCorrection"

# ═════════════════════════════════════════════════════════════════

IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

MUTEX_NAME = "Local\\ScreenColorCorrection_Mutex"
STOP_EVENT_NAME = "Local\\ScreenColorCorrection_Stop"
SHOW_EVENT_NAME = "Local\\ScreenColorCorrection_Show"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


# ───────────────────────── матрица ─────────────────────────

def correction_matrix():
    m = [[IDENTITY[i][j] + STRENGTH * (CORRECTION[i][j] - IDENTITY[i][j]) for j in range(3)]
         for i in range(3)]
    if KEEP_WHITE:
        m = [[x / sum(row) for x in row] for row in m]
    return m


def to_effect(m):
    c = [[0.0] * 5 for _ in range(5)]
    for i in range(3):
        for j in range(3):
            c[i][j] = m[j][i]
    c[3][3] = c[4][4] = 1.0
    return (ctypes.c_float * 25)(*[v for row in c for v in row])


# ───────────────────────── WinAPI ─────────────────────────

def load_winapi():
    if sys.platform != "win32":
        sys.exit("Этот скрипт работает только в Windows.")
    if struct.calcsize("P") == 4 and os.environ.get("PROCESSOR_ARCHITEW6432"):
        sys.exit("Нужен 64-битный Python.")

    mag = ctypes.WinDLL("Magnification.dll")
    pointer = ctypes.POINTER(ctypes.c_float * 25)
    mag.MagInitialize.restype = wintypes.BOOL
    mag.MagUninitialize.restype = wintypes.BOOL
    for fn in (mag.MagSetFullscreenColorEffect, mag.MagGetFullscreenColorEffect):
        fn.argtypes = [pointer]
        fn.restype = wintypes.BOOL

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateEventW.restype = wintypes.HANDLE
    k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenEventW.restype = wintypes.HANDLE
    k32.SetEvent.argtypes = [wintypes.HANDLE]
    k32.SetEvent.restype = wintypes.BOOL
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.GetCurrentThreadId.restype = wintypes.DWORD

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    u32.RegisterHotKey.restype = wintypes.BOOL
    u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                wintypes.UINT, wintypes.UINT]
    u32.GetMessageW.restype = ctypes.c_int
    u32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                       wintypes.WPARAM, wintypes.LPARAM]
    u32.PostThreadMessageW.restype = wintypes.BOOL
    return mag, k32, u32


# ───────────────────────── автозапуск ─────────────────────────

def launcher_command():
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.basename(exe).lower() == "python.exe" and os.path.exists(pyw):
        exe = pyw
    script_path = os.path.abspath(__file__)
    if script_path.endswith('.py'):
        pyw_script = script_path + 'w'
        if os.path.exists(pyw_script):
            script_path = pyw_script
    return f'"{exe}" "{script_path}" --minimized'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, AUTOSTART_NAME)
        return True
    except FileNotFoundError:
        return False


def install_autostart():
    cmd = launcher_command()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, cmd)


def uninstall_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, AUTOSTART_NAME)
    except FileNotFoundError:
        pass


def toggle_autostart():
    if autostart_enabled():
        uninstall_autostart()
        return False
    install_autostart()
    return True


# ───────────────────────── связь между экземплярами ─────────────────────────

def signal_event(k32, name):
    h = k32.OpenEventW(EVENT_MODIFY_STATE, False, name)
    if not h:
        return False
    k32.SetEvent(h)
    k32.CloseHandle(h)
    return True


def set_identity(mag):
    if mag.MagInitialize():
        try:
            mag.MagSetFullscreenColorEffect(ctypes.byref(to_effect(IDENTITY)))
        finally:
            mag.MagUninitialize()


def stop_running(mag, k32):
    found = signal_event(k32, STOP_EVENT_NAME)
    if found:
        time.sleep(1.0)
    set_identity(mag)


# ───────────────────────── горячие клавиши ─────────────────────────

def hotkey_worker(u32, k32, out_queue, info, ready):
    info["tid"] = k32.GetCurrentThreadId()
    info["filter_ok"] = bool(u32.RegisterHotKey(None, 1, HOTKEY_MODS, FILTER_VK))
    info["autostart_ok"] = bool(u32.RegisterHotKey(None, 2, HOTKEY_MODS, AUTOSTART_VK))
    ready.set()
    msg = wintypes.MSG()
    while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            out_queue.put(int(msg.wParam))
    u32.UnregisterHotKey(None, 1)
    u32.UnregisterHotKey(None, 2)


# ───────────────────────── Создание иконки трея ─────────────────────────

def create_tray_icon():
    image = Image.new('RGBA', (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill=(70, 130, 180))
    draw.text((22, 18), "C", fill=(255, 255, 255))
    return image


# ───────────────────────── окно ─────────────────────────

class App:
    def __init__(self, mag, k32, u32, stop_event, show_event, minimized):
        self.mag, self.k32, self.u32 = mag, k32, u32
        self.stop_event, self.show_event = stop_event, show_event

        self.on_effect = to_effect(correction_matrix())
        self.off_effect = to_effect(IDENTITY)
        self.current = (ctypes.c_float * 25)()
        self.enabled = START_ENABLED
        self.last_check = 0.0

        # Окно
        self.root = tk.Tk()
        self.root.title("Цветокоррекция экрана")
        self.root.resizable(False, False)
        
        # Перехватываем закрытие окна на крестик — прячем в трей
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        frm = ttk.Frame(self.root, padding=16)
        frm.pack(fill="both", expand=True)

        self.filter_lbl = ttk.Label(frm, font=("Segoe UI", 12, "bold"))
        self.filter_lbl.pack(anchor="w")
        self.auto_lbl = ttk.Label(frm)
        self.auto_lbl.pack(anchor="w", pady=(2, 12))

        self.filter_btn = ttk.Button(frm, width=36, command=self.toggle_filter)
        self.filter_btn.pack(fill="x", pady=3)
        self.auto_btn = ttk.Button(frm, width=36, command=self.toggle_autostart_click)
        self.auto_btn.pack(fill="x", pady=3)
        
        ttk.Button(frm, text="Свернуть в трей", command=self.hide_to_tray).pack(fill="x", pady=3)
        ttk.Button(frm, text="Выход", command=self.quit).pack(fill="x", pady=3)

        ttk.Label(
            frm, foreground="#666", justify="left", wraplength=300,
            text=("Ctrl+Alt+F9 — фильтр вкл/выкл\n"
                  "Ctrl+Alt+F10 — автозапуск вкл/выкл\n"
                  "Окно можно свернуть в трей (возле часов)."),
        ).pack(anchor="w", pady=(10, 0))

        # Иконка в системном трее
        menu = pystray.Menu(
            pystray.MenuItem('Открыть окно', self.show),
            pystray.MenuItem('Вкл/Выкл фильтр', self.toggle_filter),
            pystray.MenuItem('Выход', self.quit)
        )
        self.tray_icon = pystray.Icon("ColorCorrection", create_tray_icon(), "Цветокоррекция", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

        self.apply()
        self.queue = queue.Queue()
        self.hk_info = {}
        ready = threading.Event()
        self.hk_thread = threading.Thread(
            target=hotkey_worker, args=(u32, k32, self.queue, self.hk_info, ready), daemon=True)
        self.hk_thread.start()
        ready.wait(2.0)

        self.refresh()
        if minimized:
            self.hide_to_tray()
            
        self.root.after(100, self.tick)

    def hide_to_tray(self):
        self.root.withdraw()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def apply(self):
        self.mag.MagSetFullscreenColorEffect(
            ctypes.byref(self.on_effect if self.enabled else self.off_effect))

    def refresh(self):
        if self.enabled:
            self.filter_lbl.config(text="Фильтр: ВКЛЮЧЁН", foreground="#1a7f37")
            self.filter_btn.config(text="Выключить фильтр")
        else:
            self.filter_lbl.config(text="Фильтр: выключен", foreground="#b42318")
            self.filter_btn.config(text="Включить фильтр")
        if autostart_enabled():
            self.auto_lbl.config(text="Автозапуск: добавлен")
            self.auto_btn.config(text="Убрать из автозапуска")
        else:
            self.auto_lbl.config(text="Автозапуск: не добавлен")
            self.auto_btn.config(text="Добавить в автозапуск")

    def toggle_filter(self):
        self.enabled = not self.enabled
        self.apply()
        self.refresh()

    def toggle_autostart_click(self):
        try:
            toggle_autostart()
        except OSError as e:
            messagebox.showerror("Автозапуск", f"Не удалось изменить автозапуск:\n{e}")
        self.refresh()

    def toggle_autostart_hotkey(self):
        try:
            on = toggle_autostart()
            winsound.Beep(1200 if on else 500, 200)
        except OSError as e:
            pass
        self.refresh()

    def quit(self):
        if hasattr(self, 'tray_icon'):
            self.tray_icon.stop()
        self.root.destroy()

    def tick(self):
        k = self.k32
        if k.WaitForSingleObject(self.stop_event, 0) == 0:
            self.quit()
            return
        if k.WaitForSingleObject(self.show_event, 0) == 0:
            self.show()

        try:
            while True:
                key = self.queue.get_nowait()
                if key == 1:
                    self.toggle_filter()
                elif key == 2:
                    self.toggle_autostart_hotkey()
        except queue.Empty:
            pass

        now = time.monotonic()
        if now - self.last_check >= CHECK_EVERY:
            self.last_check = now
            target = self.on_effect if self.enabled else self.off_effect
            if (not self.mag.MagGetFullscreenColorEffect(ctypes.byref(self.current))
                    or any(abs(a - b) > 1e-4 for a, b in zip(self.current, target))):
                self.mag.MagSetFullscreenColorEffect(ctypes.byref(target))

        self.root.after(100, self.tick)

    def run(self):
        try:
            self.root.mainloop()
        finally:
            tid = self.hk_info.get("tid")
            if tid:
                self.u32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
                self.hk_thread.join(1.0)
            self.mag.MagSetFullscreenColorEffect(ctypes.byref(self.off_effect))


def run(mag, k32, u32, minimized):
    mutex = k32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        signal_event(k32, SHOW_EVENT_NAME)
        return
    stop_event = k32.CreateEventW(None, True, False, STOP_EVENT_NAME)
    show_event = k32.CreateEventW(None, False, False, SHOW_EVENT_NAME)

    if not mag.MagInitialize():
        raise ctypes.WinError()
    try:
        App(mag, k32, u32, stop_event, show_event, minimized).run()
    finally:
        mag.MagUninitialize()
        k32.CloseHandle(show_event)
        k32.CloseHandle(stop_event)
        k32.CloseHandle(mutex)


def main():
    args = set(sys.argv[1:])
    mag, k32, u32 = load_winapi()

    if "--uninstall" in args:
        uninstall_autostart()
        stop_running(mag, k32)
    elif args & {"--stop", "--reset"}:
        stop_running(mag, k32)
    elif "--install" in args:
        install_autostart()
        subprocess.Popen(launcher_command(), creationflags=0x08000000)
    else:
        run(mag, k32, u32, minimized="--minimized" in args)


if __name__ == "__main__":
    main()
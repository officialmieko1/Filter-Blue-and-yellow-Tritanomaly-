#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Цветокоррекция (матрица 3×3) для ВСЕГО экрана Windows через Magnification API.
С поддержкой свертывания в системный трей (возле часов).

Запуск без консоли CMD: переименуйте этот файл в *.pyw или запускайте через pythonw.exe
"""

import ctypes
import json
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

# Горячие клавиши по умолчанию. Пользователь может изменить их в окне настроек.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
ALLOWED_MODS = MOD_ALT | MOD_CONTROL | MOD_SHIFT
DEFAULT_HOTKEYS = {
    "filter": {"mods": MOD_CONTROL | MOD_ALT, "vk": 0x78},       # Ctrl+Alt+F9
    "autostart": {"mods": MOD_CONTROL | MOD_ALT, "vk": 0x79},   # Ctrl+Alt+F10
}

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


# ───────────────────────── пользовательские бинды ─────────────────────────


def settings_file():
    """Путь к настройкам в профиле пользователя Windows."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "TritopScreenColorCorrection")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "settings.json")


def normalize_hotkeys(data):
    """Проверить прочитанные бинды и подставить значения по умолчанию при ошибке."""
    result = {}
    for action, default in DEFAULT_HOTKEYS.items():
        item = data.get(action, {}) if isinstance(data, dict) else {}
        try:
            mods = int(item.get("mods", default["mods"])) & ALLOWED_MODS
            vk = int(item.get("vk", default["vk"]))
            if not (1 <= vk <= 255) or vk in (0x10, 0x11, 0x12, 0x5B, 0x5C):
                raise ValueError("Недопустимый код клавиши")
            if not mods:
                raise ValueError("Нужен хотя бы один модификатор")
            result[action] = {"mods": mods, "vk": vk}
        except (TypeError, ValueError, AttributeError):
            result[action] = dict(default)
    if (result["filter"]["mods"], result["filter"]["vk"]) == (result["autostart"]["mods"], result["autostart"]["vk"]):
        result["filter"] = dict(DEFAULT_HOTKEYS["filter"])
        result["autostart"] = dict(DEFAULT_HOTKEYS["autostart"])
    return result


def load_hotkeys():
    try:
        with open(settings_file(), "r", encoding="utf-8") as file:
            return normalize_hotkeys(json.load(file))
    except (OSError, ValueError, TypeError):
        return normalize_hotkeys(DEFAULT_HOTKEYS)


def save_hotkeys(hotkeys):
    path = settings_file()
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(hotkeys, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


VK_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
    0x20: "Space", 0x21: "Page Up", 0x22: "Page Down", 0x23: "End",
    0x24: "Home", 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓",
    0x2C: "Print Screen", 0x2D: "Insert", 0x2E: "Delete",
    0x60: "Num 0", 0x61: "Num 1", 0x62: "Num 2", 0x63: "Num 3",
    0x64: "Num 4", 0x65: "Num 5", 0x66: "Num 6", 0x67: "Num 7",
    0x68: "Num 8", 0x69: "Num 9", 0x6A: "Num *", 0x6B: "Num +",
    0x6D: "Num -", 0x6E: "Num .", 0x6F: "Num /",
}


def hotkey_name(binding):
    parts = []
    mods = binding["mods"]
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    vk = binding["vk"]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        key_name = chr(vk)
    elif 0x70 <= vk <= 0x87:
        key_name = f"F{vk - 0x6F}"
    else:
        key_name = VK_NAMES.get(vk, f"VK {vk}")
    parts.append(key_name)
    return "+".join(parts)


def captured_vk(event):
    """Получить виртуальный код клавиши из события Tk на Windows."""
    key = event.keysym
    special = {
        "BackSpace": 0x08, "Tab": 0x09, "Return": 0x0D, "Escape": 0x1B,
        "space": 0x20, "Prior": 0x21, "Next": 0x22, "End": 0x23,
        "Home": 0x24, "Left": 0x25, "Up": 0x26, "Right": 0x27,
        "Down": 0x28, "Print": 0x2C, "Insert": 0x2D, "Delete": 0x2E,
    }
    if key in special:
        return special[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    if key.startswith("F") and key[1:].isdigit():
        number = int(key[1:])
        if 1 <= number <= 24:
            return 0x6F + number
    # На Windows event.keycode обычно равен виртуальному коду клавиши.
    vk = int(getattr(event, "keycode", 0) or 0)
    if 1 <= vk <= 255:
        return vk
    return None


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
    u32.GetAsyncKeyState.argtypes = [wintypes.INT]
    u32.GetAsyncKeyState.restype = wintypes.SHORT
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

def hotkey_worker(u32, k32, out_queue, info, ready, hotkeys):
    info["tid"] = k32.GetCurrentThreadId()
    info["filter_ok"] = bool(u32.RegisterHotKey(
        None, 1, hotkeys["filter"]["mods"] | MOD_NOREPEAT, hotkeys["filter"]["vk"]))
    info["autostart_ok"] = bool(u32.RegisterHotKey(
        None, 2, hotkeys["autostart"]["mods"] | MOD_NOREPEAT, hotkeys["autostart"]["vk"]))
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
        self.hotkeys = load_hotkeys()

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
        
        ttk.Button(frm, text="Настроить бинды", command=self.configure_hotkeys).pack(fill="x", pady=3)
        ttk.Button(frm, text="Свернуть в трей", command=self.hide_to_tray).pack(fill="x", pady=3)
        ttk.Button(frm, text="Выход", command=self.quit).pack(fill="x", pady=3)

        self.hotkey_lbl = ttk.Label(
            frm, foreground="#666", justify="left", wraplength=320,
        )
        self.hotkey_lbl.pack(anchor="w", pady=(10, 0))

        # Иконка в системном трее
        menu = pystray.Menu(
            pystray.MenuItem('Открыть окно', self.show),
            pystray.MenuItem('Вкл/Выкл фильтр', self.toggle_filter),
            pystray.MenuItem('Выход', self.quit)
        )
        self.tray_icon = pystray.Icon("ColorCorrection", create_tray_icon(), "Цветокоррекция", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

        self.apply()
        self.start_hotkeys()

        self.refresh()
        if minimized:
            self.hide_to_tray()
            
        self.root.after(100, self.tick)

    def start_hotkeys(self):
        self.queue = queue.Queue()
        self.hk_info = {}
        ready = threading.Event()
        current_hotkeys = {name: dict(value) for name, value in self.hotkeys.items()}
        self.hk_thread = threading.Thread(
            target=hotkey_worker,
            args=(self.u32, self.k32, self.queue, self.hk_info, ready, current_hotkeys),
            daemon=True,
        )
        self.hk_thread.start()
        ready.wait(2.0)

    def stop_hotkeys(self):
        tid = getattr(self, "hk_info", {}).get("tid")
        thread = getattr(self, "hk_thread", None)
        if tid and thread and thread.is_alive():
            self.u32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            thread.join(1.0)

    def configure_hotkeys(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Настройка биндов")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frm = ttk.Frame(dialog, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(
            frm,
            text="Выберите действие и нажмите нужную комбинацию.\n"
                 "Нужен хотя бы один модификатор: Ctrl, Alt или Shift.",
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        pending = {name: dict(value) for name, value in self.hotkeys.items()}
        labels = {}
        recording = {"action": None}
        hint = tk.StringVar(value="")
        actions = (
            ("filter", "Включение/выключение фильтра"),
            ("autostart", "Включение/выключение автозапуска"),
        )

        for row, (action, title) in enumerate(actions, start=1):
            ttk.Label(frm, text=title).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            labels[action] = ttk.Label(frm, text=hotkey_name(pending[action]), width=18)
            labels[action].grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

            def begin_recording(name=action):
                recording["action"] = name
                hint.set(f"Для действия «{dict(actions)[name]}» нажмите комбинацию...")
                dialog.focus_force()

            ttk.Button(frm, text="Изменить", command=begin_recording).grid(
                row=row, column=2, sticky="e", pady=4)

        ttk.Label(frm, textvariable=hint, foreground="#1f5f99", wraplength=370).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 10))

        def on_keypress(event):
            action = recording["action"]
            if not action:
                return None
            if event.keysym in {
                "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
                "Meta_L", "Meta_R", "Super_L", "Super_R",
            }:
                return "break"

            mods = 0
            # Проверяем состояние клавиш через WinAPI, чтобы надёжно распознавать Alt/Ctrl/Shift.
            modifier_keys = ((0x11, MOD_CONTROL), (0x12, MOD_ALT), (0x10, MOD_SHIFT))
            for virtual_key, modifier_flag in modifier_keys:
                if self.u32.GetAsyncKeyState(virtual_key) & 0x8000:
                    mods |= modifier_flag
            # Резервный путь на случай, если ОС не вернула состояние клавиш.
            if not mods:
                if event.state & 0x0004:
                    mods |= MOD_CONTROL
                if event.state & 0x0008:
                    mods |= MOD_ALT
                if event.state & 0x0001:
                    mods |= MOD_SHIFT

            vk = captured_vk(event)
            if not vk:
                hint.set("Эту клавишу назначить не удалось. Попробуйте другую.")
                return "break"
            if not mods:
                hint.set("Добавьте Ctrl, Alt или Shift и нажмите клавишу ещё раз.")
                return "break"

            pending[action] = {"mods": mods, "vk": vk}
            labels[action].config(text=hotkey_name(pending[action]))
            recording["action"] = None
            hint.set(f"Назначено: {hotkey_name(pending[action])}. Нажмите «Сохранить».")
            return "break"

        dialog.bind("<KeyPress>", on_keypress)

        def save_and_close():
            if (pending["filter"]["mods"], pending["filter"]["vk"]) == (
                    pending["autostart"]["mods"], pending["autostart"]["vk"]):
                messagebox.showerror(
                    "Настройка биндов",
                    "Для фильтра и автозапуска должны быть разные комбинации.",
                    parent=dialog,
                )
                return

            old_hotkeys = {name: dict(value) for name, value in self.hotkeys.items()}
            self.stop_hotkeys()
            self.hotkeys = {name: dict(value) for name, value in pending.items()}
            self.start_hotkeys()

            failed = []
            if not self.hk_info.get("filter_ok"):
                failed.append(f"Фильтр ({hotkey_name(self.hotkeys['filter'])})")
            if not self.hk_info.get("autostart_ok"):
                failed.append(f"Автозапуск ({hotkey_name(self.hotkeys['autostart'])})")
            if failed:
                self.stop_hotkeys()
                self.hotkeys = old_hotkeys
                self.start_hotkeys()
                self.refresh()
                messagebox.showerror(
                    "Не удалось назначить бинды",
                    "Эти комбинации уже используются другой программой или Windows:\n\n"
                    + "\n".join(failed)
                    + "\n\nСтарые настройки оставлены без изменений.",
                    parent=dialog,
                )
                return

            try:
                save_hotkeys(self.hotkeys)
            except OSError as exc:
                self.stop_hotkeys()
                self.hotkeys = old_hotkeys
                self.start_hotkeys()
                self.refresh()
                messagebox.showerror(
                    "Ошибка сохранения",
                    f"Не удалось сохранить настройки:\n{exc}\n\nСтарые настройки восстановлены.",
                    parent=dialog,
                )
                return
            self.refresh()
            dialog.destroy()

        buttons = ttk.Frame(frm)
        buttons.grid(row=4, column=0, columnspan=3, sticky="e", pady=(2, 0))
        ttk.Button(buttons, text="Сохранить", command=save_and_close).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Отмена", command=dialog.destroy).pack(side="right")

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

        hk_lines = [
            f"{hotkey_name(self.hotkeys['filter'])} — фильтр вкл/выкл",
            f"{hotkey_name(self.hotkeys['autostart'])} — автозапуск вкл/выкл",
            "Окно можно свернуть в трей (возле часов).",
        ]
        failed = []
        if not self.hk_info.get("filter_ok", True):
            failed.append("не зарегистрирован бинд фильтра")
        if not self.hk_info.get("autostart_ok", True):
            failed.append("не зарегистрирован бинд автозапуска")
        if failed:
            hk_lines.append("Внимание: " + "; ".join(failed) + ".")
        self.hotkey_lbl.config(text="\n".join(hk_lines))

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
            self.stop_hotkeys()
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
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
        "Missing dependencies",
        "The system tray requires pystray and Pillow.\nInstall them in CMD with: pip install pystray Pillow"
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

# Язык интерфейса. Английский используется при первом запуске.
LANGUAGES = {
    "en": "English",
    "ru": "Русский",
    "es": "Español",
    "pt": "Português",
    "de": "Deutsch",
    "fr": "Français",
}
LANGUAGE_CODES = {name: code for code, name in LANGUAGES.items()}

TRANSLATIONS = {
    "en": {
        "app_title": "Screen Color Correction", "language_label": "Language:",
        "filter_enabled": "Filter: ON", "filter_disabled": "Filter: OFF",
        "filter_off_button": "Turn filter off", "filter_on_button": "Turn filter on",
        "autostart_added": "Autostart: enabled", "autostart_not_added": "Autostart: disabled",
        "autostart_remove_button": "Remove from autostart", "autostart_add_button": "Add to autostart",
        "hotkeys_button": "Configure hotkeys", "tray_button": "Minimize to tray", "exit_button": "Exit",
        "hotkey_filter_line": "{hotkey} — toggle filter", "hotkey_autostart_line": "{hotkey} — toggle autostart",
        "tray_hint": "The window can be minimized to the system tray (near the clock).",
        "filter_hotkey_failed": "filter hotkey is not registered", "autostart_hotkey_failed": "autostart hotkey is not registered",
        "warning_prefix": "Warning: ", "menu_open": "Open window", "menu_toggle_filter": "Toggle filter", "menu_exit": "Exit",
        "hotkey_dialog_title": "Hotkey settings",
        "hotkey_dialog_help": "Choose an action and press the desired key combination.\nAt least one modifier is required: Ctrl, Alt, or Shift.",
        "action_filter": "Toggle filter on/off", "action_autostart": "Toggle autostart on/off", "change_button": "Change",
        "record_prompt": "For “{action}”, press a key combination...", "unassignable_key": "This key could not be assigned. Try another.",
        "need_modifier": "Add Ctrl, Alt or Shift and press the key again.",
        "assigned_hint": "Assigned: {hotkey}. Click “Save”.", "save_button": "Save", "cancel_button": "Cancel",
        "duplicate_hotkey_title": "Hotkey settings",
        "duplicate_hotkey_error": "The filter and autostart must use different combinations.",
        "hotkey_conflict_title": "Unable to register hotkeys",
        "hotkey_conflict_filter": "Filter ({hotkey})", "hotkey_conflict_autostart": "Autostart ({hotkey})",
        "hotkey_conflict_body": "These combinations are already used by another application or Windows:\n\n{failed}\n\nThe previous settings have been restored.",
        "save_error_title": "Save error", "save_error_body": "Could not save settings:\n{error}\n\nThe previous settings have been restored.",
        "autostart_error_title": "Autostart", "autostart_error_body": "Could not change autostart:\n{error}",
        "startup_library_title": "Missing dependencies",
        "startup_library_body": "The system tray requires pystray and Pillow.\nInstall them in CMD with: pip install pystray Pillow",
        "windows_only": "This script only works on Windows.", "python_64bit": "64-bit Python is required.",
    },
    "ru": {
        "app_title": "Цветокоррекция экрана", "language_label": "Язык:",
        "filter_enabled": "Фильтр: ВКЛЮЧЁН", "filter_disabled": "Фильтр: выключен",
        "filter_off_button": "Выключить фильтр", "filter_on_button": "Включить фильтр",
        "autostart_added": "Автозапуск: добавлен", "autostart_not_added": "Автозапуск: не добавлен",
        "autostart_remove_button": "Убрать из автозапуска", "autostart_add_button": "Добавить в автозапуск",
        "hotkeys_button": "Настроить горячие клавиши", "tray_button": "Свернуть в трей", "exit_button": "Выход",
        "hotkey_filter_line": "{hotkey} — фильтр вкл/выкл", "hotkey_autostart_line": "{hotkey} — автозапуск вкл/выкл",
        "tray_hint": "Окно можно свернуть в трей (возле часов).",
        "filter_hotkey_failed": "не зарегистрирован бинд фильтра", "autostart_hotkey_failed": "не зарегистрирован бинд автозапуска",
        "warning_prefix": "Внимание: ", "menu_open": "Открыть окно", "menu_toggle_filter": "Вкл/Выкл фильтр", "menu_exit": "Выход",
        "hotkey_dialog_title": "Настройка горячих клавиш",
        "hotkey_dialog_help": "Выберите действие и нажмите нужную комбинацию.\nНужен хотя бы один модификатор: Ctrl, Alt или Shift.",
        "action_filter": "Включение/выключение фильтра", "action_autostart": "Включение/выключение автозапуска", "change_button": "Изменить",
        "record_prompt": "Для действия «{action}» нажмите комбинацию...", "unassignable_key": "Эту клавишу назначить не удалось. Попробуйте другую.",
        "need_modifier": "Добавьте Ctrl, Alt или Shift и нажмите клавишу ещё раз.",
        "assigned_hint": "Назначено: {hotkey}. Нажмите «Сохранить».", "save_button": "Сохранить", "cancel_button": "Отмена",
        "duplicate_hotkey_title": "Настройка горячих клавиш",
        "duplicate_hotkey_error": "Для фильтра и автозапуска должны быть разные комбинации.",
        "hotkey_conflict_title": "Не удалось назначить горячие клавиши",
        "hotkey_conflict_filter": "Фильтр ({hotkey})", "hotkey_conflict_autostart": "Автозапуск ({hotkey})",
        "hotkey_conflict_body": "Эти комбинации уже используются другой программой или Windows:\n\n{failed}\n\nСтарые настройки оставлены без изменений.",
        "save_error_title": "Ошибка сохранения", "save_error_body": "Не удалось сохранить настройки:\n{error}\n\nСтарые настройки восстановлены.",
        "autostart_error_title": "Автозапуск", "autostart_error_body": "Не удалось изменить автозапуск:\n{error}",
        "startup_library_title": "Ошибка библиотек",
        "startup_library_body": "Для работы трея требуются библиотеки pystray и Pillow.\nУстановите их через CMD: pip install pystray Pillow",
        "windows_only": "Этот скрипт работает только в Windows.", "python_64bit": "Нужен 64-битный Python.",
    },
    "es": {
        "app_title": "Corrección de color de pantalla", "language_label": "Idioma:",
        "filter_enabled": "Filtro: ACTIVADO", "filter_disabled": "Filtro: DESACTIVADO",
        "filter_off_button": "Desactivar filtro", "filter_on_button": "Activar filtro",
        "autostart_added": "Inicio automático: activado", "autostart_not_added": "Inicio automático: desactivado",
        "autostart_remove_button": "Quitar del inicio automático", "autostart_add_button": "Añadir al inicio automático",
        "hotkeys_button": "Configurar atajos", "tray_button": "Minimizar a la bandeja", "exit_button": "Salir",
        "hotkey_filter_line": "{hotkey} — activar/desactivar filtro", "hotkey_autostart_line": "{hotkey} — activar/desactivar inicio automático",
        "tray_hint": "La ventana se puede minimizar a la bandeja del sistema (junto al reloj).",
        "filter_hotkey_failed": "el atajo del filtro no está registrado", "autostart_hotkey_failed": "el atajo de inicio automático no está registrado",
        "warning_prefix": "Aviso: ", "menu_open": "Abrir ventana", "menu_toggle_filter": "Alternar filtro", "menu_exit": "Salir",
        "hotkey_dialog_title": "Configuración de atajos", "hotkey_dialog_help": "Elige una acción y pulsa la combinación deseada.\nSe requiere al menos una tecla modificadora: Ctrl, Alt o Shift.",
        "action_filter": "Activar/desactivar filtro", "action_autostart": "Activar/desactivar inicio automático", "change_button": "Cambiar",
        "record_prompt": "Para «{action}», pulsa una combinación de teclas...", "unassignable_key": "No se pudo asignar esta tecla. Prueba otra.",
        "need_modifier": "Añade Ctrl, Alt o Shift y vuelve a pulsar la tecla.", "assigned_hint": "Asignado: {hotkey}. Pulsa «Guardar».",
        "save_button": "Guardar", "cancel_button": "Cancelar", "duplicate_hotkey_title": "Configuración de atajos",
        "duplicate_hotkey_error": "El filtro y el inicio automático deben tener combinaciones distintas.",
        "hotkey_conflict_title": "No se pudieron registrar los atajos", "hotkey_conflict_filter": "Filtro ({hotkey})", "hotkey_conflict_autostart": "Inicio automático ({hotkey})",
        "hotkey_conflict_body": "Otra aplicación o Windows ya usa estas combinaciones:\n\n{failed}\n\nSe conservaron los ajustes anteriores.",
        "save_error_title": "Error al guardar", "save_error_body": "No se pudo guardar la configuración:\n{error}\n\nSe restauró la configuración anterior.",
        "autostart_error_title": "Inicio automático", "autostart_error_body": "No se pudo cambiar el inicio automático:\n{error}",
        "startup_library_title": "Dependencias no instaladas", "startup_library_body": "La bandeja del sistema requiere pystray y Pillow.\nInstálalas en CMD con: pip install pystray Pillow",
        "windows_only": "Este script solo funciona en Windows.", "python_64bit": "Se requiere Python de 64 bits.",
    },
    "pt": {
        "app_title": "Correção de cor da tela", "language_label": "Idioma:",
        "filter_enabled": "Filtro: ATIVADO", "filter_disabled": "Filtro: DESATIVADO",
        "filter_off_button": "Desativar filtro", "filter_on_button": "Ativar filtro",
        "autostart_added": "Inicialização automática: ativada", "autostart_not_added": "Inicialização automática: desativada",
        "autostart_remove_button": "Remover da inicialização automática", "autostart_add_button": "Adicionar à inicialização automática",
        "hotkeys_button": "Configurar atalhos", "tray_button": "Minimizar para a bandeja", "exit_button": "Sair",
        "hotkey_filter_line": "{hotkey} — ativar/desativar filtro", "hotkey_autostart_line": "{hotkey} — ativar/desativar inicialização automática",
        "tray_hint": "A janela pode ser minimizada para a bandeja do sistema (perto do relógio).",
        "filter_hotkey_failed": "o atalho do filtro não está registrado", "autostart_hotkey_failed": "o atalho de inicialização automática não está registrado",
        "warning_prefix": "Aviso: ", "menu_open": "Abrir janela", "menu_toggle_filter": "Alternar filtro", "menu_exit": "Sair",
        "hotkey_dialog_title": "Configuração de atalhos", "hotkey_dialog_help": "Escolha uma ação e pressione a combinação desejada.\nÉ necessária pelo menos uma tecla modificadora: Ctrl, Alt ou Shift.",
        "action_filter": "Ativar/desativar filtro", "action_autostart": "Ativar/desativar inicialização automática", "change_button": "Alterar",
        "record_prompt": "Para «{action}», pressione uma combinação de teclas...", "unassignable_key": "Não foi possível atribuir esta tecla. Tente outra.",
        "need_modifier": "Adicione Ctrl, Alt ou Shift e pressione a tecla novamente.", "assigned_hint": "Atribuído: {hotkey}. Clique em «Salvar».",
        "save_button": "Salvar", "cancel_button": "Cancelar", "duplicate_hotkey_title": "Configuração de atalhos",
        "duplicate_hotkey_error": "O filtro e a inicialização automática devem usar combinações diferentes.",
        "hotkey_conflict_title": "Não foi possível registrar os atalhos", "hotkey_conflict_filter": "Filtro ({hotkey})", "hotkey_conflict_autostart": "Inicialização automática ({hotkey})",
        "hotkey_conflict_body": "Estas combinações já são usadas por outro aplicativo ou pelo Windows:\n\n{failed}\n\nAs configurações anteriores foram restauradas.",
        "save_error_title": "Erro ao salvar", "save_error_body": "Não foi possível salvar as configurações:\n{error}\n\nAs configurações anteriores foram restauradas.",
        "autostart_error_title": "Inicialização automática", "autostart_error_body": "Não foi possível alterar a inicialização automática:\n{error}",
        "startup_library_title": "Dependências ausentes", "startup_library_body": "A bandeja do sistema requer pystray e Pillow.\nInstale no CMD com: pip install pystray Pillow",
        "windows_only": "Este script funciona apenas no Windows.", "python_64bit": "É necessário Python de 64 bits.",
    },
    "de": {
        "app_title": "Bildschirm-Farbkorrektur", "language_label": "Sprache:",
        "filter_enabled": "Filter: EIN", "filter_disabled": "Filter: AUS",
        "filter_off_button": "Filter ausschalten", "filter_on_button": "Filter einschalten",
        "autostart_added": "Autostart: aktiviert", "autostart_not_added": "Autostart: deaktiviert",
        "autostart_remove_button": "Aus Autostart entfernen", "autostart_add_button": "Zum Autostart hinzufügen",
        "hotkeys_button": "Tastenkürzel einstellen", "tray_button": "In Infobereich minimieren", "exit_button": "Beenden",
        "hotkey_filter_line": "{hotkey} — Filter umschalten", "hotkey_autostart_line": "{hotkey} — Autostart umschalten",
        "tray_hint": "Das Fenster kann in den Infobereich (neben der Uhr) minimiert werden.",
        "filter_hotkey_failed": "Filter-Tastenkürzel nicht registriert", "autostart_hotkey_failed": "Autostart-Tastenkürzel nicht registriert",
        "warning_prefix": "Achtung: ", "menu_open": "Fenster öffnen", "menu_toggle_filter": "Filter umschalten", "menu_exit": "Beenden",
        "hotkey_dialog_title": "Tastenkürzel einstellen", "hotkey_dialog_help": "Wähle eine Aktion und drücke die gewünschte Tastenkombination.\nMindestens eine Zusatztaste ist erforderlich: Strg, Alt oder Umschalt.",
        "action_filter": "Filter ein-/ausschalten", "action_autostart": "Autostart ein-/ausschalten", "change_button": "Ändern",
        "record_prompt": "Drücke für „{action}“ eine Tastenkombination...", "unassignable_key": "Diese Taste konnte nicht zugewiesen werden. Versuche eine andere.",
        "need_modifier": "Drücke zusätzlich Strg, Alt oder Umschalt und versuche es erneut.", "assigned_hint": "Zugewiesen: {hotkey}. Klicke auf „Speichern“.",
        "save_button": "Speichern", "cancel_button": "Abbrechen", "duplicate_hotkey_title": "Tastenkürzel einstellen",
        "duplicate_hotkey_error": "Filter und Autostart müssen unterschiedliche Kombinationen verwenden.",
        "hotkey_conflict_title": "Tastenkürzel konnten nicht registriert werden", "hotkey_conflict_filter": "Filter ({hotkey})", "hotkey_conflict_autostart": "Autostart ({hotkey})",
        "hotkey_conflict_body": "Diese Kombinationen werden bereits von einer anderen Anwendung oder Windows verwendet:\n\n{failed}\n\nDie bisherigen Einstellungen wurden beibehalten.",
        "save_error_title": "Speicherfehler", "save_error_body": "Einstellungen konnten nicht gespeichert werden:\n{error}\n\nDie bisherigen Einstellungen wurden wiederhergestellt.",
        "autostart_error_title": "Autostart", "autostart_error_body": "Autostart konnte nicht geändert werden:\n{error}",
        "startup_library_title": "Fehlende Abhängigkeiten", "startup_library_body": "Für den Infobereich werden pystray und Pillow benötigt.\nInstallation per CMD: pip install pystray Pillow",
        "windows_only": "Dieses Skript funktioniert nur unter Windows.", "python_64bit": "64-Bit-Python wird benötigt.",
    },
    "fr": {
        "app_title": "Correction des couleurs de l’écran", "language_label": "Langue :",
        "filter_enabled": "Filtre : ACTIVÉ", "filter_disabled": "Filtre : DÉSACTIVÉ",
        "filter_off_button": "Désactiver le filtre", "filter_on_button": "Activer le filtre",
        "autostart_added": "Démarrage automatique : activé", "autostart_not_added": "Démarrage automatique : désactivé",
        "autostart_remove_button": "Retirer du démarrage automatique", "autostart_add_button": "Ajouter au démarrage automatique",
        "hotkeys_button": "Configurer les raccourcis", "tray_button": "Réduire dans la zone de notification", "exit_button": "Quitter",
        "hotkey_filter_line": "{hotkey} — activer/désactiver le filtre", "hotkey_autostart_line": "{hotkey} — activer/désactiver le démarrage automatique",
        "tray_hint": "La fenêtre peut être réduite dans la zone de notification (près de l’horloge).",
        "filter_hotkey_failed": "le raccourci du filtre n’est pas enregistré", "autostart_hotkey_failed": "le raccourci de démarrage automatique n’est pas enregistré",
        "warning_prefix": "Attention : ", "menu_open": "Ouvrir la fenêtre", "menu_toggle_filter": "Activer/désactiver le filtre", "menu_exit": "Quitter",
        "hotkey_dialog_title": "Configuration des raccourcis", "hotkey_dialog_help": "Choisissez une action et appuyez sur la combinaison souhaitée.\nAu moins une touche de modification est requise : Ctrl, Alt ou Maj.",
        "action_filter": "Activer/désactiver le filtre", "action_autostart": "Activer/désactiver le démarrage automatique", "change_button": "Modifier",
        "record_prompt": "Pour « {action} », appuyez sur une combinaison...", "unassignable_key": "Impossible d’attribuer cette touche. Essayez-en une autre.",
        "need_modifier": "Ajoutez Ctrl, Alt ou Maj puis appuyez de nouveau sur la touche.", "assigned_hint": "Attribué : {hotkey}. Cliquez sur « Enregistrer ».",
        "save_button": "Enregistrer", "cancel_button": "Annuler", "duplicate_hotkey_title": "Configuration des raccourcis",
        "duplicate_hotkey_error": "Le filtre et le démarrage automatique doivent utiliser des combinaisons différentes.",
        "hotkey_conflict_title": "Impossible d’enregistrer les raccourcis", "hotkey_conflict_filter": "Filtre ({hotkey})", "hotkey_conflict_autostart": "Démarrage automatique ({hotkey})",
        "hotkey_conflict_body": "Ces combinaisons sont déjà utilisées par une autre application ou par Windows :\n\n{failed}\n\nLes paramètres précédents ont été conservés.",
        "save_error_title": "Erreur d’enregistrement", "save_error_body": "Impossible d’enregistrer les paramètres :\n{error}\n\nLes paramètres précédents ont été restaurés.",
        "autostart_error_title": "Démarrage automatique", "autostart_error_body": "Impossible de modifier le démarrage automatique :\n{error}",
        "startup_library_title": "Dépendances manquantes", "startup_library_body": "La zone de notification nécessite pystray et Pillow.\nInstallez-les dans CMD avec : pip install pystray Pillow",
        "windows_only": "Ce script fonctionne uniquement sous Windows.", "python_64bit": "Python 64 bits est requis.",
    },
}


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


def read_settings():
    try:
        with open(settings_file(), "r", encoding="utf-8") as file:
            data = json.load(file)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def write_settings(data):
    path = settings_file()
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def load_hotkeys():
    return normalize_hotkeys(read_settings())


def save_hotkeys(hotkeys):
    data = read_settings()
    data.update(hotkeys)
    write_settings(data)


def load_language():
    language = read_settings().get("language", "en")
    return language if language in LANGUAGES else "en"


def save_language(language):
    if language not in LANGUAGES:
        language = "en"
    data = read_settings()
    data["language"] = language
    write_settings(data)


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
        sys.exit("This script only works on Windows.")
    if struct.calcsize("P") == 4 and os.environ.get("PROCESSOR_ARCHITEW6432"):
        sys.exit("64-bit Python is required.")

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
        self.lang = load_language()

        self.on_effect = to_effect(correction_matrix())
        self.off_effect = to_effect(IDENTITY)
        self.current = (ctypes.c_float * 25)()
        self.enabled = START_ENABLED
        self.last_check = 0.0

        # Окно
        self.root = tk.Tk()
        self.root.title(self.t("app_title"))
        self.root.resizable(False, False)
        
        # Перехватываем закрытие окна на крестик — прячем в трей
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        frm = ttk.Frame(self.root, padding=16)
        frm.pack(fill="both", expand=True)

        language_row = ttk.Frame(frm)
        language_row.pack(fill="x", pady=(0, 10))
        self.language_lbl = ttk.Label(language_row, text=self.t("language_label"))
        self.language_lbl.pack(side="left")
        self.language_var = tk.StringVar(value=LANGUAGES[self.lang])
        self.language_combo = ttk.Combobox(
            language_row, state="readonly", values=list(LANGUAGES.values()),
            textvariable=self.language_var, width=14,
        )
        self.language_combo.pack(side="right")
        self.language_combo.bind("<<ComboboxSelected>>", self.change_language)

        self.filter_lbl = ttk.Label(frm, font=("Segoe UI", 12, "bold"))
        self.filter_lbl.pack(anchor="w")
        self.auto_lbl = ttk.Label(frm)
        self.auto_lbl.pack(anchor="w", pady=(2, 12))

        self.filter_btn = ttk.Button(frm, width=36, command=self.toggle_filter)
        self.filter_btn.pack(fill="x", pady=3)
        self.auto_btn = ttk.Button(frm, width=36, command=self.toggle_autostart_click)
        self.auto_btn.pack(fill="x", pady=3)
        
        self.hotkeys_btn = ttk.Button(frm, text=self.t("hotkeys_button"), command=self.configure_hotkeys)
        self.hotkeys_btn.pack(fill="x", pady=3)
        self.tray_btn = ttk.Button(frm, text=self.t("tray_button"), command=self.hide_to_tray)
        self.tray_btn.pack(fill="x", pady=3)
        self.exit_btn = ttk.Button(frm, text=self.t("exit_button"), command=self.quit)
        self.exit_btn.pack(fill="x", pady=3)

        self.hotkey_lbl = ttk.Label(
            frm, foreground="#666", justify="left", wraplength=320,
        )
        self.hotkey_lbl.pack(anchor="w", pady=(10, 0))

        # Иконка в системном трее
        menu = self.build_tray_menu()
        self.tray_icon = pystray.Icon("ColorCorrection", create_tray_icon(), self.t("app_title"), menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

        self.apply()
        self.start_hotkeys()

        self.refresh()
        if minimized:
            self.hide_to_tray()
            
        self.root.after(100, self.tick)

    def t(self, key, **kwargs):
        """Получить перевод текущего языка с английским резервным вариантом."""
        template = TRANSLATIONS.get(self.lang, TRANSLATIONS["en"]).get(
            key, TRANSLATIONS["en"].get(key, key))
        return template.format(**kwargs) if kwargs else template

    def build_tray_menu(self):
        return pystray.Menu(
            pystray.MenuItem(self.t("menu_open"), self.show),
            pystray.MenuItem(self.t("menu_toggle_filter"), self.toggle_filter),
            pystray.MenuItem(self.t("menu_exit"), self.quit),
        )

    def change_language(self, _event=None):
        self.lang = LANGUAGE_CODES.get(self.language_var.get(), "en")
        try:
            save_language(self.lang)
        except OSError as exc:
            messagebox.showerror(
                self.t("save_error_title"), self.t("save_error_body", error=exc),
                parent=self.root,
            )
        self.update_language()

    def update_language(self):
        self.root.title(self.t("app_title"))
        self.language_lbl.config(text=self.t("language_label"))
        self.hotkeys_btn.config(text=self.t("hotkeys_button"))
        self.tray_btn.config(text=self.t("tray_button"))
        self.exit_btn.config(text=self.t("exit_button"))
        if hasattr(self, "tray_icon"):
            try:
                self.tray_icon.title = self.t("app_title")
                self.tray_icon.menu = self.build_tray_menu()
                self.tray_icon.update_menu()
            except (AttributeError, RuntimeError):
                # Не прерываем работу приложения, если backend трея не поддерживает обновление меню.
                pass
        self.refresh()

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
        dialog.title(self.t("hotkey_dialog_title"))
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frm = ttk.Frame(dialog, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(
            frm,
            text=self.t("hotkey_dialog_help"),
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        pending = {name: dict(value) for name, value in self.hotkeys.items()}
        labels = {}
        recording = {"action": None}
        hint = tk.StringVar(value="")
        actions = (
            ("filter", self.t("action_filter")),
            ("autostart", self.t("action_autostart")),
        )

        for row, (action, title) in enumerate(actions, start=1):
            ttk.Label(frm, text=title).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            labels[action] = ttk.Label(frm, text=hotkey_name(pending[action]), width=18)
            labels[action].grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)

            def begin_recording(name=action):
                recording["action"] = name
                hint.set(self.t("record_prompt", action=dict(actions)[name]))
                dialog.focus_force()

            ttk.Button(frm, text=self.t("change_button"), command=begin_recording).grid(
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
                hint.set(self.t("unassignable_key"))
                return "break"
            if not mods:
                hint.set(self.t("need_modifier"))
                return "break"

            pending[action] = {"mods": mods, "vk": vk}
            labels[action].config(text=hotkey_name(pending[action]))
            recording["action"] = None
            hint.set(self.t("assigned_hint", hotkey=hotkey_name(pending[action])))
            return "break"

        dialog.bind("<KeyPress>", on_keypress)

        def save_and_close():
            if (pending["filter"]["mods"], pending["filter"]["vk"]) == (
                    pending["autostart"]["mods"], pending["autostart"]["vk"]):
                messagebox.showerror(
                    self.t("duplicate_hotkey_title"),
                    self.t("duplicate_hotkey_error"),
                    parent=dialog,
                )
                return

            old_hotkeys = {name: dict(value) for name, value in self.hotkeys.items()}
            self.stop_hotkeys()
            self.hotkeys = {name: dict(value) for name, value in pending.items()}
            self.start_hotkeys()

            failed = []
            if not self.hk_info.get("filter_ok"):
                failed.append(self.t("hotkey_conflict_filter", hotkey=hotkey_name(self.hotkeys["filter"])))
            if not self.hk_info.get("autostart_ok"):
                failed.append(self.t("hotkey_conflict_autostart", hotkey=hotkey_name(self.hotkeys["autostart"])))
            if failed:
                self.stop_hotkeys()
                self.hotkeys = old_hotkeys
                self.start_hotkeys()
                self.refresh()
                messagebox.showerror(
                    self.t("hotkey_conflict_title"),
                    self.t("hotkey_conflict_body", failed="\n".join(failed)),
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
                    self.t("save_error_title"),
                    self.t("save_error_body", error=exc),
                    parent=dialog,
                )
                return
            self.refresh()
            dialog.destroy()

        buttons = ttk.Frame(frm)
        buttons.grid(row=4, column=0, columnspan=3, sticky="e", pady=(2, 0))
        ttk.Button(buttons, text=self.t("save_button"), command=save_and_close).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text=self.t("cancel_button"), command=dialog.destroy).pack(side="right")

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
            self.filter_lbl.config(text=self.t("filter_enabled"), foreground="#1a7f37")
            self.filter_btn.config(text=self.t("filter_off_button"))
        else:
            self.filter_lbl.config(text=self.t("filter_disabled"), foreground="#b42318")
            self.filter_btn.config(text=self.t("filter_on_button"))
        if autostart_enabled():
            self.auto_lbl.config(text=self.t("autostart_added"))
            self.auto_btn.config(text=self.t("autostart_remove_button"))
        else:
            self.auto_lbl.config(text=self.t("autostart_not_added"))
            self.auto_btn.config(text=self.t("autostart_add_button"))

        hk_lines = [
            self.t("hotkey_filter_line", hotkey=hotkey_name(self.hotkeys["filter"])),
            self.t("hotkey_autostart_line", hotkey=hotkey_name(self.hotkeys["autostart"])),
            self.t("tray_hint"),
        ]
        failed = []
        if not self.hk_info.get("filter_ok", True):
            failed.append(self.t("filter_hotkey_failed"))
        if not self.hk_info.get("autostart_ok", True):
            failed.append(self.t("autostart_hotkey_failed"))
        if failed:
            hk_lines.append(self.t("warning_prefix") + "; ".join(failed) + ".")
        self.hotkey_lbl.config(text="\\n".join(hk_lines))

    def toggle_filter(self):
        self.enabled = not self.enabled
        self.apply()
        self.refresh()

    def toggle_autostart_click(self):
        try:
            toggle_autostart()
        except OSError as e:
            messagebox.showerror(
                self.t("autostart_error_title"),
                self.t("autostart_error_body", error=e),
                parent=self.root,
            )
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
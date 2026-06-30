#!/usr/bin/env python3
"""Telegram bot for TG WS Proxy management (multi-proxy)."""

import json
import os
import re
import secrets
import signal
import subprocess
import time
import urllib.error
import urllib.request
from typing import Optional

BOT_TOKEN = os.environ.get("TG_PROXY_BOT_TOKEN", "8671049643:AAHyS07WyKcHkwdp603xTPc7EETpaNbYci0")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
LOCAL_IP = "192.168.0.231"

PROXIES = {
    1: {"service": "tg-ws-proxy-1", "port": 443},
    2: {"service": "tg-ws-proxy-2", "port": 8443},
    3: {"service": "tg-ws-proxy-3", "port": 9443},
}


def _service_file(name: str) -> str:
    return f"/etc/systemd/system/{name}.service"


def _api(method: str, data: Optional[dict] = None, timeout: int = 10) -> dict:
    url = f"{API}/{method}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read()) if e.fp else {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return -1, "", str(e)


def _get_config(proxy_id: int) -> dict:
    svc = PROXIES[proxy_id]["service"]
    code, out, _ = _run(["systemctl", "show", svc, "--property=ExecStart", "--value"])
    cfg = {"secret": "", "port": PROXIES[proxy_id]["port"], "host": "0.0.0.0", "fake_tls_domain": "www.google.com"}
    if code != 0 or not out:
        return cfg
    for key, pattern, cast in [
        ("secret", r'--secret\s+(\S+)', str),
        ("port", r'--port\s+(\d+)', int),
        ("host", r'--host\s+(\S+)', str),
        ("fake_tls_domain", r'--fake-tls-domain\s+(\S+)', str),
    ]:
        m = re.search(pattern, out)
        if m:
            cfg[key] = cast(m.group(1))
    return cfg


def _get_status(proxy_id: int) -> str:
    svc = PROXIES[proxy_id]["service"]
    code, out, _ = _run(["systemctl", "is-active", svc])
    return out if code == 0 else "stopped"


def _get_public_ip() -> str:
    try:
        req = urllib.request.Request("https://ifconfig.me", headers={"User-Agent": "curl"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode().strip()
    except Exception:
        return "?"


def _domain_hex(domain: str) -> str:
    return domain.encode("ascii").hex()


def build_link(cfg: dict, server_ip: str) -> str:
    secret = cfg["secret"]
    port = cfg["port"]
    tls_domain = cfg.get("fake_tls_domain", "")
    domain_hex = _domain_hex(tls_domain) if tls_domain else ""
    if tls_domain:
        return f"tg://proxy?server={server_ip}&port={port}&secret=ee{secret}{domain_hex}"
    else:
        return f"tg://proxy?server={server_ip}&port={port}&secret=dd{secret}"


def _update_service_secret(proxy_id: int, new_secret: str) -> bool:
    svc = PROXIES[proxy_id]["service"]
    path = _service_file(svc)
    try:
        r = subprocess.run(["sudo", "-n", "cat", path], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return False
        content = re.sub(r'--secret\s+\S+', f'--secret {new_secret}', r.stdout)
        r = subprocess.run(["sudo", "-n", "tee", path], input=content, capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _send(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    _api("sendMessage", payload)


def _answer_callback(callback_id: int, text: str = "") -> None:
    _api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def _edit(chat_id: int, message_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    _api("editMessageText", payload)


# --- Menus ---

def _proxy_menu() -> dict:
    lines = []
    btns = []
    for pid, info in PROXIES.items():
        status = _get_status(pid)
        icon = "+" if status == "active" else "-"
        lines.append(f"{icon} Прокси {pid}: порт {info['port']} [{status}]")
        btns.append([{"text": f"Прокси {pid} ({info['port']})", "callback_data": f"select_{pid}"}])
    return "\n".join(lines), {"inline_keyboard": btns}


def _action_menu(proxy_id: int) -> dict:
    svc = PROXIES[proxy_id]["service"]
    port = PROXIES[proxy_id]["port"]
    return {
        "inline_keyboard": [
            [{"text": f"Получить ссылку", "callback_data": f"link_{proxy_id}"}],
            [{"text": "Локальная ссылка", "callback_data": f"local_{proxy_id}"}],
            [{"text": "Статус", "callback_data": f"stat_{proxy_id}"},
             {"text": "Конфигурация", "callback_data": f"conf_{proxy_id}"}],
            [{"text": "Перезапустить", "callback_data": f"rst_{proxy_id}"},
             {"text": "Новый секрет", "callback_data": f"sec_{proxy_id}"}],
            [{"text": "Назад", "callback_data": "back"}],
        ]
    }


# --- Callbacks ---

def cb_select(proxy_id: int, chat_id: int, message_id: int) -> None:
    cfg = _get_config(proxy_id)
    status = _get_status(proxy_id)
    _edit(chat_id, message_id,
        f"Прокси {proxy_id} | Порт {cfg['port']} | {status}",
        _action_menu(proxy_id)
    )


def cb_link(proxy_id: int, chat_id: int, message_id: int) -> None:
    cfg = _get_config(proxy_id)
    ip = _get_public_ip()
    _edit(chat_id, message_id,
        f"Прокси {proxy_id} (порт {cfg['port']})\n\n{build_link(cfg, ip)}",
        _action_menu(proxy_id)
    )


def cb_local(proxy_id: int, chat_id: int, message_id: int) -> None:
    cfg = _get_config(proxy_id)
    _edit(chat_id, message_id,
        f"Прокси {proxy_id} (порт {cfg['port']})\n\n{build_link(cfg, LOCAL_IP)}",
        _action_menu(proxy_id)
    )


def cb_stat(proxy_id: int, chat_id: int, message_id: int) -> None:
    cfg = _get_config(proxy_id)
    status = _get_status(proxy_id)
    ip = _get_public_ip()
    _edit(chat_id, message_id,
        f"Прокси {proxy_id}\n"
        f"Статус: {status}\n"
        f"Порт: {cfg['port']}\n"
        f"Fake TLS: {cfg.get('fake_tls_domain', '-')}\n"
        f"IP: {ip}",
        _action_menu(proxy_id)
    )


def cb_conf(proxy_id: int, chat_id: int, message_id: int) -> None:
    cfg = _get_config(proxy_id)
    _edit(chat_id, message_id,
        f"Прокси {proxy_id}\n"
        f"Секрет: {cfg['secret']}\n"
        f"Порт: {cfg['port']}\n"
        f"Хост: {cfg['host']}\n"
        f"Fake TLS: {cfg.get('fake_tls_domain', '-')}",
        _action_menu(proxy_id)
    )


def cb_rst(proxy_id: int, chat_id: int, message_id: int) -> None:
    svc = PROXIES[proxy_id]["service"]
    _edit(chat_id, message_id, f"Перезапуск прокси {proxy_id}...", _action_menu(proxy_id))
    code, _, err = _run(["sudo", "-n", "systemctl", "restart", svc], timeout=15)
    if code == 0:
        _send(chat_id, f"Прокси {proxy_id} перезапущен", _action_menu(proxy_id))
    else:
        _send(chat_id, f"Ошибка: {err}", _action_menu(proxy_id))


def cb_sec(proxy_id: int, chat_id: int, message_id: int) -> None:
    new_secret = secrets.token_hex(16)
    if not _update_service_secret(proxy_id, new_secret):
        _send(chat_id, "Ошибка записи сервисного файла", _action_menu(proxy_id))
        return
    _edit(chat_id, message_id, f"Новый секрет для прокси {proxy_id}, перезапуск...", _action_menu(proxy_id))
    svc = PROXIES[proxy_id]["service"]
    _run(["sudo", "-n", "systemctl", "daemon-reload"], timeout=5)
    code, _, err = _run(["sudo", "-n", "systemctl", "restart", svc], timeout=15)
    if code == 0:
        cfg = _get_config(proxy_id)
        ip = _get_public_ip()
        _send(chat_id,
            f"Прокси {proxy_id}\n"
            f"Новый секрет: {new_secret}\n\n"
            f"Ссылка:\n{build_link(cfg, ip)}\n\n"
            f"Локальная:\n{build_link(cfg, LOCAL_IP)}",
            _action_menu(proxy_id)
        )
    else:
        _send(chat_id, f"Ошибка перезапуска: {err}", _action_menu(proxy_id))


def cb_back(chat_id: int, message_id: int) -> None:
    text, menu = _proxy_menu()
    _edit(chat_id, message_id, text, menu)


# --- Router ---

def handle_message(msg: dict) -> None:
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()
    if text in ("/start", "/help"):
        text, menu = _proxy_menu()
        _send(chat_id, text, menu)


def handle_callback(cb: dict) -> None:
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    data = cb.get("data", "")
    _answer_callback(cb["id"])

    if data == "back":
        cb_back(chat_id, message_id)
    elif data.startswith("select_"):
        cb_select(int(data.split("_")[1]), chat_id, message_id)
    elif data.startswith("link_"):
        cb_link(int(data.split("_")[1]), chat_id, message_id)
    elif data.startswith("local_"):
        cb_local(int(data.split("_")[1]), chat_id, message_id)
    elif data.startswith("stat_"):
        cb_stat(int(data.split("_")[1]), chat_id, message_id)
    elif data.startswith("conf_"):
        cb_conf(int(data.split("_")[1]), chat_id, message_id)
    elif data.startswith("rst_"):
        cb_rst(int(data.split("_")[1]), chat_id, message_id)
    elif data.startswith("sec_"):
        cb_sec(int(data.split("_")[1]), chat_id, message_id)


def main() -> None:
    print(f"Bot started, token: {BOT_TOKEN[:10]}...")
    offset = 0
    running = True

    def stop(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while running:
        try:
            resp = _api("getUpdates", {"offset": offset, "timeout": 30}, timeout=35)
            if resp.get("ok") and resp.get("result"):
                for update in resp["result"]:
                    offset = update["update_id"] + 1
                    if "callback_query" in update:
                        handle_callback(update["callback_query"])
                    elif "message" in update:
                        handle_message(update["message"])
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()

# TG WS Proxy — Настройка на Ubuntu

## Требования

- Ubuntu 22.04+ (тестировалось на 24.04)
- Python 3.12+
- Роутер с поддержкой Virtual Server / Port Forwarding (TP-Link и т.д.)
- Доступ к интернету

## 1. Установка

```bash
cd /home/goshik/TG_PROXY

# Создание venv и установка зависимостей
python3 -m venv .venv
.venv/bin/pip install -e .
```

Глобальная команда `tg-ws-proxy` будет доступна через pip install.

## 2. Генерация секрета

```bash
python3 -c "import secrets; print(secrets.token_hex(16))"
```

Сохраните результат — это 32 hex-символа.

## 3. Настройка systemd-сервисов

Создать 3 файла (по одному на каждый прокси):

**`/etc/systemd/system/tg-ws-proxy-1.service`** (порт 443):
```ini
[Unit]
Description=TG WS Proxy (443)
After=network.target

[Service]
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/home/goshik/.local/bin/tg-ws-proxy --host 0.0.0.0 --port 443 --secret <СЕКРЕТ_1> --fake-tls-domain www.google.com
Restart=always
User=goshik

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/tg-ws-proxy-2.service`** (порт 8443):
```ini
[Unit]
Description=TG WS Proxy (8443)
After=network.target

[Service]
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/home/goshik/.local/bin/tg-ws-proxy --host 0.0.0.0 --port 8443 --secret <СЕКРЕТ_2> --fake-tls-domain www.google.com
Restart=always
User=goshik

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/tg-ws-proxy-3.service`** (порт 9443):
```ini
[Unit]
Description=TG WS Proxy (9443)
After=network.target

[Service]
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/home/goshik/.local/bin/tg-ws-proxy --host 0.0.0.0 --port 9443 --secret <СЕКРЕТ_3> --fake-tls-domain www.google.com
Restart=always
User=goshik

[Install]
WantedBy=multi-user.target
```

> `AmbientCapabilities=CAP_NET_BIND_SERVICE` позволяет слушать привилегированные порты (443) без root-прав.

Запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable tg-ws-proxy-1 tg-ws-proxy-2 tg-ws-proxy-3
sudo systemctl start tg-ws-proxy-1 tg-ws-proxy-2 tg-ws-proxy-3
```

## 4. Настройка роутера (TP-Link)

**Advanced → NAT Forwarding → Virtual Servers**

| ID | Service Type | External Port | Internal IP | Internal Port | Protocol | Status |
|----|-------------|---------------|-------------|---------------|----------|--------|
| 1 | tg-proxy | 443 | 192.168.0.231 | 443 | TCP | Enabled |
| 2 | tg-proxy_2 | 8443 | 192.168.0.231 | 8443 | TCP | Enabled |
| 3 | tg-proxy_3 | 9443 | 192.168.0.231 | 9443 | TCP | Enabled |

> **Важно:** External Port и Internal Port должны совпадать!

## 5. Ссылка для подключения

```
tg://proxy?server=<ПУБЛИЧНЫЙ_IP>&port=443&secret=ee<СЕКРЕТ><HEX_ДОМЕНА>
```

Где:
- `<ПУБЛИЧНЫЙ_IP>` — WAN IP роутера (виден на странице статуса)
- `<СЕКРЕТ>` — 32 hex-символа
- `<HEX_ДОМЕНА>` — hex-код домена из `--fake-tls-domain` (для `www.google.com`: `77777772e676f6f676c652e636f6d`)

**Текущая конфигурация (3 прокси):**

| Прокси | Порт | Ссылка |
|--------|------|--------|
| 1 | 443 | `tg://proxy?server=<IP>&port=443&secret=ee<СЕКРЕТ>7777772e676f6f676c652e636f6d` |
| 2 | 8443 | `tg://proxy?server=<IP>&port=8443&secret=ee<СЕКРЕТ>7777772e676f6f676c652e636f6d` |
| 3 | 9443 | `tg://proxy?server=<IP>&port=9443&secret=ee<СЕКРЕТ>7777772e676f6f676c652e636f6d` |

> Ссылки генерируются ботом: [@tgproxy_polo_bot](https://t.me/tgproxy_polo_bot) → Прокси → Получить ссылку

## 6. Проверка

```bash
# Статус всех прокси
systemctl status tg-ws-proxy-1 tg-ws-proxy-2 tg-ws-proxy-3

# Логи конкретного прокси
journalctl -u tg-ws-proxy-1 -f

# Проверка порта извне
curl -s "https://ports.yougetsignal.com/check-port.php" -d "remoteAddress=178.141.9.234&portNumber=8443"
```

---

## Проблема от 30.06.2026 и её решение

### Симптомы

- Прокси запущен, слушает `0.0.0.0:443`
- Локально отвечает (`192.168.0.231:443` работает)
- Внешнее подключение по публичному IP не проходит
- Порт 443 закрыт снаружи (проверено внешним сервисом)

### Причины (по порядку)

1. **Прокси слушал на `127.0.0.1`** — не принимал внешние подключения
2. **Нет Fake TLS** — протокол `dd` (obfuscated2) легко блокируется DPI
3. **Неправильный External Port** — было 1443, нужно 443
4. **CGNAT** — провайдер выдавал IP из диапазона CGNAT (`178.141.244.23`), порты не пробрасываются
5. **Virtual Server vs Port Forwarding** — на TP-Link проброс портов называется "Virtual Servers", не "Port Forwarding"

### Что было сделано

1. Прокси перезапущен с `--host 0.0.0.0` (приём на всех интерфейсах)
2. Добавлен `--fake-tls-domain www.google.com` (маскировка под HTTPS)
3. Порт сменён на 443 (раньше работал на этом порту)
4. Добавлено `AmbientCapabilities=CAP_NET_BIND_SERVICE` в systemd (для порта 443 без root)
5. Обратились в техподдержку провайдера → получили белый PPPoE IP (`178.141.9.234`)
6. На роутере TP-Link настроены **Virtual Servers**: External 443 → Internal 192.168.0.231:443/TCP

### Итог

Прокси работает через роутер на порту 443 с Fake TLS. Ссылка генерируется автоматически при запуске.

---

## Telegram Bot

Бот: [@tgproxy_polo_bot](https://t.me/tgproxy_polo_bot)

### Проблема: bot не отвечал на команды

**Причина:** DNS `api.telegram.org` заблокирован в России. Бот не мог подключиться к Telegram API.

**Решение:** Добавлена запись в `/etc/hosts` напрямую на IP Telegram:
```
149.154.167.220 api.telegram.org
```

> После смены IP провайдера или обновления серверов Telegram может потребоваться обновить IP в `/etc/hosts`.

### Установка

```bash
# Создать venv (если ещё нет)
cd /home/goshik/TG_PROXY
python3 -m venv .venv
.venv/bin/pip install -e .

# Добавить запись в hosts (если ещё нет)
grep -q "api.telegram.org" /etc/hosts || echo "149.154.167.220 api.telegram.org" | sudo tee -a /etc/hosts

# Создать systemd-сервис
sudo tee /etc/systemd/system/tg-proxy-bot.service > /dev/null << 'EOF'
[Unit]
Description=TG Proxy Bot
After=network.target tg-ws-proxy.service

[Service]
ExecStart=/home/goshik/TG_PROXY/.venv/bin/python3 /home/goshik/TG_PROXY/bot.py
Restart=always
User=goshik
Environment=TG_PROXY_BOT_TOKEN=<ТОКЕН_БОТА>

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable tg-proxy-bot
sudo systemctl start tg-proxy-bot
```

### Команды бота

- `/proxy` — ссылка для подключения (публичный IP)
- `/local` — локальная ссылка (192.168.0.x)
- `/status` — статус прокси и текущий IP
- `/config` — текущая конфигурация (секрет, порт, домен)

---

## Полезные команды

```bash
# Все прокси
sudo systemctl restart tg-ws-proxy-1 tg-ws-proxy-2 tg-ws-proxy-3
sudo systemctl stop tg-ws-proxy-1 tg-ws-proxy-2 tg-ws-proxy-3
systemctl status tg-ws-proxy-1 tg-ws-proxy-2 tg-ws-proxy-3

# Один прокси
sudo systemctl restart tg-ws-proxy-2
journalctl -u tg-ws-proxy-2 -f

# Бот
sudo systemctl restart tg-proxy-bot
journalctl -u tg-proxy-bot -f

# Сеть
curl -s ifconfig.me          # текущий публичный IP
ss -tlnp | grep 443          # проверка listening портов
```

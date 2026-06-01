# Развертывание На Bazzite

[English version](BAZZITE.md)

Bazzite поддерживается как целевая система для CS2 WebUI. Контейнерная модель
Bazzite подходит проекту: панель и CS2-инстансы запускаются через Podman, а
Quadlet связывает контейнеры с systemd.

Установщик определяет `ID=bazzite` из `/etc/os-release` и использует:

```text
/var/opt/cs2webui       код приложения
/var/lib/cs2webui       настройки и CS2-инстансы
/var/lib/cs2webui-system root-owned helper-файлы и состояние Caddy
```

Базовый образ операционной системы не изменяется. Установщик не вызывает
`rpm-ostree`.

## Требования

Запускайте bootstrap в Desktop Mode. На хосте должны быть доступны:

```text
podman
systemd
ss
loginctl
python3
поддержка python3 venv
git
```

Если обязательного инструмента нет, установщик остановится с понятной ошибкой.

## Установка

```bash
curl -fsSL https://raw.githubusercontent.com/feicap/cs2webui/main/cs2webui.sh \
  -o cs2webui.sh
less cs2webui.sh
sudo bash cs2webui.sh
```

После установки откройте временную ссылку из терминала и продолжите настройку
в браузере. На последнем экране мастер покажет управляемую команду для
IP-доступа или домена. В режиме домена Caddy запускается через системный
rootful Quadlet, а панель и CS2-инстансы продолжают использовать rootless
Podman.

После установки запустите read-only отчет хоста:

```bash
sudo bash /var/opt/cs2webui/scripts/verify-linux.sh
```

Общие volume панели, host-agent и CS2-инстансов используют общую SELinux-метку
Podman (`:z`). Состояние Caddy остается приватным для контейнера Caddy (`:Z`).

## Удаление

Обычное удаление убирает сервисы и код приложения, но сохраняет настройки
панели и CS2-инстансы:

```bash
sudo bash /var/opt/cs2webui/scripts/uninstall.sh
```

Используйте `--purge-all`, только если нужно удалить также данные панели,
CS2-инстансы и отдельную rootless Podman-учетную запись. Скрипт потребует
явные текстовые подтверждения.

## Статус Проверки

Профиль Bazzite реализован, но еще должен быть проверен на реальном
Bazzite-хосте. Результаты фиксируются в
[LINUX_INTEGRATION.md](LINUX_INTEGRATION.md).

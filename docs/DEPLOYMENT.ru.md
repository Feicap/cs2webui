# Развертывание На Linux

[English version](DEPLOYMENT.md)

CS2 WebUI предназначен для Linux-хоста с systemd и Podman. Текущие скрипты
являются первым вариантом развертывания и должны быть проверены на реальном
Linux-хосте перед использованием в production.

## Требования

- Debian 12 или актуальная Ubuntu LTS;
- `systemd`;
- `podman`;
- `ss` из пакета `iproute2`;
- `loginctl`;
- root-доступ для первоначальной установки.

Для каждого изолированного CS2-инстанса зарезервируйте не менее `65 GB` плюс
место под backup. Valve указывает для CS2 Linux `glibc 2.31+` и CPU уровня
`x86-64-v2` с POPCNT/SSE4.2. Игровой контейнер использует Debian 12 и запускает
скачанный сервер через `game/cs2.sh`.

Источник Valve:
[Counter-Strike 2 - Dedicated Servers](https://developer.valvesoftware.com/wiki/Counter-Strike_2/Dedicated_Servers).

## Установка Из Репозитория

```bash
git clone https://github.com/feicap/cs2webui.git
cd cs2webui
sudo bash scripts/install.sh
```

Минимальный bootstrap из GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/feicap/cs2webui/main/cs2webui.sh \
  -o cs2webui.sh
less cs2webui.sh
sudo bash cs2webui.sh
```

Скрипт создает сервисного пользователя, собирает контейнер панели через
rootless Podman, устанавливает пользовательский Quadlet unit, выбирает первый
свободный TCP-порт начиная с `8080` и выводит временную ссылку на WebUI.
Постоянные настройки и игровые данные хранятся в `/var/lib/cs2webui`, а
root-owned helper-файлы для внешнего доступа отдельно в
`/var/lib/cs2webui-system`.

После установки запустите read-only отчет проверки Linux:

```bash
sudo bash /opt/cs2webui/scripts/verify-linux.sh
```

На Bazzite используйте `/var/opt/cs2webui/scripts/verify-linux.sh`. Отчет
проверяет зависимости хоста, требования Valve к CPU и диску, bash-синтаксис,
rootless Podman-образы, пользовательские сервисы и сокет ограниченного агента.

## Удаление Панели

```bash
sudo bash /opt/cs2webui/scripts/uninstall.sh
```

Обычное удаление убирает код панели и ее сервис, но сохраняет:

```text
/var/lib/cs2webui/instances
/var/lib/cs2webui/panel
```

Это сделано намеренно: игровые серверы CS2 и настройки панели не должны
удаляться без отдельного явного действия пользователя.

Удаление настроек панели:

```bash
sudo bash /opt/cs2webui/scripts/uninstall.sh --purge-panel-data
```

Удаление игровых инстансов требует отдельного флага и ручного подтверждения:

```bash
sudo bash /opt/cs2webui/scripts/uninstall.sh --purge-panel-data --purge-instances
```

Для полного удаления всех управляемых данных, выделенного service-user и его
rootless Podman storage используйте:

```bash
sudo bash /opt/cs2webui/scripts/uninstall.sh --purge-all
```

Этот режим требует текстовых подтверждений перед удалением CS2-файлов и перед
удалением service-user.

## Сборка Опционального Bridge-Плагина

Расширенный список игроков и автоматическая Workshop-ротация после завершения
матча используют опциональный CounterStrikeSharp bridge. Установщик пытается
собрать архив автоматически, но ошибка не прерывает установку панели.
Повторная ручная сборка на Linux-хосте через Podman:

```bash
bash /opt/cs2webui/scripts/build-bridge.sh
```

Скрипт использует контейнер .NET 8 SDK и создает:

```text
/var/lib/cs2webui/imports/cs2webui-bridge.zip
```

Мастер инстанса предлагает MetaMod, CounterStrikeSharp и bridge как
рекомендуемые опции. После успешного выполнения SteamCMD панель получает
latest Linux-архив MetaMod и latest CounterStrikeSharp `with-runtime` из
официальных API релизов, устанавливает выбранные prerequisites и добавляет
готовый bridge-архив, если он доступен. Те же действия можно выполнить вручную
на экране **Plugins**. Перезапустите CS2-сервер и проверьте `meta list` через
консоль. Без опциональных компонентов панель продолжает работать через A2S и
RCON.

## Установка Локального Архива Или Папки Плагина

Поместите доверенный ZIP-архив или распакованную папку плагина внутрь:

```text
/var/lib/cs2webui/imports
```

На экране **Plugins** выберите **Managed local archive / folder** и укажите
относительное имя, например `simpleadmin.zip` или `simpleadmin-release`.
Панель проверяет пути архива, отклоняет символические ссылки и конфликтующие
файлы, а также ограничивает размер распаковки перед копированием файлов в
выбранный инстанс. Для доверенных релизов доступна и установка HTTPS-архива.

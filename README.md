# VaultDrop

**Українська** · [English](README.en.md)

[![Release](https://img.shields.io/github/v/release/Galactic717/VaultDrop)](https://github.com/Galactic717/VaultDrop/releases/latest)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D6)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Офлайн-копії папок для Windows із перевіркою кожного файла читанням із диска.

![Демонстрація роботи VaultDrop](docs/demo.gif)

## Завантаження

Готові збірки — на сторінці [Releases](https://github.com/Galactic717/VaultDrop/releases/latest):

- **Установлення:** [`VaultDrop_0.2.0_x64-setup.exe`](https://github.com/Galactic717/VaultDrop/releases/latest/download/VaultDrop_0.2.0_x64-setup.exe).
- **Без установлення:** [`VaultDrop-0.2.0-portable.zip`](https://github.com/Galactic717/VaultDrop/releases/latest/download/VaultDrop-0.2.0-portable.zip) — розпакуй повністю й запусти `VaultDrop Desktop.exe`. Поруч повинен залишатися `vaultdrop.exe` — ядро копіювання.
- **Лише командний рядок:** [`vaultdrop.exe`](https://github.com/Galactic717/VaultDrop/releases/latest/download/vaultdrop.exe).
- Контрольні суми — `SHA256SUMS.txt` у тому ж релізі.

## Скріншоти

| Нова копія | Прогрес |
|---|---|
| ![Вибір джерела й дисків](docs/screenshots/backup-uk.png) | ![Копіювання з перевіркою](docs/screenshots/progress-uk.png) |
| **Результат** | **Перевірка копії** |
| ![Результат копіювання](docs/screenshots/result-uk.png) | ![Перевірка наявної копії](docs/screenshots/verify-uk.png) |
| **Пошкоджена копія** | **Компактне вікно** |
| ![Виявлено змінений файл](docs/screenshots/native-damaged-uk.png) | ![Вузьке вікно](docs/screenshots/compact-uk.png) |

Windows 10/11 x64 із WebView2; фактично перевірено на Windows 11. Інсталятор і виконувані файли не підписані. У застосунку немає хмари, акаунтів або доступу до інтернету.

## Як користуватися

1. Вибери папку-джерело. Програма порахує файли та обсяг.
2. Обери один чи два диски або власну папку для копії. Праворуч видно підсумок і точні шляхи.
3. Натисни **Почати копіювання**. VaultDrop записує файли, перечитує їх в обхід кешу Windows і порівнює контрольні суми.
4. Перевір результат. Неповна або зупинена операція не позначається успішною. Важливі файли варто тримати ще на одному незалежному носії.
5. Перед від’єднанням диска скористайся безпечним видаленням Windows.

Вкладка **Перевірити копію** знаходить попередні копії на дисках; також можна вибрати папку вручну. Перевірка не змінює файли в копії. Якщо початкове копіювання було неповним чи перерваним, перевірка це повідомить, навіть коли всі записані в описі файли цілі.

Кнопка **Зупинити** припиняє операцію. Оригінали залишаються без змін; для завершення неповної копії запусти копіювання повторно. Це повне повторне копіювання, без докачування.

Мови: українська, English, polski, Deutsch, español, français.

## Що змінилося у 0.2

- Повністю новий інтерфейс із підсумком копії, станами дисків, окремими екранами перевірки, прогресу та результатів.
- Зупинка операції без закриття програми; зрозумілі повідомлення про помилки процесу.
- Виправлено хибний успішний результат для неповної копії та для помилок запису звітів.
- Блокування одночасного запису в одну копію, перевірка шляхів опису, захист від переходу через посилання в папці призначення.
- Виділені модулі керування процесом, перевірки шляхів і представлення результатів; сканування виконується у фонових потоках.
- Попередження перед заміною копії іншого джерела з такою ж назвою папки.

Докладний розбір: [архітектура й реверс-інженерія](docs/ARCHITECTURE.md), [перевірки](docs/VALIDATION.md), [межі можливостей](docs/LIMITATIONS.md).

## Командний рядок

```powershell
.\dist\vaultdrop.exe copy --source 'D:\Photos' --to 'E:\Backup\Photos' --lang uk
.\dist\vaultdrop.exe copy --source 'D:\Photos' --to 'E:\Photos' --to 'F:\Photos'
.\dist\vaultdrop.exe verify --target 'E:\Backup\Photos' --lang uk
```

`--to` можна повторити двічі; шлях може містити кому. `--json` вмикає JSON Lines. Коди виходу: `0` — успіх, `1` — неповна/пошкоджена копія, `2` — помилка виконання. Старий рядок `SAFE TO FORMAT` у машинному звіті збережено для сумісності; він не є гарантією довічного збереження даних. Verify повертає `INTACT`, `DAMAGED` або `INCOMPLETE`.

## Файли в копії

| Файл | Призначення |
|---|---|
| `.vaultdrop.json` і `.vaultdrop.json.xxh64` | Опис скопійованих файлів і контрольна сума опису |
| `vaultdrop-report.txt` / `.json` | Підсумок останнього копіювання |
| `vaultdrop-incident.txt` / `.json` | Причини помилок |
| `.vaultdrop.running` | Незавершене копіювання або запис службових даних |
| `.vaultdrop.lock` | Постійний службовий файл; блокування активне лише під час запису |

Старі зайві файли у копії не видаляються. Посилання та junction не копіюються. Деталі — в обмеженнях.

## Розробка та збірка

Потрібні Python 3.12+, Rust MSVC, Visual Studio Build Tools, Node.js і Microsoft Edge для браузерних тестів.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e '.[dev]'
powershell -NoProfile -ExecutionPolicy Bypass -File build.ps1
```

Скрипт проганяє Python- і JavaScript-тести, браузерні сценарії, збирає CLI, Tauri-застосунок, NSIS-інсталятор і portable ZIP. Артефакти та SHA256SUMS.txt лежать у `dist`.

Окремі перевірки:

```powershell
.venv\Scripts\python -m pytest -q
npm --prefix src-app ci
npm --prefix src-app test
npm --prefix src-app run test:ui
```

Структура: `src-core/vaultdrop` — ядро, `src-app/ui` — інтерфейс, `src-app/src-tauri/src` — Windows-оболонка, `tests` і `src-app/tests` — тести. Переклади єдині для CLI та UI: `src-core/vaultdrop/locales`.


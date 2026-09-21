> Історичний документ версії 0.1. Актуальний стан 0.2: [архітектура](ARCHITECTURE.md), [перевірки](VALIDATION.md), [обмеження](LIMITATIONS.md).

# SPEC VaultDrop MVP — заморожено 21.09.2026
# Будується з нуля. Старі проекти — тільки контекст.

## 1. Сценарії

S1 Ingest: source dir -> dest1 (+dest2 опціонально) -> Start -> report + verdict.
S2 Verify: target dir (колишній dest) -> Verify -> intact/changed/missing по файлах.

## 2. Алгоритм copy (ядро з нуля)

```
for each file in walk(source):
  rel = relative_path(file)
  h1 = xxhash64_stream(read(file, chunks=1MB))
  if mtime changed during read: re-read once, else mark unstable+incident
  for dest in [dest1, dest2]:
    tmp = dest / rel + ".vaultdrop-tmp-<rand>"
    write_stream(file -> tmp)
    h2 = xxhash64_stream(read(tmp from disk))
    if h1 != h2: retry once; if again != : incident[rel]+=dest_fail; continue
    rename(tmp -> dest/rel)
  ledger_entry[rel] = {size, mtime_utc, xxhash64_hex=h1, copied_at_utc}
write .vaultdrop.json + report.json + report.txt in each dest
verdict = SAFE TO FORMAT if all files matched in all dests else FAIL
```

Temp-файли після краху ігноруються при наступному запуску (маска `.vaultdrop-tmp-*`).

## 3. Схема ledger `.vaultdrop.json`

```json
{
  "vaultdrop_version": "0.1.0",
  "created_at_utc": "2026-09-21T10:00:00Z",
  "source_label": "D:\\promin",
  "files": [
    {
      "rel_path": "docs/SPEC.md",
      "size": 12345,
      "mtime_utc": "2026-09-21T09:00:00Z",
      "xxhash64_hex": "9d2a...",
      "copied_at_utc": "2026-09-21T10:01:00Z"
    }
  ]
}
```

`report.json`: {total, ok, failed, skipped_locked, verdict}
`incident.json`: [{rel_path, dest, reason: mismatch/locked/yanked/power, attempts}]

## 4. Обробка відмов

- Висмикнули флешку: write/verify ловить OSError -> incident yanked -> FAIL для цих файлів, прогін продовжується, крашу немає.
- Locked файл: skip + incident locked, не валить прогін.
- 0 байт, кирилиця, пробіли, >260 символів через `\\?\`: підтримуються.
- Файл змінився під час читання: 1 перечитування, інакше unstable.
- Жодного видалення source. Жодного форматування dest кодом.

## 5. Стек і шляхи

- Python 3.12 core, пакети: xxhash. CLI argparse.
- Tauri UI викликає той самий CLI.
- Все на D:\vaultdrop\. Кеші, venv теж D:. ASCII-шляхи.
- Офлайн: запуск з вимкненим Wi-Fi повинен пройти.

## 6. Фази

P0 spec (цей файл + MARKET) — без коду.
P1 core copy+hash + 5 тестів.
P2 verify+ledger + re-verify через зміну 1 байта.
P3 CLI + Tauri 1 екран.
P4 NSIS інсталер + README з гіфкою + реліз .exe.

## 7. Non-goals v1

Шифрування, стиснення, хмара, планувальник, дедуп, macOS/Linux, AI. Заборонено.

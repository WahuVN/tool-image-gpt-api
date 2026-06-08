# TuTien3 Green-Screen Art Commands

Target folder:

```text
D:\TOOL\TOOL Anh\TuTien3
```

This TuTien3 batch draws the full Tu Tien art catalog on opaque pure green-screen PNG backgrounds. It does not remove the green background and does not export transparent alpha.

Full catalog count: 177 PNGs.

- A. Character: 80
- B. Relics: 53
- C. Frame: 11
- D. UI Button: 6
- E. Icon: 14
- F. Background: 5
- G. VFX: 8

## Streamlit tool preset

In the Streamlit app, open `Vẽ art game Tu Tiên Cờ`, then click:

```text
Setup TuTien3 nền xanh lá
```

That preset sets export root to `D:\TOOL\TOOL Anh\TuTien3`, selects all 177 catalog items, enables overwrite, enables green-screen raw mode, and disables the blue-screen alpha-removal workflow.

## One-click batch files

Draw only missing files:

```bat
draw_missing_tutien3_green_art.bat
```

Redraw all 177 files from scratch:

```bat
redraw_all_tutien3_green_art.bat
```

Start redraw-all in a hidden background process and write logs:

```bat
start_redraw_all_tutien3_green_art_background.bat
```

Validate green-screen PNGs and rebuild contact sheets:

```bat
validate_tutien3_green_art.bat
```

## Terminal commands

Open terminal in the repo first:

```bat
cd /d "D:\TOOL\TOOL Anh"
```

List all files still pending without drawing:

```bat
.venv\Scripts\python.exe tools\generate_tutien3_green_art.py --dry-run
```

Draw only missing files:

```bat
.venv\Scripts\python.exe tools\generate_tutien3_green_art.py --workers 4 --contact-sheet
```

Redraw the whole 177-image catalog:

```bat
.venv\Scripts\python.exe tools\generate_tutien3_green_art.py --overwrite --workers 4 --contact-sheet
```

Validate only:

```bat
.venv\Scripts\python.exe tools\generate_tutien3_green_art.py --validate-only --contact-sheet
```

Test one image only:

```bat
.venv\Scripts\python.exe tools\generate_tutien3_green_art.py --overwrite --limit 1 --workers 1 --contact-sheet
```

Draw one group only:

```bat
.venv\Scripts\python.exe tools\generate_tutien3_green_art.py --overwrite --groups "B" --workers 4 --contact-sheet
```

Draw P0 priority only:

```bat
.venv\Scripts\python.exe tools\generate_tutien3_green_art.py --overwrite --priorities P0 --workers 4 --contact-sheet
```

Use another image model:

```bat
.venv\Scripts\python.exe tools\generate_tutien3_green_art.py --overwrite --model cx/gpt-5.5-image --workers 2 --contact-sheet
```

Contact sheets and logs are saved in:

```text
outputs\tutien3_green_generation
```

## Notes

- The script validates target size and checks that the image edges/corners are pure `#00FF00`.
- If the API is slow, use the background batch file and watch the log command it prints.
- The script skips existing files unless `--overwrite` is used.

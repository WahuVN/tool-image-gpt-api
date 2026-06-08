# Relic Contract Art Commands

These commands use the project 9Router image setup in `.env.9router` and write final PNGs under `TuTien2/Resources`.

## One-click batch files

```bat
draw_missing_relic_contract_art.bat
validate_relic_contract_art.bat
```

## Terminal commands

Check what is still missing without drawing:

```bat
.venv\Scripts\python.exe tools\generate_relic_contract_art.py --dry-run
```

Draw only missing Liar/Three-card temp relic contract PNGs, then validate and build contact sheets:

```bat
.venv\Scripts\python.exe tools\generate_relic_contract_art.py --workers 4 --contact-sheet
```

Validate all 40 required contract PNGs and build contact sheets:

```bat
.venv\Scripts\python.exe tools\generate_relic_contract_art.py --validate-only --contact-sheet
```

Redraw all 40 contract PNGs:

```bat
.venv\Scripts\python.exe tools\generate_relic_contract_art.py --overwrite --workers 4 --contact-sheet
```

Test one missing/redraw item only:

```bat
.venv\Scripts\python.exe tools\generate_relic_contract_art.py --overwrite --limit 1 --workers 1 --contact-sheet
```

Use a different model or worker count:

```bat
.venv\Scripts\python.exe tools\generate_relic_contract_art.py --model cx/gpt-5.5-image --workers 2 --contact-sheet
```

Contact sheets are saved in `outputs/relic_contract_generation`.

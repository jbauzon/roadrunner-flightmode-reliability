# Contributing

Thanks for your interest. Here's how to get set up.

## Development setup

Prerequisites:

- Python 3.11+
- Node.js 20+ (for the web frontend)
- NI-DAQmx on Windows if you need real-hardware testing (SITL works without it)

```bash
git clone https://github.com/jbauzon/roadrunner-flightmode-reliability.git
cd roadrunner-flightmode-reliability

python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate            # Windows
pip install -e ".[dev,hardware]"   # drop 'hardware' on non-Windows

cd web && npm install && npm run build && cd ..
```

## Run the server

```bash
python ws_server.py --sitl        # SITL (no hardware)
python ws_server.py                # Real hardware
```

Open http://localhost:18890 in a browser.

## Run tests

```bash
pytest tests/ui_interaction_test.py tests/test_web_gui_e2e.py   # fast (~2 min)
pytest tests/                                                    # full suite
```

Walkthroughs run as standalone scripts:

```bash
python tests/new_user_walkthrough.py
python tests/playback_walkthrough.py --no-real-csv
```

## Code style

- `from __future__ import annotations` at the top of every `.py`
- Type hints on public functions
- `ruff check rr_test/ tests/` must pass

## Reporting bugs

Open a GitHub issue with:

- What you did
- What you expected
- What actually happened
- Any log output

# Tests

Run all fast tests:
```
pytest tests/ui_interaction_test.py tests/test_web_gui_e2e.py
```

## Test files

| File | What it tests | Runtime | How to run |
|------|--------------|---------|------------|
| `ui_interaction_test.py` | Every WebSocket command the GUI sends (43 controls) | ~60s | `python tests/ui_interaction_test.py` |
| `test_web_gui_e2e.py` | Firmware state machine via pymavlink + WS structure | ~2 min | `python tests/test_web_gui_e2e.py` |
| `new_user_walkthrough.py` | Full operator flow: open app → start IBIT → watch results | ~90s | `python tests/new_user_walkthrough.py` |
| `playback_walkthrough.py` | Flight Profile Playback end-to-end (100 Hz streaming) | ~60s | `python tests/playback_walkthrough.py --no-real-csv` |
| `debug_then_batch_walkthrough.py` | Debug Mode pre-flight → 9h batch (2 UUTs) | ~3 min | `python tests/debug_then_batch_walkthrough.py` |
| `debug_then_batch_6uuts.py` | Same but with 6 UUTs (full bench) | ~4 min | `python tests/debug_then_batch_6uuts.py` |
| `permutation_test.py` | 9 different user paths (stop mid-test, emergency stop, etc.) | ~8 min | `python tests/permutation_test.py` |
| `test_sitl.py` | Low-level SITL integration (MAVLink handshake, IBIT phases) | ~2 min | `python tests/test_sitl.py` |
| `test_permutations.py` | Combinatorial scenario testing with fault injection | ~5 min | `python tests/test_permutations.py` |
| `web_e2e_test.py` | Playwright browser-based E2E (requires Node) | ~3 min | `python tests/web_e2e_test.py` |
| `vv/` | Headed Playwright V&V suite (opens Chrome window) | ~5 min | `cd tests/vv && run_vv.bat` |

## Which tests to run when

- **After any code change:** `ui_interaction_test.py` (fastest, catches most regressions)
- **Before committing:** add `test_web_gui_e2e.py`
- **Before releasing:** run all of the above
- **On a new bench:** `debug_then_batch_6uuts.py` validates the full hardware setup

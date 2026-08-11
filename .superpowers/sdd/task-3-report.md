# Task 3 report — isolated candidate preflight

## RED

The initial contract test run failed as expected because `ActivationStore` had
no `preflight` method:

```text
.venv/bin/python -m pytest -q tests/honeyos/test_builder_preflight.py
7 failed
AttributeError: 'ActivationStore' object has no attribute 'preflight'
```

The real subprocess test then exposed two isolation defects before the final
implementation:

```text
preflight install_candidate failed
error: could not create 'build/lib/honeyos': Permission denied
```

Installing directly from the read-only slot attempted a source-tree build.
After changing that to a disposable archive, the runner exposed the second
defect:

```text
No module named pytest
```

A plain new virtual environment does not contain the required boundary-test
runner.  The final release contract pins `pytest==9.1.1` in the normal
`honeyos` runtime extra and the slot venv sees only the current trusted
runtime's installed dependency directory through a private `.pth`.  A missing
trusted dependency path still fails closed.

## GREEN

- `ActivationStore.preflight(activation_id, runner=None)` now uses an
  injectable `ProcessRunner`, a private atomic `PreflightReceipt`, bounded
  command records, redacted output, and strict preflight receipt validation.
- It creates a fresh synthetic HOME/HONEYOS_HOME, external bytecode cache and
  temp directory; command environments are a whitelist with cleared
  `PYTHONPATH`, `VIRTUAL_ENV`, `PIP_*`, `UV_*`, proxy, provider, channel, and
  credential variables.
- The complete frozen slot source is archived outside `slot/source` and
  installed non-editably with `pip --no-index --no-deps --no-build-isolation`.
  No candidate source file is writable during packaging or execution.
- Commands run from `slot/source` with `-s`; the import check requires both
  `honeyos.__file__` and `honeyos.runtime.main.__file__` to be inside that
  source tree.  This preserves the external bytecode-cache setting (unlike
  `-I`, which ignores it) and proves execution did not fall back to the live
  checkout.
- Preflight runs compile, import-origin, CLI, fixed Builder boundary tests,
  and only changed reviewed test files. Candidate/full-slot evidence is
  revalidated before and after execution; a source mutation fails the
  receipt. Failed or absent receipts block `awaiting_confirmation`.
- The distribution `honeyos` extra now declares pinned pytest and `uv.lock`
  contains the corresponding `extra == 'honeyos'` edge, so ordinary release
  installs include the required test runner.

## Verification

```text
uv lock --check
Resolved 242 packages in 13ms

.venv/bin/python -m pytest -q tests/honeyos/test_builder_activation.py tests/honeyos/test_builder_preflight.py
32 passed in 9.71s

.venv/bin/ruff check honeyos/companion/builder_activation.py tests/honeyos/test_builder_activation.py tests/honeyos/test_builder_preflight.py
All checks passed!

git diff --check
(no output)
```

## Self-review

- A real subprocess integration test verifies a successful slot preflight,
  source-origin imports, and no bytecode cache under the read-only source.
- A second real test simulates missing trusted runtime dependency paths and
  verifies fail-closed behavior.
- No service, provider, network, channel, confirmation callback, or live user
  data path is touched by the preflight implementation.

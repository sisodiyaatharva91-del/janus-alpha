"""Test driver: exercises measure_lookahead_bias.py UNMODIFIED, substituting
only the parquet I/O (no pyarrow in this sandbox). Everything else -- the lag,
the engine extraction, the metrics, the CLI -- is the real code path."""
import sys
import runpy
import pandas as pd

fixture = sys.argv[1]
_real = pd.read_parquet
pd.read_parquet = lambda *a, **k: pd.read_pickle(fixture)

sys.argv = ['measure_lookahead_bias.py', '--data', fixture, '--stage2']
try:
    runpy.run_path('measure_lookahead_bias.py', run_name='__main__')
except SystemExit as e:
    print(f"\n[driver] script exited with code {e.code}")

# GTA VI launch-day Twitch viewer forecast

Entry for `gta6-twitch-ccu-forecast-01`: forecast the concurrent Twitch
viewers in the Grand Theft Auto VI category for each hour 2-24 of release
day (19 November 2026, UTC), as five quantiles (5/25/50/75/95%) per hour.

## How it works

`main.py` (Python 3.13, standard library only, offline, deterministic)
reads every case file in the input directory and writes one forecast per
case. For each hour it builds the forecast from the past launch curves
shipped inside the case file itself:

1. Every comparable launch contributes the log ratio of its viewers in
   that hour to its own first-hour count.
2. Comparables are weighted by how close their first-hour count is to
   this launch's first-hour count, on the log scale, with a Gaussian
   kernel of bandwidth 1. Launches that open huge stay near their first
   hour; launches that open small build through the day, so first-hour
   size is the conditioning variable that matters.
3. The five quantiles are the interpolated weighted quantiles of that
   hour's log-ratio distribution, shifted back by this launch's
   first-hour count. No shrinkage: the honest conditional quantiles
   scored best in validation.
4. Hours with too few comparable curves fall back to a persistence fan
   that widens like a random walk in log space.

Nothing is fetched, nothing is random, and no launch is named in the
code: the same rule runs on every case the grader hands it.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Without those variables it reads `/input` and writes `/output`, as the
grader runs it.

## Local validation

The kit ships no local grader and no practice answers, so validation was
built from the 37 comparable launches inside the practice cases: each
launch in turn was held out, a case file was built for it from its own
pre-checkpoint data plus the other launches' curves, and the entry was
run on it exactly as the grader runs it (subprocess, one case per run).

- Leave-one-launch-out mean pinball loss (log scale): **0.400** vs the
  house baseline's **0.930** on the same folds; the entry wins 33 of 37
  folds.
- On the 16 folds with a first-hour count above 100,000 (the launches
  closest in scale to GTA VI): **0.216** vs baseline **0.261**.
- Variants tested and rejected on the same folds: pooled (unconditioned)
  curves, per-hour log-size regression, k-nearest curves, extra kernel
  dimensions (pre-release liveness, unlock-wave shape, weekday, hour-1
  channels, viewers per channel), median smoothing, and interval
  shrink/widen. None beat the single-kernel rule above.
- Determinism: two runs produce byte-identical outputs, including under
  the grader's flags (`python3 -P -s`, `PYTHONHASHSEED=0`).
- Runtime: about 0.08 s for one case (limit 8 s).
- Edge fixtures pass: final-shaped input (minute history, streams, and
  category tables present), missing comparables, missing first-hour
  print, malformed JSON, and an empty input directory all still produce
  valid forecast files.

## License

MIT — see `LICENSE`.

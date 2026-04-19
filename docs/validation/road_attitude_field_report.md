# Track-space Road Attitude Field — Validation Report

**Invariant:** observed demand, not friction. This report evaluates whether
aggregating bank/grade evidence across laps in track space reduces spread
enough to be useful for correction, and whether applying that field in
shadow mode improves alignment with GPS-derived centripetal.

## 1. Coverage

```
  centerline length: 1233.6 m, s-bin width: 5.0 m, n_bins: 247
  bank_valid bins:   183/247 (74.1%)
  grade_valid bins:  161/247 (65.2%)
  laps total:        43, used for bank: 43, used for grade: 43
  mean lap_coverage bank:  38.8
  mean lap_coverage grade: 28.0
```

## 2. Spread: per-sample (legacy) vs track-space (new)

```
  per-sample bank  std (deg):  9.405
  track-space bank std (deg):  4.712   (median across valid bins)
  reduction factor:            2.00x

  per-sample grade std (deg):  5.985
  track-space grade std (deg): 10.613
  reduction factor:            0.56x
```

## 3. Field mean values on valid bins

```
  mean bank  (deg): -0.615  median std: 4.299
  mean grade (deg): -0.360  median std: 10.613
```

## 4. Confidence + evidence distribution

```
  confidence    p 5: 0.70   evidence p 5: 457   coverage p 5: 35
  confidence    p25: 0.70   evidence p25: 809   coverage p25: 40
  confidence    p50: 0.77   evidence p50: 2596   coverage p50: 43
  confidence    p75: 0.77   evidence p75: 3436   coverage p75: 43
  confidence    p95: 0.89   evidence p95: 4290   coverage p95: 43
```

## 5. Shadow-mode correction impact (vs GPS centripetal)

`cal_bias` = median(|a_lat| / |v²κ/g|) on samples with |v²κ/g| > 0.05 G.
Closer to 1.0 = better alignment with GPS-derived centripetal.

```
regime                 | n        | cal_raw       | cal_cor       | rmse_raw    | rmse_cor    | bias_raw_g    | bias_cor_g   
---------------------- | -------- | ------------- | ------------- | ----------- | ----------- | ------------- | -------------
all_valid              | 854471   | 0.853         | 0.889         | 0.280       | 0.282       | -0.0544       | -0.0459      
straight               | 201681   | 0.531         | 0.860         | 0.162       | 0.168       | +0.0348       | +0.0582      
left_corner            | 141570   | 0.859         | 0.892         | 0.347       | 0.343       | -0.1317       | -0.1114      
right_corner           | 252706   | 0.865         | 0.848         | 0.351       | 0.361       | -0.1427       | -0.1551      
braking                | 140737   | 0.775         | 0.805         | 0.358       | 0.357       | -0.1313       | -0.1149      
accelerating           | 156567   | 0.968         | 0.990         | 0.259       | 0.261       | +0.0124       | +0.0128      
steady_mid_corner      | 128087   | 0.876         | 0.867         | 0.323       | 0.332       | -0.1228       | -0.1297      
```

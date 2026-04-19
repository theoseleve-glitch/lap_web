# Attitude Correction Validation Report

**Invariant:** observed demand, not friction. This report checks whether
the attitude correction moves the corrected lateral demand *toward* or
*away from* GPS-derived centripetal (v²κ/g) — our one external reference.

## 1. Conventions audited


| Quantity                           | Source                          | Sign convention found                     |
|------------------------------------|---------------------------------|-------------------------------------------|
| RaceChrono lateral *calc (col 19)  | data/raw/*.csv                  | unspecified by file; interpreted per test |
| Kart-frame y axis                  | road_attitude_estimator.py:258  | +y = LEFT                                 |
| Positive curvature κ               | _curvature_from_xy + road_att.  | left turn (CCW in XY)                     |
| GPS centripetal v²κ/g              | validation harness              | signed: positive on left turns            |
| Bank sign (road_attitude)          | road_attitude_estimator.py:215  | +bank = left side high → gravity_y = +sin |
| Bank correction (attitude_corr.)   | attitude_correction.py:182      | alat_cor = alat_raw − sin(bank)           |
| Grade sign (road_attitude)         | road_attitude_estimator.py:188  | +grade = uphill → a_x_gravity = −sin      |
| Grade correction (attitude_corr.)  | attitude_correction.py:183      | along_cor = along_raw + sin(grade)        |
| build_ok_raw.py use of alat        | scripts/build_ok_raw.py:232-243 | **takes abs() — sign information discarded** |
| curvature passed to correction     | scripts/build_ok_raw.py:228-236 | **None — ESTIMATOR SEES NO CURVATURE**    |

Observations:
  * The attitude estimator, without curvature, computes bank from
    ``a_y_residual = g_lp[:,1]`` — i.e., the low-passed lateral accel.
    In a sustained corner this signal equals *centripetal + bank*,
    so the estimator absorbs the corner's centripetal into "bank".
  * Per-sample bank is clamped to ±12°. ``sin(12°) ≈ 0.21 g`` — large
    enough to swing corrected |alat| by 20-30% every time we enter a corner.
  * build_ok_raw.py takes abs() of corrected alat before computing cal_bias,
    so the cal_bias metric sees **magnitude swings**, not sign inversions.


## 2. Scenario matrix — session-wide magnitude alignment

`cal_bias` = median(|a_lat| / |v²κ/g|) on in-corner samples (|v²κ/g| > 0.05 g)
Closer to 1.0 = better agreement with GPS-derived centripetal.

```
scenario                               | mean_bank° | std_bank° | mean_grade° | applied_frac | cal_bias_raw | cal_bias_cor | sign_cons_cor
-------------------------------------- | ---------- | --------- | ----------- | ------------ | ------------ | ------------ | -------------
nocurv_b+g+                            | -1.62      | 9.41      | -5.22       | 99.8%        | 0.853        | 1.132        | 0.885        
curv_b+g+                              | +0.54      | 10.88     | -5.22       | 99.8%        | 0.853        | 1.288        | 0.891        
nocurv_b-g+                            | +1.62      | 9.41      | -5.22       | 99.8%        | 0.853        | 0.681        | 0.838        
curv_b-g+                              | -0.54      | 10.88     | -5.22       | 99.8%        | 0.853        | 0.583        | 0.812        
nocurv_b+g-                            | -1.62      | 9.41      | +5.22       | 99.8%        | 0.853        | 1.132        | 0.885        
curv_b+g-                              | +0.54      | 10.88     | +5.22       | 99.8%        | 0.853        | 1.288        | 0.891        
curv_b-g-                              | -0.54      | 10.88     | +5.22       | 99.8%        | 0.853        | 0.583        | 0.812        
```

## 3. Per-segment breakdown — current production scenario

This mirrors what build_ok_raw.py is doing today (no curvature, original signs).

```
segment              | n        | cal_bias_raw | cal_bias_cor | rmse_raw_g  | rmse_cor_g  | sign_agree_raw | sign_agree_cor
-------------------- | -------- | ------------ | ------------ | ----------- | ----------- | -------------- | --------------
all_valid            | 854471   | 0.853        | 1.132        | 0.280       | 0.307       | 0.89           | 0.88          
straight             | 201681   | 0.531        | 1.513        | 0.162       | 0.224       | 0.68           | 0.66          
left_corner          | 141570   | 0.859        | 1.096        | 0.347       | 0.339       | 0.97           | 0.97          
right_corner         | 252706   | 0.865        | 0.973        | 0.351       | 0.358       | 0.98           | 0.98          
braking              | 140737   | 0.775        | 0.933        | 0.358       | 0.359       | 0.89           | 0.88          
accelerating         | 156567   | 0.968        | 1.343        | 0.259       | 0.316       | 0.88           | 0.88          
steady_mid_corner    | 128087   | 0.876        | 1.048        | 0.323       | 0.324       | 0.98           | 0.98          
```

## 4. Per-segment breakdown — WITH curvature (what production SHOULD do)

```
segment              | n        | cal_bias_raw | cal_bias_cor | rmse_raw_g  | rmse_cor_g  | sign_agree_raw | sign_agree_cor
-------------------- | -------- | ------------ | ------------ | ----------- | ----------- | -------------- | --------------
all_valid            | 854471   | 0.853        | 1.288        | 0.280       | 0.311       | 0.89           | 0.89          
straight             | 201681   | 0.531        | 1.913        | 0.162       | 0.257       | 0.68           | 0.67          
left_corner          | 141570   | 0.859        | 1.165        | 0.347       | 0.332       | 0.97           | 0.97          
right_corner         | 252706   | 0.865        | 1.138        | 0.351       | 0.330       | 0.98           | 0.98          
braking              | 140737   | 0.775        | 1.146        | 0.358       | 0.341       | 0.89           | 0.89          
accelerating         | 156567   | 0.968        | 1.494        | 0.259       | 0.335       | 0.88           | 0.88          
steady_mid_corner    | 128087   | 0.876        | 1.153        | 0.323       | 0.313       | 0.98           | 0.98          
```

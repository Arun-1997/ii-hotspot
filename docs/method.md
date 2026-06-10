# Method

## The problem

Inflow and infiltration (I&I) -- rainwater and groundwater entering the
foul sewer through cracked pipes, faulty manholes, and illegal connections
-- is one of the most expensive persistent problems in wastewater systems.
Utilities know they have it; locating *where* in a large network is the
hard part. CCTV inspection of every pipe is prohibitive, and the flow
meters that would tell you something are sparse.

## The signal

Rain events are natural stress tests of the network. After rainfall, a
zone with I&I sources shows an anomalous flow-rate spike at the downstream
meter. The shape of that spike encodes the mechanism:

- A **fast** response (peak within ~1 h, narrow) is direct **inflow** --
  surface water finding a hole.
- A **slow** response (peak after a day or more, broad) is groundwater
  **infiltration** through pipe defects.

## The model

For each flow meter `m`, the residual after subtracting a SWMM-modelled
dry-weather + legitimate-runoff baseline is modelled as a non-negative
mixture of upstream-zone responses:

```
R_m(t) = sum over zones z upstream of m of
         A_z * ( a_z^fast * (P_z * h_fast)(t)
               + a_z^slow * (P_z * h_slow)(t) )
       + noise
```

- `P_z` is zone `z`'s rainfall series (mm per 5 min).
- `A_z` is zone `z`'s drained area (m^2).
- `h_fast` and `h_slow` are exponential unit hydrographs with time
  constants of about 1 h and 36 h.
- `a_z^fast` and `a_z^slow` are dimensionless capture fractions -- the
  fraction of rain landing on zone `z` that ends up in the foul sewer.

The unknowns `a_z` are the same quantity as the **R** in EPA's classic RTK
method, so the output is immediately legible to wastewater engineers.

## Two-stage estimation

**Stage A (unmixing).** Stack all timesteps across all meters and all
events into one large non-negative least-squares problem. For each meter
`m`, columns of the design matrix corresponding to zones *not* upstream of
`m` are zeroed. Ridge regularization via row augmentation stabilizes the
fit when neighbouring zones receive correlated rain. Output: per-zone
`a_fast`, `a_slow` for zones that lie upstream of any meter.

**Stage B (regression).** A gradient-boosted regressor maps static zone
features (pipe age, material, fraction below the water table, soil class,
manhole density, ...) to the recovered Stage A coefficients. Two purposes:

1. Generalize to zones that no meter sees.
2. Produce SHAP attributions that explain *why* a zone is suspect --
   actionable for an asset manager.

## Identifiability

Storms are spatially patchy at the 1 km radar resolution. Different events
illuminate different subsets of zones with different intensities, so the
linear system separates well even when one meter covers dozens of zones.
A handful of well-separated storms is enough; see the synthetic harness.

## Why physics-residual rather than pure ML

A pure ML approach has to learn the entire dry-weather flow pattern, the
diurnal cycle, weekday/weekend variation, and the rainfall response from
data. A physics-residual approach uses SWMM to handle the easy parts and
leaves the ML to learn only the geospatially-structured I&I component.
That makes it (a) far more data-efficient, (b) immediately interpretable,
and (c) able to extrapolate to zones with no historical metering.

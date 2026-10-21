# Review of the optimized OCV estimation paper

Reviewed 2026-10-20 against `documentation/An_Enhanced_Li-ion_Battery_Model_with_Optimized_OCV_Estimation.pdf` (five PDF pages, proceedings pages 13–17).

Paper: Oh Sing Ee Jenna et al., *An Enhanced Li-ion Battery Model with Optimized OCV Estimation*, PEPSC 2025. DOI: 10.1109/PEPSC67251.2025.11453369.

## Assessment

The paper is relevant because its abstract explicitly names the EVE-INR18650/35V platform, matching the supplied cell specification. It provides a candidate room-temperature OCV–SOC relation. It does not establish a validated online SOC estimator or SOP model for our hardware. The findings below concern the supplied paper; raw data and author code were not available for this review.

## Candidate polynomial

Equation (15), PDF page 3, gives:

```text
U(s) = 6.634e-10*s^5 - 2.012e-7*s^4 + 2.221e-5*s^3
       - 0.001107*s^2 + 0.03365*s + 3.163
```

Here `s` is SOC in **percent, 0–100**, and `U` is volts. Project SOC represented as a fraction must be multiplied by 100 before evaluating this equation.

Independent evaluation of the printed coefficients:

| SOC (%) | Predicted OCV (V) |
|---:|---:|
| 0 | 3.163000 |
| 10 | 3.409064 |
| 20 | 3.540811 |
| 50 | 3.804062 |
| 80 | 4.074397 |
| 100 | 4.182000 |

The derivative is positive throughout 0–100%: evaluating its extrema using the derivative's stationary points gives a minimum of approximately 0.004797 V per percentage point, near 94.03% SOC. The printed curve therefore has a unique inverse over its mathematical domain. This does not establish experimental accuracy throughout that domain.

Its image over that domain is only 3.163–4.182 V. In particular, the cell's 2.50 V discharge cutoff is not represented by this polynomial at 0% SOC. Do not force an inverse for voltages outside the curve's range, extrapolate below it, or silently treat an out-of-range voltage as a validated endpoint. Loaded cutoff voltage and rested OCV are different quantities.

## Findings requiring attention

1. **The stated discharge procedure is numerically inconsistent.** PDF page 1 says 6.8 mA for five minutes corresponds to approximately 10% of a 3500 mAh cell. It actually removes 0.5667 mAh, approximately **0.0162%**. Removing 10% in five minutes would require 4.2 A. That calculation identifies the discrepancy; it is not a proposed test current. The intended current or duration needs confirmation from the authors/data.

2. **The KF comparison does not demonstrate our required online estimation task.** Equations (3)–(5), PDF page 2, use states `[OCV, OCV_rate, SOC]` and measurements of both OCV and SOC. Our hardware measures terminal voltage, current and temperature; it does not directly measure OCV during load or provide independent true SOC. Comparing an updated OCV estimate with OCV used in the update can yield small residuals without demonstrating independent prediction accuracy. The paper does not make the evaluation timing sufficiently clear to resolve this concern. Its reported 0.557 mV test RMSE is not evidence of equivalent SOC accuracy in our live system.

3. **Table III contains incorrect polynomial RMSE values.** PDF page 4 repeats each polynomial MSE in the RMSE column. For example, battery 1 has MSE `3.32e-4 V^2`, whose square root is **0.01822 V**, rather than `3.32e-4 V`. The aggregate polynomial test RMSE in Table I is about 20.1 mV; that is an OCV error metric, not an SOC error metric.

4. **The printed filter is insufficiently specified for direct reproduction.** The transition matrix contains an unspecified coupling factor and an implicit time step of one in the OCV-rate term. The initial OCV-rate value of −10 has no clear time unit. The text describes adaptive covariance updates without a complete reproducible mapping for all matrix entries. The current-to-SOC control input needs explicit sign, elapsed time, capacity and percent/fraction conventions. Equation (1) also requires a factor of `1/3600` if time is in seconds and capacity is in Ah.

5. **Validation scope is narrower than the application.** The experiments are described at approximately 25°C with one-hour rests. Holding out the last two cycles per cell is useful for temporal evaluation but does not test unseen cells, temperatures, aging conditions or our dynamic driving load. Selecting polynomial degree using training MSE is not independent model selection; nested least-squares models generally improve training fit as degree increases. Raw data, fit-domain coverage and independent validation remain needed.

## Recommended application to APS380

These are engineering recommendations from the review, not claims established by the paper:

- Store the polynomial as a source-labeled **candidate 25°C reference**, separately from measured calibration. Generate a bounded lookup table and verify inversion and SOC units.
- Validate rested-voltage initialization against our actual cell at several independently established SOC points. Define out-of-range behavior and record initialization uncertainty.
- Update running SOC on the PC using measured **net cell current**, elapsed measurement time and measured effective capacity. With discharge positive and SOC as a fraction, the baseline equation is `SOC_next = SOC - I_cell*dt/(3600*capacity_Ah)`; charge efficiency and measurement bias require consideration during calibration.
- Use a measured/rest-qualified OCV relation for initialization or correction. Do not directly invert loaded terminal voltage as though it were OCV.
- If an online observer is subsequently needed, identify a terminal-voltage model such as `V_terminal = OCV(SOC) - I_cell*R0 - V_polarization` under the project's discharge-positive convention. Validate its parameters and estimator against independent data before relying on it.
- Develop SOP separately using the approved voltage, current and temperature bounds, an explicit prediction horizon and validated electrical dynamics. An OCV polynomial alone cannot establish permissible charging or discharge power.
- Keep Python responsible for SOC/SOP and instrument commands, ESP32 responsible for sensing/local supervision, and independent hardware protection separate, as required by the current project context.

No simulator, cell configuration, estimator or hardware-control behavior was changed by this review.

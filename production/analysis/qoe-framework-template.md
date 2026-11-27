# Proposed LLM QoE Framework — Analysis Template

## Construct
User-perceived quality of a streaming LLM interaction under a defined model, task, participant and network condition.

## Candidate predictors
- Network: configured latency/jitter/loss/bandwidth; measured ICMP RTT and loss; iPerf throughput; packet inter-arrival variation.
- Inference: vLLM TTFT, scheduler queue time, inter-token latency, TPOT, end-to-end latency and output-token count.
- Client: click-to-first-chunk, post-prepare chat TTFT, first rendered frame, client end-to-end duration, chunk arrival distribution.
- Task: task category, rubric score and response completeness.
- Human workload: NASA-TLX raw score.

## Outcome
P.852-aligned local QoE supplemental rating. Treat this as a local instrument until the supervisor approves the exact P.852 mapping.

## Modelling plan
1. Descriptive distributions and missingness by model, profile and task.
2. Repeated-measures mixed-effects regression with participant random intercepts and task/model/network fixed effects.
3. Nonlinear exploratory model with participant-grouped cross-validation.
4. Independent held-out participant cohort for confirmatory predictive validation.
5. Calibration, MAE/RMSE, confidence intervals and subgroup error analysis.
6. Inter-rater reliability (ICC(2,1), ICC(2,k)) for independent rubric scoring.
7. Sensitivity analysis for finish_reason=length, incomplete outputs, missing questionnaires and protocol deviations.

## Required caution
Do not claim causality from a convenience sample or one pilot. Do not train/test split individual traces randomly when a participant contributes repeated observations. Do not combine configured network settings with measured network values as if they were equivalent. Report model revision and inference settings with every result.

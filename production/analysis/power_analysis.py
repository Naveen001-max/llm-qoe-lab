#!/usr/bin/env python3
"""Approximate paired-samples power calculation; final design needs statistician review."""
import argparse, json, math
from statsmodels.stats.power import TTestPower

p=argparse.ArgumentParser()
p.add_argument("--effect-size",type=float,default=0.5,help="Standardised within-participant mean difference (Cohen dz)")
p.add_argument("--power",type=float,default=0.8)
p.add_argument("--alpha",type=float,default=0.05)
p.add_argument("--alternative",choices=["two-sided","larger","smaller"],default="two-sided")
a=p.parse_args()
n=TTestPower().solve_power(effect_size=a.effect_size,power=a.power,alpha=a.alpha,alternative=a.alternative)
print(json.dumps({"design":"paired-samples t-test approximation","required_complete_participants":math.ceil(n),
 "effect_size_dz":a.effect_size,"power":a.power,"alpha":a.alpha,"alternative":a.alternative,
 "warning":"Planning approximation only. Final sample size should account for the repeated-measures/mixed model, multiplicity, expected attrition, task/profile balance and ethics/supervisor review."},indent=2))

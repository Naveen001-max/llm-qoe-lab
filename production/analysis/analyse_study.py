#!/usr/bin/env python3
"""Exploratory analysis of LLM QoE Lab study export.
Usage: python analyse_study.py study-export.json --out results/
Participant-grouped CV prevents repeated-measure participant leakage.
"""
import argparse, json, math, re
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, kruskal
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
import statsmodels.formula.api as smf

def parse_tc_counters(text):
    if not isinstance(text,str): return None
    m=re.search(r"Sent\s+(\d+)\s+bytes\s+(\d+)\s+pkt\s+\(dropped\s+(\d+)",text)
    if not m: return None
    return {"bytes":int(m.group(1)),"packets":int(m.group(2)),"drops":int(m.group(3))}

def qdisc_delta(start_payload,end_payload):
    start=(start_payload or {}).get("gateway_ack",{})
    end=(end_payload or {}).get("gateway_end_stats",{})
    output={}
    for key,start_key,end_key in [
        ("wan_egress","wan_qdisc_stats","wan_qdisc_stats"),
        ("wan_ingress_ifb","ifb_qdisc_stats","ifb_qdisc_stats")]:
        a=parse_tc_counters(start.get(start_key)); b=parse_tc_counters(end.get(end_key))
        for metric in ("bytes","packets","drops"):
            output[f"{key}_{metric}_delta"]=(b[metric]-a[metric]) if a and b else None
    return output

def flatten(records):
    rows=[]
    for item in records:
        t=item.get("trace",{}); a=item.get("assignment",{})
        reqs=item.get("requests",[])
        if not reqs: continue
        req=max(reqs,key=lambda r:r.get("started_at") or "")
        q={x["instrument"]:x for x in item.get("questionnaires",[])}
        events=item.get("events",[])
        render=next((e.get("payload",{}) for e in reversed(events) if e.get("event_type")=="participant_rendering_summary"),{})
        client_done=next((e.get("payload",{}) for e in reversed(events) if e.get("event_type")=="participant_stream_completed"),{})
        profile_start=next((e.get("payload",{}) for e in events if e.get("event_type")=="network_profile_applied"),{})
        profile_end=next((e.get("payload",{}) for e in reversed(events) if e.get("event_type")=="network_profile_reset"),{})
        packet_deltas=qdisc_delta(profile_start,profile_end)
        profile=(a.get("condition") or {}).get("network_profile",{})
        rows.append({
            "trace_id":t.get("id"),"participant_id":t.get("participant_id"),
            "task_code":item.get("task",{}).get("task_code"),
            "model_arm":(a.get("condition") or {}).get("model_arm",t.get("model_arm")),
            "network_profile":profile.get("name"),
            "latency_ms":profile.get("latency_ms",0),"jitter_ms":profile.get("jitter_ms",0),
            "loss_pct":profile.get("loss_pct",0),"bandwidth_mbps":profile.get("bandwidth_mbps",0),
            "ttft_ms":req.get("ttft_ms"),"client_chat_ttft_ms":render.get("client_chat_ttft_ms"),
            "client_first_render_frame_ms":render.get("client_first_render_frame_ms"),
            "client_click_to_first_chunk_ms":render.get("client_click_to_first_chunk_ms"),
            "profile_prepare_ms":render.get("profile_prepare_ms"),
            "client_chat_e2e_ms":client_done.get("client_chat_e2e_ms"),
            "client_click_to_completion_ms":client_done.get("client_click_to_completion_ms"),
            "itl_mean_ms":req.get("itl_mean_ms"),
            "tpot_ms":req.get("tpot_ms"),"queue_time_ms":req.get("queue_time_ms"),
            "e2e_latency_ms":req.get("e2e_latency_ms"),"output_tokens":req.get("output_tokens"),"chunk_count":req.get("chunk_count"),"response_bytes":req.get("response_bytes"),
            "finish_reason":req.get("finish_reason"),
            "qoe_score":q.get("p852_aligned_supplemental",{}).get("score"),
            "nasa_tlx_raw":q.get("nasa_tlx_raw",{}).get("score"),
            "rubric_score":np.mean([x.get("total_score") for x in item.get("rubric_scores",[])]) if item.get("rubric_scores") else np.nan
        })
    return pd.DataFrame(rows)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input",type=Path); ap.add_argument("--out",type=Path,default=Path("analysis-output"))
    args=ap.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    records=json.loads(args.input.read_text(encoding="utf-8"))
    df=flatten(records)
    if df.empty: raise SystemExit("No completed request traces found in export.")
    df.to_csv(args.out/"trace-level-dataset.csv",index=False)
    report={"n_traces":int(len(df)),"n_participants":int(df.participant_id.nunique()),
            "missing_qoe":int(df.qoe_score.isna().sum()),"analyses":{}}
    paired=df.dropna(subset=["ttft_ms","qoe_score"])
    if len(paired)>=3:
        rho,p=spearmanr(paired.ttft_ms,paired.qoe_score)
        report["analyses"]["spearman_ttft_qoe"]={"rho":float(rho),"p_value":float(p),"n":int(len(paired))}
    groups=[g.qoe_score.dropna().values for _,g in df.groupby("network_profile") if g.qoe_score.notna().sum()>=2]
    if len(groups)>=2:
        stat,p=kruskal(*groups)
        report["analyses"]["kruskal_qoe_by_profile"]={"statistic":float(stat),"p_value":float(p),"groups":len(groups)}
    model_df=df.dropna(subset=["qoe_score","participant_id"]).copy()
    numeric=["ttft_ms","itl_mean_ms","tpot_ms","queue_time_ms","e2e_latency_ms","output_tokens","chunk_count","response_bytes","latency_ms","jitter_ms","loss_pct","bandwidth_mbps"]
    categorical=["model_arm","network_profile","task_code","finish_reason"]
    if model_df.participant_id.nunique()>=3 and len(model_df)>=10:
        X=model_df[numeric+categorical]; y=model_df.qoe_score.astype(float); groups=model_df.participant_id
        pre=ColumnTransformer([
            ("num",Pipeline([("impute",SimpleImputer(strategy="median")),("scale",StandardScaler())]),numeric),
            ("cat",Pipeline([("impute",SimpleImputer(strategy="most_frequent")),("onehot",OneHotEncoder(handle_unknown="ignore"))]),categorical)
        ])
        pipe=Pipeline([("pre",pre),("rf",RandomForestRegressor(n_estimators=400,min_samples_leaf=2,random_state=42,n_jobs=-1))])
        splitter=GroupKFold(n_splits=min(5,groups.nunique()))
        obs=[]; pred=[]
        for train,test in splitter.split(X,y,groups):
            pipe.fit(X.iloc[train],y.iloc[train]); pred.extend(pipe.predict(X.iloc[test])); obs.extend(y.iloc[test])
        report["analyses"]["grouped_cv_qoe_prediction"]={
            "folds":min(5,groups.nunique()),"mae":float(mean_absolute_error(obs,pred)),
            "rmse":float(math.sqrt(mean_squared_error(obs,pred))),"r2":float(r2_score(obs,pred)),
            "warning":"Exploratory only; report uncertainty and use an independent held-out cohort for confirmatory validation."
        }
    else:
        report["analyses"]["grouped_cv_qoe_prediction"]={"skipped":"Need at least 3 participants and 10 complete QoE traces."}
    mixed_df=model_df.dropna(subset=["ttft_ms","queue_time_ms","e2e_latency_ms","model_arm","network_profile","task_code"])
    if mixed_df.participant_id.nunique()>=5 and len(mixed_df)>=20:
        try:
            fit=smf.mixedlm(
                "qoe_score ~ ttft_ms + queue_time_ms + e2e_latency_ms + C(model_arm) + C(network_profile) + C(task_code)",
                data=mixed_df,groups=mixed_df["participant_id"]).fit(reml=False)
            report["analyses"]["mixed_effects_model"]={
                "converged":bool(fit.converged),
                "coefficients":{k:float(v) for k,v in fit.params.items()},
                "confidence_intervals":{k:[float(v[0]),float(v[1])] for k,v in fit.conf_int().iterrows()},
                "p_values":{k:float(v) for k,v in fit.pvalues.items()}
            }
        except Exception as exc:
            report["analyses"]["mixed_effects_model"]={"failed":type(exc).__name__}
    else:
        report["analyses"]["mixed_effects_model"]={"skipped":"Need at least 5 participants and 20 complete traces with timing and condition fields."}
    scorer_rows=[]
    for item in records:
        scores=[x.get("total_score") for x in item.get("rubric_scores",[]) if x.get("total_score") is not None]
        if len(scores)>=2:
            diffs=[abs(a-b) for i,a in enumerate(scores) for b in scores[i+1:]]
            scorer_rows.append({"trace_id":item.get("trace",{}).get("id"),"mean_abs_difference":float(np.mean(diffs))})
    pd.DataFrame(scorer_rows).to_csv(args.out/"interrater-disagreement.csv",index=False)
    long_scores=[]
    for item in records:
        for score in item.get("rubric_scores",[]):
            if score.get("total_score") is not None and score.get("scorer_id"):
                long_scores.append({"trace_id":item.get("trace",{}).get("id"),
                                    "scorer_id":score.get("scorer_id"),"total_score":score.get("total_score")})
    if long_scores:
        try:
            import pingouin as pg
            icc=pg.intraclass_corr(data=pd.DataFrame(long_scores),targets="trace_id",
                raters="scorer_id",ratings="total_score")
            report["analyses"]["interrater_icc"]=icc[icc.Type.isin(["ICC2","ICC2k"])][["Type","ICC","CI95%","pval"]].to_dict("records")
        except Exception as exc:
            report["analyses"]["interrater_icc"]={"unavailable":type(exc).__name__}
    (args.out/"analysis-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))
if __name__=="__main__": main()

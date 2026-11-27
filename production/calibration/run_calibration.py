#!/usr/bin/env python3
"""Automated WP5 calibration across gateway profiles and both inference arms."""
import argparse, json, os, subprocess, time, urllib.request, ssl, datetime, re
from pathlib import Path

PROFILES=[
 {"name":"baseline","latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0},
 {"name":"moderate","latency_ms":100,"jitter_ms":20,"loss_pct":1,"bandwidth_mbps":50},
 {"name":"high_delay","latency_ms":250,"jitter_ms":30,"loss_pct":1,"bandwidth_mbps":25},
 {"name":"constrained","latency_ms":100,"jitter_ms":50,"loss_pct":3,"bandwidth_mbps":5}
]
def request_json(url, data=None, headers=None, context=None, timeout=30):
    raw=json.dumps(data).encode() if data is not None else None
    req=urllib.request.Request(url,data=raw,headers=headers or {},method="POST" if data is not None else "GET")
    return urllib.request.urlopen(req,timeout=timeout,context=context).read()
def ping_probe(host, count=20):
    result=subprocess.run(["ping","-n","-c",str(count),"-i","0.2","-W","2",host],
        capture_output=True,text=True,timeout=count*3+10)
    output=result.stdout+"\n"+result.stderr
    loss=re.search(r"([0-9.]+)% packet loss",output)
    rtt=re.search(r"rtt min/avg/max/(?:mdev|stddev) = ([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+) ms",output)
    return {"return_code":result.returncode,"packet_loss_pct":float(loss.group(1)) if loss else None,
        "rtt_min_ms":float(rtt.group(1)) if rtt else None,"rtt_avg_ms":float(rtt.group(2)) if rtt else None,
        "rtt_max_ms":float(rtt.group(3)) if rtt else None,"rtt_mdev_ms":float(rtt.group(4)) if rtt else None,
        "raw_output":output[-1200:]}

def gateway_status(url,headers,context):
    req=urllib.request.Request(url.rstrip("/")+"/status",headers=headers,method="GET")
    with urllib.request.urlopen(req,context=context,timeout=15) as r: return json.loads(r.read())

def run_model(base, model, api_key, context):
    payload={"model":model,"messages":[{"role":"user","content":"Explain in two short paragraphs why network latency and model inference latency are different."}],
             "stream":True,"stream_options":{"include_usage":True},"max_tokens":96,"temperature":0,"top_p":1.0,"seed":42}
    req=urllib.request.Request(base.rstrip("/")+"/chat/completions",data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+api_key},method="POST")
    start=time.perf_counter(); first=None; previous=None; gaps=[]; tokens=0; finish=None
    with urllib.request.urlopen(req,timeout=180,context=context) as resp:
        for raw in resp:
            line=raw.decode("utf-8","replace").strip()
            if not line.startswith("data:"): continue
            data=line[5:].strip()
            if data=="[DONE]": break
            try: packet=json.loads(data)
            except Exception: continue
            if packet.get("usage"): tokens=packet["usage"].get("completion_tokens",tokens)
            choices=packet.get("choices") or []
            if not choices: continue
            c=choices[0]
            if c.get("delta",{}).get("content"):
                now=time.perf_counter()
                if first is None: first=now
                if previous is not None: gaps.append((now-previous)*1000)
                previous=now
            if c.get("finish_reason"): finish=c["finish_reason"]
    end=time.perf_counter()
    return {"ttft_ms":(first-start)*1000 if first else None,"e2e_ms":(end-start)*1000,
            "mean_inter_output_gap_ms":sum(gaps)/len(gaps) if gaps else None,
            "provider_completion_tokens":tokens,"finish_reason":finish}
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--gateway",required=True); ap.add_argument("--token",default=os.getenv("GATEWAY_TOKEN",""))
    ap.add_argument("--gateway-ca",required=True); ap.add_argument("--inference-ca",required=True); ap.add_argument("--iperf-host",required=True)
    ap.add_argument("--llm-url",required=True); ap.add_argument("--llm-model",required=True); ap.add_argument("--llm-key",required=True)
    ap.add_argument("--slm-url",required=True); ap.add_argument("--slm-model",required=True); ap.add_argument("--slm-key",required=True)
    ap.add_argument("--out",default="calibration-results.json")
    args=ap.parse_args()
    if not args.token: raise SystemExit("Supply --token or GATEWAY_TOKEN")
    gateway_context=ssl.create_default_context(cafile=args.gateway_ca)
    inference_context=ssl.create_default_context(cafile=args.inference_ca)
    headers={"Authorization":"Bearer "+args.token,"Content-Type":"application/json"}
    results={"started_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"profiles":[]}
    try:
        for profile in PROFILES:
            ack=json.loads(request_json(args.gateway.rstrip("/")+"/profile",profile,headers,gateway_context).decode())
            status=gateway_status(args.gateway,headers,gateway_context)
            ping=ping_probe(args.iperf_host)
            iperf=subprocess.run(["iperf3","-c",args.iperf_host,"-t","15","-J"],capture_output=True,text=True,timeout=40)
            if iperf.returncode: raise RuntimeError("iperf3 failed: "+iperf.stderr[-500:])
            entry={"profile":profile,"gateway_ack":ack,"gateway_status":status,"icmp_probe":ping,
                   "iperf3":json.loads(iperf.stdout),"inference":{}}
            for arm,url,model,key in [("llm",args.llm_url,args.llm_model,args.llm_key),("slm",args.slm_url,args.slm_model,args.slm_key)]:
                entry["inference"][arm]=run_model(url,model,key,inference_context)
            results["profiles"].append(entry)
            Path(args.out).write_text(json.dumps(results,indent=2),encoding="utf-8")
    except Exception as exc:
        results["error"]={"type":type(exc).__name__,"message":str(exc)[:500]}
        raise
    finally:
        baseline={"latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0}
        try: request_json(args.gateway.rstrip("/")+"/profile",baseline,headers,gateway_context)
        except Exception as exc: results["baseline_reset_error"]=type(exc).__name__
        results["completed_at_utc"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
        Path(args.out).write_text(json.dumps(results,indent=2),encoding="utf-8")
    print(f"Wrote {args.out}")
if __name__=="__main__": main()

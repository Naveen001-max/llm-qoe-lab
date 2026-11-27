"""Authenticated host agent for applying the experiment's tc/netem profiles.
Run on the dedicated Ubuntu gateway host. WAN_IF is the gateway interface carrying routed experiment traffic.
"""
import os, hmac, subprocess, re
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

TOKEN=os.environ.get("QOE_GATEWAY_TOKEN","")
WAN_IF=os.environ.get("WAN_IF","")
app=FastAPI(title="LLM QoE Gateway Agent",docs_url=None,redoc_url=None)

class Profile(BaseModel):
    latency_ms: int=Field(ge=0,le=2000)
    jitter_ms: float=Field(ge=0,le=500)
    loss_pct: float=Field(ge=0,le=30)
    bandwidth_mbps: float=Field(ge=0,le=1000)

def run(args):
    p=subprocess.run(args,capture_output=True,text=True,timeout=12)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout)[-800:])
    return p.stdout.strip()

def parse_qdisc_counters(device: str):
    """Parse tc -s qdisc output into per-qdisc counters; do not aggregate hierarchy levels."""
    output = run(["tc", "-s", "qdisc", "show", "dev", device])
    rows, current = [], None
    qdisc_re = re.compile(r"^qdisc\s+(\S+)\s+(\S+):\s+(.*)$")
    sent_re = re.compile(
        r"Sent\s+(\d+)\s+bytes\s+(\d+)\s+pkt\s+"
        r"\(dropped\s+(\d+),\s*overlimits\s+(\d+)\s+requeues\s+(\d+)\)"
    )
    for line in output.splitlines():
        match = qdisc_re.match(line.strip())
        if match:
            if current is not None:
                rows.append(current)
            kind, handle, placement = match.groups()
            current = {"device": device, "kind": kind, "handle": handle + ":",
                       "placement": placement, "bytes": 0, "packets": 0,
                       "dropped": 0, "overlimits": 0, "requeues": 0}
            continue
        sent = sent_re.search(line)
        if sent and current is not None:
            values = [int(value) for value in sent.groups()]
            current.update(dict(zip(("bytes", "packets", "dropped", "overlimits", "requeues"), values)))
    if current is not None:
        rows.append(current)
    return rows

def qdisc_snapshot():
    if not WAN_IF:
        raise RuntimeError("WAN_IF is not configured")
    return {
        "wan_interface": WAN_IF,
        "wan_qdiscs": parse_qdisc_counters(WAN_IF),
        "ifb_interface": "ifb0",
        "ifb_qdiscs": parse_qdisc_counters("ifb0"),
        "counter_source": "tc -s qdisc show",
        "counter_semantics": "Per-qdisc counters. Do not sum parent and child qdiscs because hierarchical qdiscs can count the same packet at multiple levels."
    }

def auth(header):
    if not TOKEN or not header or not header.startswith("Bearer ") or not hmac.compare_digest(header[7:],TOKEN):
        raise HTTPException(401,"Invalid gateway controller credential")

def apply_one(dev, cfg):
    subprocess.run(["tc","qdisc","del","dev",dev,"root"],capture_output=True,text=True)
    # A missing root qdisc is normal before the first profile is applied.
    args=["delay",f'{cfg.latency_ms}ms']
    if cfg.jitter_ms: args += [f'{cfg.jitter_ms}ms',"distribution","normal"]
    if cfg.loss_pct: args += ["loss","random",f'{cfg.loss_pct}%']
    if cfg.bandwidth_mbps:
        run(["tc","qdisc","replace","dev",dev,"root","handle","1:","htb","default","10"])
        run(["tc","class","replace","dev",dev,"parent","1:","classid","1:10","htb","rate",f'{cfg.bandwidth_mbps:g}mbit',"ceil",f'{cfg.bandwidth_mbps:g}mbit'])
        run(["tc","qdisc","replace","dev",dev,"parent","1:10","handle","10:","netem",*args])
    else:
        run(["tc","qdisc","replace","dev",dev,"root","netem",*args])

def reset_to_baseline():
    if not WAN_IF: raise RuntimeError("WAN_IF is not configured")
    run(["ip","link","set","ifb0","up"])
    run(["tc","qdisc","replace","dev",WAN_IF,"handle","ffff:","ingress"])
    run(["tc","filter","replace","dev",WAN_IF,"parent","ffff:","protocol","all","u32",
         "match","u32","0","0","action","mirred","egress","redirect","dev","ifb0"])
    baseline=Profile(latency_ms=0,jitter_ms=0,loss_pct=0,bandwidth_mbps=0)
    apply_one(WAN_IF,baseline); apply_one("ifb0",baseline)

@app.on_event("startup")
def startup_baseline():
    reset_to_baseline()

@app.get("/health")
def health():
    return {"status":"ok","interface":WAN_IF}

@app.get("/status")
def status(authorization: str|None=Header(default=None)):
    auth(authorization)
    return {"wan_qdisc":run(["tc","qdisc","show","dev",WAN_IF]),
            "wan_qdisc_stats":run(["tc","-s","qdisc","show","dev",WAN_IF]),
            "ifb_qdisc":run(["tc","qdisc","show","dev","ifb0"]),
            "ifb_qdisc_stats":run(["tc","-s","qdisc","show","dev","ifb0"]),
            "qdisc_counters":qdisc_snapshot(),
            "ingress_filter":run(["tc","filter","show","dev",WAN_IF,"parent","ffff:"])}

@app.post("/profile")
def profile(cfg: Profile, authorization: str|None=Header(default=None)):
    auth(authorization)
    if not WAN_IF: raise HTTPException(503,"WAN_IF is not configured")
    run(["ip","link","set","ifb0","up"])
    run(["tc","qdisc","replace","dev",WAN_IF,"handle","ffff:","ingress"])
    run(["tc","filter","replace","dev",WAN_IF,"parent","ffff:","protocol","all","u32","match","u32","0","0","action","mirred","egress","redirect","dev","ifb0"])
    apply_one(WAN_IF,cfg); apply_one("ifb0",cfg)
    return {"applied":True,"profile":cfg.model_dump(),"wan_qdisc":run(["tc","qdisc","show","dev",WAN_IF]),
            "wan_qdisc_stats":run(["tc","-s","qdisc","show","dev",WAN_IF]),
            "ifb_qdisc":run(["tc","qdisc","show","dev","ifb0"]),
            "ifb_qdisc_stats":run(["tc","-s","qdisc","show","dev","ifb0"]),
            "qdisc_counters":qdisc_snapshot()}

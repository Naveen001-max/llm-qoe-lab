"""Linux TCP CONNECT proxy with real bidirectional traffic shaping via tc/netem + IFB.
Only traffic sent through this proxy is shaped. Run inside a container with NET_ADMIN.
"""
import asyncio
import json
import os
import subprocess
import threading
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone

PROXY_HOST = "0.0.0.0"
PROXY_PORT = int(os.getenv("PROXY_PORT", "3128"))
CONTROL_PORT = int(os.getenv("NETEM_CONTROL_PORT", "8081"))
IFACE = os.getenv("NETEM_INTERFACE", "eth0")
state = {"enabled": False, "latency_ms": 0, "jitter_ms": 0, "loss_pct": 0, "updated_at": None,
         "backend": "Linux tc/netem + IFB", "interface": IFACE, "directions": [], "error": None,
         "packet_counters": {"outbound": {"packets_seen": 0, "packets_dropped": 0}, "inbound": {"packets_seen": 0, "packets_dropped": 0}},
         "_raw_last": {"outbound": {"packets_seen": 0, "packets_dropped": 0}, "inbound": {"packets_seen": 0, "packets_dropped": 0}}}
lock = threading.Lock()


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout or f"command failed: {cmd}").strip())
    return p.stdout.strip()



def qdisc_raw_counts(interface):
    """Read Linux qdisc counters. These are packet counters, not LLM chunk counters."""
    try:
        output = run(["tc", "-s", "qdisc", "show", "dev", interface, "root"])
    except Exception:
        return {"packets_seen": 0, "packets_dropped": 0}
    match = re.search(r"Sent\s+\d+\s+bytes\s+(\d+)\s+pkt\s+\(dropped\s+(\d+)", output, re.I)
    if not match:
        return {"packets_seen": 0, "packets_dropped": 0}
    return {"packets_seen": int(match.group(1)), "packets_dropped": int(match.group(2))}

def update_packet_counters():
    """Accumulate qdisc counters across slider changes, which replace/reset qdiscs."""
    raw = {"outbound": qdisc_raw_counts(IFACE), "inbound": qdisc_raw_counts("ifb0")}
    with lock:
        for direction in ("outbound", "inbound"):
            for key in ("packets_seen", "packets_dropped"):
                current = raw[direction][key]
                previous = state["_raw_last"][direction][key]
                # A lower counter means tc/netem was recreated; add the new counter from zero.
                delta = current - previous if current >= previous else current
                state["packet_counters"][direction][key] += max(0, delta)
                state["_raw_last"][direction][key] = current
        state["packet_counters"]["combined"] = {
            key: state["packet_counters"]["outbound"][key] + state["packet_counters"]["inbound"][key]
            for key in ("packets_seen", "packets_dropped")
        }
        return json.loads(json.dumps(state["packet_counters"]))


def tc_apply(latency_ms: int, jitter_ms: int, loss_pct: float):
    # Snapshot old qdisc counters before replacing qdiscs for a new slider setting.
    try: update_packet_counters()
    except Exception: pass
    # Keep a zero-impairment netem qdisc installed at baseline so qdisc counters
    # remain observable even when all sliders are at zero.
    args = ["tc", "qdisc", "replace", "dev", IFACE, "root", "netem"]
    if latency_ms or jitter_ms:
        args += ["delay", f"{latency_ms}ms"]
        if jitter_ms:
            args += [f"{jitter_ms}ms", "distribution", "normal"]
    if loss_pct:
        # Independent random packet loss is a reproducible baseline model. It is
        # not a claim that all real radio/network loss follows an IID distribution.
        args += ["loss", "random", f"{loss_pct}%", "0%"]
    run(args)

    # Redirect ingress into IFB, where a second netem qdisc shapes inbound packets.
    try:
        run(["ip", "link", "show", "ifb0"])
    except Exception:
        run(["ip", "link", "add", "ifb0", "type", "ifb"])
    run(["ip", "link", "set", "ifb0", "up"])
    # Replace is idempotent; remove stale ingress qdisc/filter first if needed.
    subprocess.run(["tc", "qdisc", "del", "dev", IFACE, "ingress"], capture_output=True, text=True)
    run(["tc", "qdisc", "add", "dev", IFACE, "handle", "ffff:", "ingress"])
    run(["tc", "filter", "replace", "dev", IFACE, "parent", "ffff:", "protocol", "all", "u32",
         "match", "u32", "0", "0", "action", "mirred", "egress", "redirect", "dev", "ifb0"])
    # Keep the IFB qdisc installed at baseline as well, so inbound packet counters
    # do not disappear when impairments are set to zero.
    args = ["tc", "qdisc", "replace", "dev", "ifb0", "root", "netem"]
    if latency_ms or jitter_ms:
        args += ["delay", f"{latency_ms}ms"]
        if jitter_ms:
            args += [f"{jitter_ms}ms", "distribution", "normal"]
    if loss_pct:
        args += ["loss", "random", f"{loss_pct}%", "0%"]
    run(args)

    with lock:
        state.update({"ready": True, "enabled": bool(latency_ms or jitter_ms or loss_pct), "latency_ms": latency_ms,
                      "jitter_ms": jitter_ms, "loss_pct": loss_pct,
                      "updated_at": datetime.now(timezone.utc).isoformat(),
                      "directions": ["outbound", "inbound"], "error": None})
    return dict(state)


class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def send_json(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path == "/stats":
            try:
                counters = update_packet_counters()
                root_qdisc = run(["tc", "qdisc", "show", "dev", IFACE])
                ifb_qdisc = run(["tc", "qdisc", "show", "dev", "ifb0"])
                ingress_filter = run(["tc", "filter", "show", "dev", IFACE, "parent", "ffff:"])
                actually_ready = ("netem" in root_qdisc and "netem" in ifb_qdisc
                                  and bool(ingress_filter.strip()) and "ifb0" in ingress_filter)
                with lock:
                    snapshot = {"ready": actually_ready, "interface": IFACE, "backend": state.get("backend"),
                                "packet_counters": counters,
                                "settings": {k: state.get(k) for k in ("latency_ms", "jitter_ms", "loss_pct", "updated_at")},
                                "at": datetime.now(timezone.utc).isoformat()}
                return self.send_json(200, snapshot)
            except Exception as e:
                return self.send_json(500, {"ready": False, "error": str(e), "at": datetime.now(timezone.utc).isoformat()})
        if self.path != "/status":
            return self.send_json(404, {"error": "not found"})
        with lock:
            snapshot = {k: v for k, v in state.items() if not k.startswith("_")}
        try:
            snapshot["interface_ip"] = run(["sh", "-lc", f"ip -4 -o addr show dev {IFACE} | awk '{{print $4}}'"])
            snapshot["tc_qdisc"] = run(["tc", "qdisc", "show", "dev", IFACE])
            snapshot["packet_counters"] = update_packet_counters()
            snapshot["ifb_qdisc"] = run(["tc", "qdisc", "show", "dev", "ifb0"])
            snapshot["ingress_filter"] = run(["tc", "filter", "show", "dev", IFACE, "parent", "ffff:"])
            ingress_ready = bool(snapshot["ingress_filter"].strip()) and "ifb0" in snapshot["ingress_filter"]
            ifb_ready = "netem" in snapshot.get("ifb_qdisc", "")
            root_ready = "netem" in snapshot.get("tc_qdisc", "")
            snapshot["ready"] = bool(ingress_ready and ifb_ready and root_ready)
            snapshot["impairment_active"] = bool(snapshot.get("latency_ms", 0) or snapshot.get("jitter_ms", 0) or snapshot.get("loss_pct", 0))
            if not snapshot["ready"]:
                snapshot["error"] = "NetEm readiness check failed: expected egress netem, IFB netem, and an ingress redirect to ifb0."
        except Exception as e:
            snapshot.update({"ready": False, "error": str(e)})
        return self.send_json(200, snapshot)
    def do_POST(self):
        if self.path != "/settings": return self.send_json(404, {"error":"not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            latency = int(data.get("latency_ms", 0)); jitter = int(data.get("jitter_ms", 0)); loss = float(data.get("loss_pct", 0))
            # Keep the UI and API in a realistic experimental range. These are
            # per-direction values applied symmetrically, not a physical Wi-Fi change.
            if not 0 <= latency <= 250 or not 0 <= jitter <= 40 or not 0 <= loss <= 3:
                return self.send_json(400, {"error":"settings out of experimental range (one-way added delay 0–250 ms, jitter SD 0–40 ms, random packet loss 0–3%)"})
            result = tc_apply(latency, jitter, loss)
            return self.send_json(200, {"ok": True, **result})
        except Exception as e:
            # Best-effort rollback avoids leaving only one direction shaped after a partial failure.
            try: tc_apply(0, 0, 0)
            except Exception: pass
            with lock: state.update({"enabled": False, "latency_ms": 0, "jitter_ms": 0, "loss_pct": 0, "error": str(e)})
            return self.send_json(500, {"ok": False, "error": str(e), "hint":"Real shaping requires Linux tc/netem, IFB support, and NET_ADMIN capability. Partial changes were rolled back where possible."})

async def pump(reader, writer):
    try:
        while True:
            data = await reader.read(65536)
            if not data: break
            writer.write(data); await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        try: writer.close()
        except Exception: pass

async def handle_connect(client_reader, client_writer):
    try:
        header = await asyncio.wait_for(client_reader.readuntil(b"\r\n\r\n"), timeout=15)
        first = header.split(b"\r\n", 1)[0].decode("ascii", "replace").split()
        if len(first) < 3 or first[0].upper() != "CONNECT":
            client_writer.write(b"HTTP/1.1 405 Only HTTPS CONNECT is supported\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            await client_writer.drain(); return
        hostport = first[1]
        if ":" in hostport:
            host, port_text = hostport.rsplit(":", 1); port = int(port_text)
        else: host, port = hostport, 443
        if not host or not 1 <= port <= 65535: raise ValueError("Invalid CONNECT destination")
        upstream_reader, upstream_writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=20)
        client_writer.write(b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: LLM-QoE-NetEm\r\n\r\n")
        await client_writer.drain()
        await asyncio.gather(pump(client_reader, upstream_writer), pump(upstream_reader, client_writer))
        upstream_writer.close()
        try: await upstream_writer.wait_closed()
        except Exception: pass
    except Exception:
        try:
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            await client_writer.drain()
        except Exception: pass
    finally:
        client_writer.close()
        try: await client_writer.wait_closed()
        except Exception: pass

async def main():
    # Set up a zero-impairment baseline; if this fails, still start so status can report the reason.
    try: tc_apply(0, 0, 0)
    except Exception as e:
        with lock: state["error"] = str(e)
    server = await asyncio.start_server(handle_connect, PROXY_HOST, PROXY_PORT)
    async with server: await server.serve_forever()

if __name__ == "__main__":
    control = ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), ControlHandler)
    threading.Thread(target=control.serve_forever, daemon=True).start()
    asyncio.run(main())

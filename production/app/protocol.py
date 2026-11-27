from copy import deepcopy

NETWORK_PROFILES = [
    {"name":"baseline","latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0},
    {"name":"moderate","latency_ms":100,"jitter_ms":20,"loss_pct":1,"bandwidth_mbps":50},
    {"name":"high_delay","latency_ms":250,"jitter_ms":30,"loss_pct":1,"bandwidth_mbps":25},
    {"name":"constrained","latency_ms":100,"jitter_ms":50,"loss_pct":3,"bandwidth_mbps":5},
]

TASKS = [
 {"task_code":"T01","title":"Factual explanation","prompt":"Explain the difference between latency, jitter, packet loss and bandwidth to a non-technical reader. Give one practical example of each.","instructions":"Read the answer and decide whether it is accurate and understandable.","rubric":[("accuracy",30,"All four networking terms are correctly defined."),("completeness",25,"Explains each term distinctly."),("examples",25,"Examples are technically appropriate."),("clarity",20,"Language is understandable.") ]},
 {"task_code":"T02","title":"Structured summarisation","prompt":"Summarise the following note in exactly five bullet points: A small clinic is evaluating a digital appointment system. Patients report long waits, unclear status updates, and difficulty rescheduling. Staff report duplicate bookings and manual reconciliation. The clinic wants measurable service improvements without excluding users with limited digital skills.","instructions":"Check whether the summary preserves the important points without inventing facts.","rubric":[("coverage",40,"Captures patient and staff problems."),("fidelity",30,"No unsupported claims."),("format",15,"Exactly five bullets."),("clarity",15,"Concise and readable.") ]},
 {"task_code":"T03","title":"Multi-step reasoning","prompt":"A service receives 120 requests per minute. Each request transfers 240 KB on average. Calculate the average data rate in Mbps (decimal units), show the formula, and state one limitation of this average.","instructions":"Evaluate the calculation and reasoning.","rubric":[("method",30,"Correct conversion from KB/min to bits/s."),("result",35,"Approximately 3.84 Mbps using decimal units."),("working",20,"Shows formula and steps."),("limitation",15,"Notes burstiness/overhead/variance.") ]},
 {"task_code":"T04","title":"Instruction following","prompt":"Create a 4-row table comparing REST, WebSocket, Server-Sent Events and gRPC. Columns must be: technology, communication pattern, common use, one limitation. Do not add text outside the table.","instructions":"Check exact format and coverage.","rubric":[("format",30,"Exactly four rows and four requested columns."),("accuracy",40,"Descriptions are technically sound."),("completeness",20,"All four technologies included."),("constraint",10,"No prose outside table.") ]},
 {"task_code":"T05","title":"Code comprehension","prompt":"Review this Python function and identify its bug, explain why it occurs, and provide a corrected version: def average(values): return sum(values) / len(values)","instructions":"Assess correctness, edge cases and explanation.","rubric":[("bug",30,"Identifies empty-list division by zero."),("fix",35,"Handles empty input explicitly."),("reasoning",20,"Explains failure condition."),("code_quality",15,"Valid readable code.") ]},
 {"task_code":"T06","title":"Information extraction","prompt":"Extract the following into JSON with keys name, date, amount, currency, status: 'Invoice from Northwind Labs dated 14 March 2026 for INR 18,450; payment status: pending.' Return valid JSON only.","instructions":"Check schema, values and JSON validity.","rubric":[("schema",25,"All requested keys present."),("values",40,"Correctly extracts all fields."),("types",15,"Amount numeric or consistently represented."),("validity",20,"Valid JSON only.") ]},
 {"task_code":"T07","title":"Planning","prompt":"Prepare a practical 6-step plan to migrate a small research web application from SQLite to PostgreSQL with minimal downtime. Include backup, schema migration, validation and rollback.","instructions":"Assess sequencing and operational safety.","rubric":[("sequence",25,"Steps are logically ordered."),("backup",20,"Includes tested backup."),("validation",25,"Includes data and application checks."),("rollback",20,"Provides rollback path."),("practicality",10,"Actions are implementable.") ]},
 {"task_code":"T08","title":"Translation","prompt":"Translate into clear Hindi (Devanagari): 'The system records the time required to receive the first visible response and the delay between consecutive streamed outputs.' Preserve the technical meaning.","instructions":"Assess semantic fidelity and readability.","rubric":[("meaning",50,"Preserves both timing concepts."),("terminology",25,"Technical terms remain understandable."),("fluency",25,"Natural Hindi.") ]},
 {"task_code":"T09","title":"Classification","prompt":"Classify each item as network QoS, model/inference performance, or subjective QoE: packet loss, TTFT, frustration, bandwidth, queue time, satisfaction, inter-token latency, perceived usefulness. Return a table and justify ambiguous choices briefly.","instructions":"Check classification consistency and rationale.","rubric":[("classification",60,"Correct categories."),("coverage",20,"All eight items included."),("justification",20,"Clear distinction between technical and subjective measures.") ]},
 {"task_code":"T10","title":"Numerical interpretation","prompt":"A participant's TTFT values across three trials are 400 ms, 600 ms and 500 ms. Calculate mean, median and range, and explain why reporting only the mean may hide variability.","instructions":"Check calculations and interpretation.","rubric":[("mean",25,"500 ms."),("median",25,"500 ms."),("range",20,"200 ms."),("interpretation",30,"Explains spread and trial variability.") ]},
 {"task_code":"T11","title":"Constraint consistency","prompt":"You are helping a user plan a 2-day beginner workshop on network measurement. First propose a schedule. Then, in the same answer, ensure the second day includes practical iperf3 and packet-capture exercises, and identify prerequisites.","instructions":"Assess coherence, coverage and internal consistency.","rubric":[("two_day_structure",25,"Clear schedule for both days."),("required_exercises",30,"Includes iPerf3 and packet capture on day two."),("prerequisites",20,"Identifies required tools/skills."),("consistency",25,"No contradictions.") ]},
 {"task_code":"T12","title":"Critical evaluation","prompt":"Evaluate this claim: 'If a chatbot has low network latency, it always provides a good user experience.' Give a balanced argument, at least three counter-factors, and a testable hypothesis.","instructions":"Assess critical reasoning and testability.","rubric":[("position",20,"Rejects the absolute claim with nuance."),("factors",35,"Includes model quality, TTFT/streaming, task success or workload."),("hypothesis",25,"Proposes measurable relationship."),("balance",20,"Distinguishes QoS from QoE.") ]}
]

def task_records():
    out=[]
    for idx, t in enumerate(TASKS, 1):
        x=deepcopy(t)
        x["task_order"]=idx
        x["rubric"]=[{"criterion":c,"weight":w,"description":d} for c,w,d in x["rubric"]]
        x["network_profile"]={"name":"assigned_by_randomisation","latency_ms":0,"jitter_ms":0,"loss_pct":0,"bandwidth_mbps":0}
        out.append(x)
    return out

NASA_TLX = {
 "instrument":"nasa_tlx_raw",
 "version":"NASA-TLX six subscale rating form; local digital capture",
 "scale":{"min":0,"max":100,"step":5},
 "dimensions":[
  {"key":"mental_demand","label":"Mental demand","anchors":["Very low","Very high"]},
  {"key":"physical_demand","label":"Physical demand","anchors":["Very low","Very high"]},
  {"key":"temporal_demand","label":"Temporal demand","anchors":["Very low","Very high"]},
  {"key":"performance","label":"Performance","anchors":["Perfect / successful","Failure / poor"]},
  {"key":"effort","label":"Effort","anchors":["Very low","Very high"]},
  {"key":"frustration","label":"Frustration","anchors":["Very low","Very high"]}
 ],
 "scoring":"Raw TLX = arithmetic mean of the six ratings. Weighted TLX requires the 15 pairwise comparisons and is not inferred from the raw ratings."
}
P852_QOE = {
 "instrument":"p852_aligned_supplemental",
 "version":"Local supplemental items aligned to ITU-T P.852 chatbot subjective-evaluation dimensions; not a verbatim reproduction of the Recommendation questionnaire",
 "scale":{"min":1,"max":5,"labels":["Very poor","Poor","Fair","Good","Excellent"]},
 "items":[
  {"key":"overall_quality","label":"Overall, how would you rate the quality of this chatbot interaction?"},
  {"key":"answer_relevance","label":"How relevant was the answer to your request?"},
  {"key":"answer_completeness","label":"How complete was the answer for your task?"},
  {"key":"ease_of_interaction","label":"How easy was it to interact with the chatbot?"},
  {"key":"response_clarity","label":"How clear and understandable was the response?"},
  {"key":"interaction_satisfaction","label":"How satisfied are you with this interaction?"}
 ],
 "scoring":"Report item distributions and mean/median separately; do not claim this local instrument is the official ITU-T P.852 questionnaire. Obtain supervisor/ethics review before study use."
}


CONSENT_SUMMARY = {
 "version":"1.0.0",
 "title":"LLM QoE Lab research participation",
 "summary":"You will complete 12 chatbot tasks. The study records your prompts and AI responses, pseudonymous participant code, task and model/network condition, response timing and streaming telemetry, network measurements, task scores and questionnaire ratings. Participation is voluntary. You may stop at any time without penalty. Do not enter names, contact details, passwords or other sensitive personal information into the chatbot. Data access, retention, withdrawal and contact details must be completed in the institution-approved consent document before recruitment."
}

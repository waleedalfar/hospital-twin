"""The deterministic rules engine (PROMPT.md §9): same output schema as Gemini, used when Gemini errors,
times out or fails validation twice. Every number it cites comes from the input summary."""

from twin.agent.schema import AgentOutput, CitedMetric, Recommendation
from twin.agent.summary import PatientSummary, Summary, flat_metrics

ER_FULL_HOURS = 2.0
ER_WAIT_MIN = 30.0
WAITING_COUNT = 4
DIVERT_FROM_OCCUPANCY_PCT = 70.0
DIVERT_MINUTES = 120
WARD_PRESSURE_PCT = 0.85
ICU_RESERVE_OCCUPIED = 5


def cite(metrics: dict[str, float], *names: str) -> list[CitedMetric]:
    return [CitedMetric(name=n, value=metrics[n]) for n in names if n in metrics]


def describe_stay(p: PatientSummary) -> str:
    left = f", ~{p.expected_discharge_h:.1f} h left" if p.expected_discharge_h is not None else ""
    return f"{p.id} {p.hours_in_hospital:.1f} h in hospital{left}"


def recommend(s: Summary) -> AgentOutput:
    """Up to four recommendations for the hospital in `s`, in order of importance."""
    m = flat_metrics(s)
    units = {u.unit: u for u in s.units}
    recs: list[Recommendation] = []
    er = units["ER"]
    er_pressure = (er.hours_until_full is not None and er.hours_until_full <= ER_FULL_HOURS) or er.occupied >= er.capacity
    if s.status == "open" and er_pressure and (s.waiting >= WAITING_COUNT or s.er_wait_min >= ER_WAIT_MIN):
        targets = [o for o in s.other_hospitals if o.status == "open" and o.occupancy_pct <= DIVERT_FROM_OCCUPANCY_PCT]
        if targets:
            best = min(targets, key=lambda o: (o.occupancy_pct, o.id))
            recs.append(
                Recommendation(
                    id="rule-divert",
                    hospital_id=s.hospital_id,
                    action="divert_ambulances",
                    targets=[best.id],
                    params={"duration_min": DIVERT_MINUTES},
                    rationale=(
                        f"{s.hospital_name}'s ER is full with {s.waiting} waiting and a {m['er_wait_min']:.0f} min wait. "
                        f"Divert ambulances to {best.name}, which is at {m[f'other.{best.id}.occupancy_pct']:.0f}% of capacity."
                    ),
                    cited_metrics=cite(
                        m,
                        "ER.occupied",
                        "ER.capacity",
                        "waiting",
                        "er_wait_min",
                        f"other.{best.id}.occupancy_pct",
                    ),
                )
            )
    ward, rec_unit = units["WARD"], units["REC"]
    beds = ward.capacity + rec_unit.capacity
    if (ward.occupied + rec_unit.occupied) >= WARD_PRESSURE_PCT * beds and s.expedite_candidates:
        picks = s.expedite_candidates[:3]
        recs.append(
            Recommendation(
                id="rule-discharge",
                hospital_id=s.hospital_id,
                action="expedite_discharge",
                targets=[p.id for p in picks],
                params={},
                rationale=(
                    f"Wards are at {ward.occupied}/{ward.capacity}. These {len(picks)} low-risk patients are expected to go home soonest "
                    f"({', '.join(describe_stay(p) for p in picks)}); discharging them frees beds."
                ),
                cited_metrics=cite(
                    m,
                    "WARD.occupied",
                    "WARD.capacity",
                    *[f"patient.{p.id}.hours_in_hospital" for p in picks],
                    *[f"patient.{p.id}.expected_discharge_h" for p in picks if p.expected_discharge_h is not None],
                ),
            )
        )
    for st in s.staffing:
        if st.required > st.nurses and st.unit in ("ER", "WARD", "ICU", "REC"):
            recs.append(
                Recommendation(
                    id=f"rule-staff-{st.unit}",
                    hospital_id=s.hospital_id,
                    action="call_in_staff",
                    targets=[st.unit],
                    params={"count": min(4, st.required - st.nurses)},
                    rationale=f"{st.unit} has {st.nurses} nurses for a ratio that needs {st.required}; call in {min(4, st.required - st.nurses)}.",
                    cited_metrics=cite(m, f"staff.{st.unit}.nurses", f"staff.{st.unit}.required"),
                )
            )
            break
    icu = units["ICU"]
    if s.high_risk and icu.occupied >= ICU_RESERVE_OCCUPIED and s.open_beds.get("ICU"):
        bed = s.open_beds["ICU"][0]
        recs.append(
            Recommendation(
                id="rule-hold-icu",
                hospital_id=s.hospital_id,
                action="hold_bed",
                targets=[bed],
                params={"minutes": 120},
                rationale=(
                    f"ICU is at {icu.occupied}/{icu.capacity} and {len(s.high_risk)} patients are at high risk. Hold {bed} for an escalation."
                ),
                cited_metrics=cite(m, "ICU.occupied", "ICU.capacity", "high_risk_patients"),
            )
        )
    return AgentOutput(recommendations=recs)

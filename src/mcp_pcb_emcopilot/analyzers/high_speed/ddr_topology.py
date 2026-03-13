"""
DDR memory interface topology validation and byte lane analysis.

Parses DDR net names, groups signals into byte lanes, checks intra-byte
DQ-to-DQS skew against JEDEC limits, validates inter-byte-lane skew,
address/command-to-clock skew, and fly-by topology.

All calculations are pure Python -- no numpy dependency.
"""

import math
import re
from typing import Optional, Dict, List, Any


# ---------------------------------------------------------------------------
# Physical constant
# ---------------------------------------------------------------------------
C0 = 299792458.0  # m/s

# ---------------------------------------------------------------------------
# JEDEC skew limits (ps) by standard
# ---------------------------------------------------------------------------
JEDEC_LIMITS: Dict[str, Dict[str, Any]] = {
    "DDR3": {
        "dq_dqs_skew_ps": 50,         # intra-byte DQ to DQS
        "inter_byte_skew_ps": 200,     # byte-lane to byte-lane
        "addr_cmd_clk_skew_ps": 100,   # address/command to clock
        "clk_pair_skew_ps": 5,         # CK_P vs CK_N
        "bits_per_lane": 8,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "fly_by_required": False,
        "max_data_rate_mtps": 2133,
    },
    "DDR4": {
        "dq_dqs_skew_ps": 10,
        "inter_byte_skew_ps": 100,
        "addr_cmd_clk_skew_ps": 50,
        "clk_pair_skew_ps": 2,
        "bits_per_lane": 8,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "fly_by_required": True,
        "max_data_rate_mtps": 3200,
    },
    "DDR5": {
        "dq_dqs_skew_ps": 5,
        "inter_byte_skew_ps": 50,
        "addr_cmd_clk_skew_ps": 25,
        "clk_pair_skew_ps": 1,
        "bits_per_lane": 8,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "fly_by_required": True,
        "max_data_rate_mtps": 6400,
    },
    "LPDDR4": {
        "dq_dqs_skew_ps": 15,
        "inter_byte_skew_ps": 120,
        "addr_cmd_clk_skew_ps": 60,
        "clk_pair_skew_ps": 3,
        "bits_per_lane": 8,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "fly_by_required": False,
        "max_data_rate_mtps": 4267,
    },
    "LPDDR5": {
        "dq_dqs_skew_ps": 8,
        "inter_byte_skew_ps": 60,
        "addr_cmd_clk_skew_ps": 30,
        "clk_pair_skew_ps": 2,
        "bits_per_lane": 8,
        "impedance_se_ohm": 40,
        "impedance_diff_ohm": 80,
        "fly_by_required": True,
        "max_data_rate_mtps": 6400,
    },
}

# ---------------------------------------------------------------------------
# Net-name patterns (case-insensitive)
# ---------------------------------------------------------------------------
# DQ data bits:  DQ0 .. DQ63, DDR_DQ0, DDR4_DQ15, etc.
_RE_DQ = re.compile(
    r'(?:DDR\d?_?)?(?:LP)?(?:DDR\d?_?)?DQ(\d+)$', re.IGNORECASE
)
# DQS strobes (positive/negative):  DQS0_P, DQS0_N, DDR_DQS1P, etc.
_RE_DQS = re.compile(
    r'(?:DDR\d?_?)?(?:LP)?(?:DDR\d?_?)?DQS(\d+)[_]?([PN])', re.IGNORECASE
)
# DM / DBI (data mask / data bus inversion):  DM0, DBI0, etc.
_RE_DM = re.compile(
    r'(?:DDR\d?_?)?(?:LP)?(?:DDR\d?_?)?(?:DM|DBI)(\d+)', re.IGNORECASE
)
# Clock:  CK_P, CK_N, CLK_P, DDR_CK0_P, etc.
_RE_CK = re.compile(
    r'(?:DDR\d?_?)?(?:LP)?(?:DDR\d?_?)?C(?:L)?K(\d*)[_]?([PN])', re.IGNORECASE
)
# Bank address:  BA0-BA2, BG0-BG1  (must check BEFORE address to avoid BA0 matching A0)
_RE_BA = re.compile(
    r'(?:DDR\d?_?)?(?:LP)?(?:DDR\d?_?)?(?:BA|BG)(\d+)$', re.IGNORECASE
)
# Address:  A0-A17, ADDR0-ADDR17, DDR_A0, etc.
# Negative lookbehind prevents matching BA0 as A0
_RE_ADDR = re.compile(
    r'(?:DDR\d?_?)?(?:LP)?(?:DDR\d?_?)?(?:(?<![A-Z])A|ADDR)(\d+)$', re.IGNORECASE
)
# Command/control:  RAS, CAS, WE, CS, CKE, ODT, RESET, ACT
_RE_CMD = re.compile(
    r'(?:DDR\d?_?)?(?:LP)?(?:DDR\d?_?)?'
    r'(RAS|CAS|WE|CS|CKE|ODT|RESET|ACT|PAR)(?:_?N?)?(\d*)$',
    re.IGNORECASE,
)


def _classify_ddr_net(net_name: str) -> Optional[Dict[str, Any]]:
    """Classify a single net name into a DDR signal group.

    Returns a dict with keys ``group``, ``index`` (bit/lane number),
    ``polarity`` (P/N for diff pairs), or *None* if not DDR.
    """
    m = _RE_DQ.search(net_name)
    if m:
        return {"group": "dq", "index": int(m.group(1)), "polarity": None}

    m = _RE_DQS.search(net_name)
    if m:
        return {"group": "dqs", "index": int(m.group(1)),
                "polarity": m.group(2).upper()}

    m = _RE_DM.search(net_name)
    if m:
        return {"group": "dm", "index": int(m.group(1)), "polarity": None}

    m = _RE_CK.search(net_name)
    if m:
        idx = int(m.group(1)) if m.group(1) else 0
        return {"group": "ck", "index": idx, "polarity": m.group(2).upper()}

    # Check BA/BG before address (BA0 would otherwise match the A0 address pattern)
    m = _RE_BA.search(net_name)
    if m:
        return {"group": "ba", "index": int(m.group(1)), "polarity": None}

    m = _RE_ADDR.search(net_name)
    if m:
        return {"group": "addr", "index": int(m.group(1)), "polarity": None}

    m = _RE_CMD.search(net_name)
    if m:
        idx = int(m.group(2)) if m.group(2) else 0
        return {"group": "cmd", "index": idx, "polarity": None,
                "signal": m.group(1).upper()}

    return None


def _prop_delay_ps_per_mm(dielectric_constant: float = 4.3) -> float:
    """Default propagation delay in ps/mm for FR4-like substrate."""
    er_eff = (dielectric_constant + 1.0) / 2.0 + (dielectric_constant - 1.0) / 3.0
    return math.sqrt(er_eff) / (C0 * 1e-9)  # ps/mm


# ===================================================================
# Public API
# ===================================================================

def validate_ddr_topology(
    classified_nets: Any,
    trace_lengths: Optional[Dict[str, float]] = None,
    ddr_standard: str = "DDR4",
    dielectric_constant: float = 4.3,
) -> dict:
    """Validate DDR topology from classified net data.

    Parameters
    ----------
    classified_nets : NetClassificationResult | dict | list
        Output from ``pcb_classify_nets``.  Accepts either:
        - a ``NetClassificationResult`` object (has ``.classified_nets``),
        - a dict with key ``"nets"`` (from serialised result),
        - a plain list of ``NetClassification`` / dicts.
    trace_lengths : dict[str, float] or None
        Optional mapping of net_name -> routed length in mm.  If *None*,
        length-based skew checks are skipped and only structural checks run.
    ddr_standard : str
        DDR standard to validate against (DDR3, DDR4, DDR5, LPDDR4, LPDDR5).
    dielectric_constant : float
        Substrate Er for propagation-delay conversion (default 4.3).

    Returns
    -------
    dict
        byte_lanes, skew analysis, timing margins, topology assessment,
        issues list, and overall pass/fail.
    """
    # --- Normalise input -----------------------------------------------
    nets_list: list = []
    if hasattr(classified_nets, "classified_nets"):
        # NetClassificationResult object
        nets_list = classified_nets.classified_nets
    elif isinstance(classified_nets, dict) and "nets" in classified_nets:
        nets_list = classified_nets["nets"]
    elif isinstance(classified_nets, list):
        nets_list = classified_nets
    else:
        return {"error": "classified_nets must be a NetClassificationResult, dict, or list"}

    # --- Identify DDR signals ------------------------------------------
    ddr_signals: Dict[str, Dict] = {}  # net_name -> classification info
    for net in nets_list:
        if isinstance(net, dict):
            name = net.get("name", net.get("net_name", ""))
            cat = net.get("category", "")
        else:
            name = getattr(net, "net_name", "")
            cat = getattr(net, "category", "")

        info = _classify_ddr_net(name)
        if info is not None:
            info["net_name"] = name
            ddr_signals[name] = info
        elif "ddr" in cat.lower():
            # Fallback: the classifier said it's DDR even if our regex didn't match
            ddr_signals[name] = {"group": "unknown_ddr", "index": 0,
                                 "polarity": None, "net_name": name}

    if not ddr_signals:
        return {
            "ddr_nets_found": 0,
            "byte_lanes": [],
            "issues": [{"severity": "info",
                        "description": "No DDR nets detected in design"}],
            "pass_fail": "N/A",
        }

    # --- Group into byte lanes -----------------------------------------
    bits_per_lane = JEDEC_LIMITS.get(ddr_standard, JEDEC_LIMITS["DDR4"])["bits_per_lane"]

    byte_lanes: Dict[int, Dict[str, Any]] = {}
    clock_nets: list = []
    addr_nets: list = []
    cmd_nets: list = []

    for name, info in ddr_signals.items():
        grp = info["group"]
        idx = info["index"]

        if grp == "dq":
            lane = idx // bits_per_lane
            byte_lanes.setdefault(lane, {"dq": {}, "dqs_p": None, "dqs_n": None,
                                          "dm": None, "lane": lane})
            byte_lanes[lane]["dq"][idx] = name
        elif grp == "dqs":
            lane = idx
            byte_lanes.setdefault(lane, {"dq": {}, "dqs_p": None, "dqs_n": None,
                                          "dm": None, "lane": lane})
            if info["polarity"] == "P":
                byte_lanes[lane]["dqs_p"] = name
            else:
                byte_lanes[lane]["dqs_n"] = name
        elif grp == "dm":
            lane = idx
            byte_lanes.setdefault(lane, {"dq": {}, "dqs_p": None, "dqs_n": None,
                                          "dm": None, "lane": lane})
            byte_lanes[lane]["dm"] = name
        elif grp == "ck":
            clock_nets.append((name, info))
        elif grp == "addr" or grp == "ba":
            addr_nets.append((name, info))
        elif grp == "cmd":
            cmd_nets.append((name, info))

    # --- Spec lookup ---------------------------------------------------
    spec = JEDEC_LIMITS.get(ddr_standard, JEDEC_LIMITS["DDR4"])
    delay_ps_mm = _prop_delay_ps_per_mm(dielectric_constant)
    issues: list = []

    # --- Intra-byte DQ-to-DQS skew ------------------------------------
    lane_results: list = []
    for lane_id in sorted(byte_lanes.keys()):
        bl = byte_lanes[lane_id]
        lane_info: Dict[str, Any] = {
            "lane": lane_id,
            "dq_count": len(bl["dq"]),
            "dqs_p": bl["dqs_p"],
            "dqs_n": bl["dqs_n"],
            "dm": bl["dm"],
            "dq_nets": bl["dq"],
        }

        if trace_lengths and bl["dqs_p"] and bl["dqs_p"] in trace_lengths:
            dqs_len = trace_lengths[bl["dqs_p"]]
            lane_info["dqs_length_mm"] = round(dqs_len, 2)

            max_skew_ps = 0.0
            dq_skews: Dict[str, float] = {}
            for bit_idx, dq_name in bl["dq"].items():
                if dq_name in trace_lengths:
                    dq_len = trace_lengths[dq_name]
                    skew_mm = abs(dq_len - dqs_len)
                    skew_ps = skew_mm * delay_ps_mm
                    dq_skews[dq_name] = round(skew_ps, 2)
                    if skew_ps > max_skew_ps:
                        max_skew_ps = skew_ps

            lane_info["dq_dqs_skews_ps"] = dq_skews
            lane_info["max_dq_dqs_skew_ps"] = round(max_skew_ps, 2)
            limit = spec["dq_dqs_skew_ps"]
            lane_info["dq_dqs_skew_limit_ps"] = limit
            lane_info["intra_byte_pass"] = max_skew_ps <= limit

            if max_skew_ps > limit:
                worst_net = max(dq_skews, key=dq_skews.get) if dq_skews else "?"
                issues.append({
                    "severity": "critical" if max_skew_ps > limit * 2 else "high",
                    "type": "dq_dqs_skew",
                    "byte_lane": lane_id,
                    "description": (
                        f"Byte lane {lane_id}: DQ-DQS skew {max_skew_ps:.1f} ps "
                        f"exceeds {ddr_standard} limit of {limit} ps "
                        f"(worst: {worst_net})"
                    ),
                    "measured_ps": round(max_skew_ps, 2),
                    "limit_ps": limit,
                    "recommendation": (
                        f"Adjust {worst_net} length to match DQS within {limit} ps"
                    ),
                })
        else:
            lane_info["intra_byte_pass"] = None  # can't check without lengths

        # Structural: missing DQS
        if not bl["dqs_p"] or not bl["dqs_n"]:
            issues.append({
                "severity": "critical",
                "type": "missing_dqs",
                "byte_lane": lane_id,
                "description": f"Byte lane {lane_id}: missing DQS differential pair",
                "recommendation": "Ensure DQS_P and DQS_N are both routed",
            })

        lane_results.append(lane_info)

    # --- Inter-byte-lane skew ------------------------------------------
    inter_byte_skew_ps = 0.0
    inter_byte_pass = True
    if trace_lengths and len(lane_results) > 1:
        dqs_delays: Dict[int, float] = {}
        for lr in lane_results:
            dqs_name = byte_lanes[lr["lane"]]["dqs_p"]
            if dqs_name and dqs_name in trace_lengths:
                dqs_delays[lr["lane"]] = trace_lengths[dqs_name] * delay_ps_mm

        if len(dqs_delays) > 1:
            min_d = min(dqs_delays.values())
            max_d = max(dqs_delays.values())
            inter_byte_skew_ps = max_d - min_d
            limit = spec["inter_byte_skew_ps"]
            inter_byte_pass = inter_byte_skew_ps <= limit

            if not inter_byte_pass:
                issues.append({
                    "severity": "high",
                    "type": "inter_byte_skew",
                    "description": (
                        f"Inter-byte-lane skew {inter_byte_skew_ps:.1f} ps "
                        f"exceeds {ddr_standard} limit of {limit} ps"
                    ),
                    "measured_ps": round(inter_byte_skew_ps, 2),
                    "limit_ps": limit,
                    "recommendation": "Match DQS lengths across byte lanes",
                })

    # --- Address/Command to clock skew ---------------------------------
    addr_cmd_skew_ps = 0.0
    addr_cmd_pass = True
    if trace_lengths:
        # Find clock length (use CK_P as reference)
        ck_p_name = None
        for name, info in clock_nets:
            if info.get("polarity") == "P":
                ck_p_name = name
                break
        if not ck_p_name and clock_nets:
            ck_p_name = clock_nets[0][0]

        if ck_p_name and ck_p_name in trace_lengths:
            ck_delay = trace_lengths[ck_p_name] * delay_ps_mm
            all_ac_nets = addr_nets + cmd_nets
            ac_delays = []
            for name, _ in all_ac_nets:
                if name in trace_lengths:
                    ac_delays.append(trace_lengths[name] * delay_ps_mm)
            if ac_delays:
                max_ac = max(ac_delays)
                min_ac = min(ac_delays)
                # Skew is worst-case difference from clock
                addr_cmd_skew_ps = max(abs(max_ac - ck_delay), abs(min_ac - ck_delay))
                limit = spec["addr_cmd_clk_skew_ps"]
                addr_cmd_pass = addr_cmd_skew_ps <= limit

                if not addr_cmd_pass:
                    issues.append({
                        "severity": "high",
                        "type": "addr_cmd_clk_skew",
                        "description": (
                            f"Address/Command-to-Clock skew {addr_cmd_skew_ps:.1f} ps "
                            f"exceeds {ddr_standard} limit of {limit} ps"
                        ),
                        "measured_ps": round(addr_cmd_skew_ps, 2),
                        "limit_ps": limit,
                        "recommendation": "Match addr/cmd trace lengths to clock reference",
                    })

    # --- Clock pair skew -----------------------------------------------
    clk_pair_skew_ps = 0.0
    clk_pair_pass = True
    if trace_lengths and len(clock_nets) >= 2:
        ck_p_len = None
        ck_n_len = None
        for name, info in clock_nets:
            if name in trace_lengths:
                if info.get("polarity") == "P":
                    ck_p_len = trace_lengths[name]
                elif info.get("polarity") == "N":
                    ck_n_len = trace_lengths[name]
        if ck_p_len is not None and ck_n_len is not None:
            clk_pair_skew_ps = abs(ck_p_len - ck_n_len) * delay_ps_mm
            limit = spec["clk_pair_skew_ps"]
            clk_pair_pass = clk_pair_skew_ps <= limit
            if not clk_pair_pass:
                issues.append({
                    "severity": "critical",
                    "type": "clk_pair_skew",
                    "description": (
                        f"Clock P/N pair skew {clk_pair_skew_ps:.1f} ps "
                        f"exceeds {ddr_standard} limit of {limit} ps"
                    ),
                    "measured_ps": round(clk_pair_skew_ps, 2),
                    "limit_ps": limit,
                    "recommendation": "Precisely match CK_P and CK_N lengths",
                })

    # --- Fly-by topology check -----------------------------------------
    fly_by_info = {"required": spec["fly_by_required"], "detected": None}
    if spec["fly_by_required"]:
        fly_by_info["note"] = (
            f"{ddr_standard} requires fly-by topology for address/command/clock. "
            "Verify sequential DRAM connections in layout."
        )

    # --- Overall -------------------------------------------------------
    critical_count = sum(1 for i in issues if i.get("severity") == "critical")
    high_count = sum(1 for i in issues if i.get("severity") == "high")
    overall_pass = critical_count == 0 and high_count == 0

    return {
        "ddr_standard": ddr_standard,
        "ddr_nets_found": len(ddr_signals),
        "byte_lane_count": len(lane_results),
        "byte_lanes": lane_results,
        "inter_byte_skew_ps": round(inter_byte_skew_ps, 2),
        "inter_byte_pass": inter_byte_pass,
        "addr_cmd_clk_skew_ps": round(addr_cmd_skew_ps, 2),
        "addr_cmd_pass": addr_cmd_pass,
        "clk_pair_skew_ps": round(clk_pair_skew_ps, 2),
        "clk_pair_pass": clk_pair_pass,
        "clock_nets": [n for n, _ in clock_nets],
        "addr_nets": [n for n, _ in addr_nets],
        "cmd_nets": [n for n, _ in cmd_nets],
        "fly_by_topology": fly_by_info,
        "issues": issues,
        "issue_count": len(issues),
        "critical_count": critical_count,
        "high_count": high_count,
        "pass_fail": "PASS" if overall_pass else "FAIL",
    }


def analyze_ddr_timing_budget(
    ddr_standard: str,
    data_rate_mtps: int,
    byte_lanes: List[Dict[str, Any]],
    dielectric_constant: float = 4.3,
) -> dict:
    """Detailed per-lane timing margin analysis against JEDEC budget.

    Parameters
    ----------
    ddr_standard : str
        DDR3, DDR4, DDR5, LPDDR4, LPDDR5.
    data_rate_mtps : int
        Data rate in MT/s (e.g. 3200).
    byte_lanes : list[dict]
        Each dict should have:
        - ``lane`` (int)
        - ``dqs_length_mm`` (float)
        - ``dq_lengths_mm`` (list[float])  -- one per DQ bit
        Optionally: ``dqs_n_length_mm``, ``dm_length_mm``.
    dielectric_constant : float
        Substrate Er (default 4.3).

    Returns
    -------
    dict
        Per-lane timing margins, setup/hold analysis, overall compliance.
    """
    spec = JEDEC_LIMITS.get(ddr_standard, JEDEC_LIMITS["DDR4"])
    delay_ps_mm = _prop_delay_ps_per_mm(dielectric_constant)
    ui_ps = 1e6 / data_rate_mtps  # unit interval in ps

    # Timing budget components (typical JEDEC allocation)
    # These are simplified allocations; real JEDEC specs are more detailed
    t_dqss_ps = ui_ps * 0.25   # DQS-DQ launch window (fraction of UI)
    t_controller_setup_ps = ui_ps * 0.15  # controller setup time
    t_controller_hold_ps = ui_ps * 0.10   # controller hold time
    t_jitter_ps = 15.0 + 0.01 * data_rate_mtps  # clock + data jitter budget

    lane_results = []
    all_pass = True

    for bl in byte_lanes:
        lane_id = bl.get("lane", 0)
        dqs_len = bl.get("dqs_length_mm", 0.0)
        dq_lens = bl.get("dq_lengths_mm", [])
        dqs_n_len = bl.get("dqs_n_length_mm")
        dm_len = bl.get("dm_length_mm")

        lane_info: Dict[str, Any] = {
            "lane": lane_id,
            "dqs_delay_ps": round(dqs_len * delay_ps_mm, 1),
            "dq_delays_ps": [round(l * delay_ps_mm, 1) for l in dq_lens],
            "bits": [],
        }

        # Per-bit analysis
        max_skew = 0.0
        for i, dq_len in enumerate(dq_lens):
            skew_mm = abs(dq_len - dqs_len)
            skew_ps = skew_mm * delay_ps_mm

            # Setup margin = UI/2 - t_dqss - skew - jitter - controller_setup
            setup_margin = ui_ps / 2.0 - t_dqss_ps - skew_ps - t_jitter_ps - t_controller_setup_ps
            # Hold margin = UI/2 - skew - jitter - controller_hold
            hold_margin = ui_ps / 2.0 - skew_ps - t_jitter_ps - t_controller_hold_ps

            bit_pass = setup_margin > 0 and hold_margin > 0
            if not bit_pass:
                all_pass = False

            if skew_ps > max_skew:
                max_skew = skew_ps

            lane_info["bits"].append({
                "bit": i,
                "dq_length_mm": round(dq_len, 2),
                "dq_delay_ps": round(dq_len * delay_ps_mm, 1),
                "skew_ps": round(skew_ps, 1),
                "setup_margin_ps": round(setup_margin, 1),
                "hold_margin_ps": round(hold_margin, 1),
                "pass": bit_pass,
            })

        lane_info["max_dq_dqs_skew_ps"] = round(max_skew, 1)
        lane_info["jedec_skew_limit_ps"] = spec["dq_dqs_skew_ps"]
        lane_info["intra_byte_pass"] = max_skew <= spec["dq_dqs_skew_ps"]

        # DQS pair skew (if N length provided)
        if dqs_n_len is not None:
            dqs_pair_skew = abs(dqs_len - dqs_n_len) * delay_ps_mm
            lane_info["dqs_pair_skew_ps"] = round(dqs_pair_skew, 1)

        if not lane_info["intra_byte_pass"]:
            all_pass = False

        lane_results.append(lane_info)

    return {
        "ddr_standard": ddr_standard,
        "data_rate_mtps": data_rate_mtps,
        "unit_interval_ps": round(ui_ps, 1),
        "timing_budget": {
            "dqss_window_ps": round(t_dqss_ps, 1),
            "controller_setup_ps": round(t_controller_setup_ps, 1),
            "controller_hold_ps": round(t_controller_hold_ps, 1),
            "jitter_budget_ps": round(t_jitter_ps, 1),
        },
        "jedec_limits": {
            "dq_dqs_skew_ps": spec["dq_dqs_skew_ps"],
            "inter_byte_skew_ps": spec["inter_byte_skew_ps"],
            "addr_cmd_clk_skew_ps": spec["addr_cmd_clk_skew_ps"],
        },
        "byte_lanes": lane_results,
        "lane_count": len(lane_results),
        "all_pass": all_pass,
        "dielectric_constant": dielectric_constant,
        "prop_delay_ps_per_mm": round(delay_ps_mm, 3),
    }

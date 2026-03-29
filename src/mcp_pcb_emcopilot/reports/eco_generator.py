"""ECO (Engineering Change Order) generator for EDA tools."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


class ECOGenerator:
    """Generate structured ECOs from review findings and recommendations."""

    def generate(self, design: Any, review_result: Any,
                 recommendations: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """Generate ECO list from review result and actionable recommendations."""
        ecos: List[Dict[str, Any]] = []
        eco_id = 1

        if recommendations:
            for rec in recommendations:
                eco = {
                    "id": eco_id,
                    "type": rec.get("action_type", "review"),
                    "priority": rec.get("priority", "medium"),
                    "description": rec.get("description", ""),
                    "category": rec.get("category", "general"),
                    "coordinates": rec.get("coordinates", {}),
                    "parameters": rec.get("parameters", {}),
                    "effort": rec.get("effort", "moderate"),
                    "finding_ref": rec.get("finding_ref", ""),
                }
                ecos.append(eco)
                eco_id += 1
        elif review_result:
            # Generate from findings directly
            for dr in getattr(review_result, 'domain_results', []):
                for f in dr.findings:
                    if f.severity not in ('critical', 'warning', 'high'):
                        continue
                    eco = {
                        "id": eco_id,
                        "type": self._infer_eco_type(f, dr.domain),
                        "priority": f.severity,
                        "description": f"{f.title}: {f.description[:120]}",
                        "category": dr.domain,
                        "coordinates": {
                            "x_mm": getattr(f, 'location_x_mm', None),
                            "y_mm": getattr(f, 'location_y_mm', None),
                            "layer": getattr(f, 'location_layer', None),
                        },
                        "parameters": {},
                        "effort": self._estimate_effort(f, dr.domain),
                        "finding_ref": f"{dr.domain}:{f.title}",
                    }
                    ecos.append(eco)
                    eco_id += 1

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4}
        ecos.sort(key=lambda e: priority_order.get(e["priority"], 5))
        return ecos

    def export_json(self, ecos: List[Dict], output_path: str) -> str:
        """Export ECOs as JSON file."""
        with open(output_path, 'w') as f:
            json.dump({"ecos": ecos, "count": len(ecos),
                       "by_effort": {
                           "trivial": sum(1 for e in ecos if e["effort"] == "trivial"),
                           "moderate": sum(1 for e in ecos if e["effort"] == "moderate"),
                           "respin": sum(1 for e in ecos if e["effort"] == "respin"),
                       }}, f, indent=2)
        return output_path

    def export_csv(self, ecos: List[Dict], output_path: str) -> str:
        """Export ECOs as CSV for import into issue trackers."""
        import csv
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Type", "Priority", "Category", "Description", "Effort", "X_mm", "Y_mm", "Layer"])
            for e in ecos:
                coords = e.get("coordinates", {})
                writer.writerow([
                    e["id"], e["type"], e["priority"], e["category"],
                    e["description"][:200], e["effort"],
                    coords.get("x_mm", ""), coords.get("y_mm", ""), coords.get("layer", ""),
                ])
        return output_path

    def _infer_eco_type(self, finding: Any, domain: str) -> str:
        desc = (finding.description or "").lower()
        if "trace" in desc and ("width" in desc or "narrow" in desc):
            return "trace_width_change"
        if "filter" in desc or "cap" in desc or "decoupl" in desc:
            return "add_component"
        if "impedance" in desc:
            return "trace_width_change"
        if "skew" in desc or "spread" in desc or "length" in desc:
            return "reroute"
        if "via" in desc:
            return "add_via"
        return "review"

    def _estimate_effort(self, finding: Any, domain: str) -> str:
        if finding.severity == "critical":
            if "impedance" in domain and "inner" in (finding.description or "").lower():
                return "respin"  # Stackup change needed
            if "filter" in (finding.description or "").lower():
                return "moderate"  # Add component
            return "moderate"
        return "trivial"

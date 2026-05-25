"""
OpenSCENARIO Fragment Dataset Validation Script
Validates each domain CSV file across three levels:
  1. Field completeness  (non-empty description & code)
  2. Well-formed XML
  3. Domain-specific structure (required elements & attributes)
"""

import csv
import xml.etree.ElementTree as ET
import os
import sys
from dataclasses import dataclass, field
from typing import List, Tuple

# ── Domain-specific validation rules ─────────────────────────────────────────

DOMAIN_RULES = {
    "agent": [
        ("ScenarioObject", ["name"]),
    ],
    # position: checked via POSITION_INDICATORS (OR logic) — see check_structure()
    "position": [],
    # speed: AbsoluteTargetSpeed OR RelativeTargetSpeed must exist (OR logic)
    "speed": [
        ("SpeedAction", []),
    ],
    "actor": [
        ("Actors", []),
    ],
    "condition": [
        ("Condition", ["name"]),
    ],
    "behavior": [
        ("PrivateAction", []),
    ],
}

# position domain: at least one of these tags must appear
POSITION_INDICATORS = {
    "LanePosition", "WorldPosition", "RelativeWorldPosition",
    "RelativeObjectPosition", "RoadPosition", "RelativeRoadPosition",
    "RelativeTargetPosition", "RelativeLanePosition", "RoutePosition",
    "FollowTrajectoryAction", "RoutingAction",
    "AssignRouteAction", "AcquirePositionAction",
}

# speed domain: at least one of these target speed tags must appear
SPEED_TARGET_INDICATORS = {
    "AbsoluteTargetSpeed",
    "RelativeTargetSpeed",
}


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class FragmentResult:
    row_index: int
    description: str
    well_formed: bool
    structure_valid: bool
    field_complete: bool
    errors: List[str] = field(default_factory=list)

    @property
    def passed(self):
        return self.well_formed and self.structure_valid and self.field_complete


# ── Validation functions ──────────────────────────────────────────────────────

def check_field_complete(description: str, code: str) -> Tuple[bool, List[str]]:
    errors = []
    if not description or not description.strip():
        errors.append("Empty description field")
    if not code or not code.strip():
        errors.append("Empty code field")
    return len(errors) == 0, errors


def check_well_formed(code: str) -> Tuple[bool, List[str]]:
    try:
        ET.fromstring(f"<root>{code}</root>")
        return True, []
    except ET.ParseError as e:
        return False, [f"XML parse error: {e}"]


def check_structure(code: str, domain: str) -> Tuple[bool, List[str]]:
    errors = []
    try:
        root = ET.fromstring(f"<root>{code}</root>")
    except ET.ParseError:
        return False, ["Cannot check structure: XML is malformed"]

    all_tags = {elem.tag for elem in root.iter()}

    # General rules (AND logic: all must be present)
    for required_tag, required_attrs in DOMAIN_RULES.get(domain, []):
        found = list(root.iter(required_tag))
        if not found:
            errors.append(f"Missing required element <{required_tag}>")
            continue
        for attr in required_attrs:
            val = found[0].get(attr, "")
            if not val.strip():
                errors.append(f"<{required_tag}> missing or empty attribute '{attr}'")

    # position: OR logic — at least one position indicator must exist
    if domain == "position":
        if not all_tags.intersection(POSITION_INDICATORS):
            errors.append(
                f"No position indicator found. Expected one of: "
                f"{', '.join(sorted(POSITION_INDICATORS))}"
            )

    # speed: OR logic — AbsoluteTargetSpeed or RelativeTargetSpeed must exist
    if domain == "speed":
        if not all_tags.intersection(SPEED_TARGET_INDICATORS):
            errors.append(
                f"No speed target found. Expected one of: "
                f"{', '.join(sorted(SPEED_TARGET_INDICATORS))}"
            )

    # actor: EntityRef is recommended but some actor fragments may use
    #        selectTriggeringEntities="true" without explicit EntityRef
    if domain == "actor":
        actors_elems = list(root.iter("Actors"))
        if actors_elems:
            sel = actors_elems[0].get("selectTriggeringEntities", "false")
            has_entity_ref = bool(list(root.iter("EntityRef")))
            if not has_entity_ref and sel.lower() != "true":
                errors.append(
                    "<Actors> has no <EntityRef> and selectTriggeringEntities is not 'true'"
                )

    return len(errors) == 0, errors


# ── Per-file validation ───────────────────────────────────────────────────────

def validate_csv(filepath: str, domain: str) -> List[FragmentResult]:
    results = []
    with open(filepath, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            description = row.get("description", "")
            code = row.get("code", "")

            errors = []

            fc_ok, fc_errors = check_field_complete(description, code)
            errors.extend(fc_errors)

            wf_ok, wf_errors = check_well_formed(code)
            errors.extend(wf_errors)

            if wf_ok:
                st_ok, st_errors = check_structure(code, domain)
                errors.extend(st_errors)
            else:
                st_ok = False

            results.append(FragmentResult(
                row_index=i,
                description=description[:60] + "..." if len(description) > 60 else description,
                well_formed=wf_ok,
                structure_valid=st_ok,
                field_complete=fc_ok,
                errors=errors,
            ))
    return results


# ── Summary & failure printers ────────────────────────────────────────────────

def print_summary(all_results: dict):
    DOMAINS = ["agent", "position", "speed", "actor", "condition", "behavior"]
    header = (f"{'Domain':<12} {'Total':>6} {'Field OK':>9} "
              f"{'XML OK':>8} {'Struct OK':>10} {'Pass':>6} {'Pass%':>7}")
    sep = "=" * len(header)
    print(f"\n{sep}")
    print("OpenSCENARIO Fragment Dataset — Validation Summary")
    print(sep)
    print(header)
    print("-" * len(header))

    grand_total = grand_pass = 0
    for domain in DOMAINS:
        if domain not in all_results:
            continue
        results = all_results[domain]
        total     = len(results)
        field_ok  = sum(1 for r in results if r.field_complete)
        xml_ok    = sum(1 for r in results if r.well_formed)
        struct_ok = sum(1 for r in results if r.structure_valid)
        passed    = sum(1 for r in results if r.passed)
        pct       = passed / total * 100 if total else 0
        print(f"{domain:<12} {total:>6} {field_ok:>9} {xml_ok:>8} "
              f"{struct_ok:>10} {passed:>6} {pct:>6.1f}%")
        grand_total += total
        grand_pass  += passed

    print("-" * len(header))
    grand_pct = grand_pass / grand_total * 100 if grand_total else 0
    print(f"{'TOTAL':<12} {grand_total:>6} {'':>9} {'':>8} "
          f"{'':>10} {grand_pass:>6} {grand_pct:>6.1f}%")
    print(sep)


def print_failures(all_results: dict, max_per_domain: int = 5):
    print(f"\n--- Failed Fragments (up to {max_per_domain} per domain) ---")
    for domain in ["agent", "position", "speed", "actor", "condition", "behavior"]:
        if domain not in all_results:
            continue
        failures = [r for r in all_results[domain] if not r.passed]
        if not failures:
            print(f"\n[{domain}] All fragments passed.")
            continue
        print(f"\n[{domain}] {len(failures)} failure(s):")
        for r in failures[:max_per_domain]:
            print(f"  Row {r.row_index}: {r.description}")
            for e in r.errors:
                print(f"    ERROR: {e}")
        if len(failures) > max_per_domain:
            print(f"  ... and {len(failures) - max_per_domain} more.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    DOMAINS  = ["agent", "position", "speed", "actor", "condition", "behavior"]
    all_results = {}

    for domain in DOMAINS:
        candidates = [
            os.path.join(data_dir, f"{domain}s.csv"),
            os.path.join(data_dir, f"{domain}.csv"),
            os.path.join(data_dir, f"{domain}_fragments.csv"),
        ]
        filepath = next((p for p in candidates if os.path.exists(p)), None)
        if filepath is None:
            print(f"[WARNING] CSV not found for domain '{domain}' in {data_dir}. Skipping.")
            continue
        print(f"Validating [{domain}] from {filepath} ...")
        all_results[domain] = validate_csv(filepath, domain)

    if not all_results:
        print("No CSV files found.")
        print("  Usage: python validate_fragments.py /path/to/csv/directory")
        sys.exit(1)

    print_summary(all_results)
    print_failures(all_results)


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


STATUS_VALUE = {"closed": 1.0, "partial": 0.5, "open": 0.0}


# Stable trace links.  These IDs are deliberately independent of CSV row order so
# that a report, deviation, or future design baseline can refer to them without
# being invalidated when the tables grow.  Controls are currently composite
# control bundles described by each risk row; they remain open until their
# implementation and effectiveness evidence are approved.
REQUIREMENT_RISK_LINKS: dict[str, tuple[str, ...]] = {
    "REQ-USE-001": ("R-001", "R-002", "R-003", "R-010", "R-014", "R-017", "R-022", "R-027", "R-031", "R-039"),
    "REQ-REG-001": ("R-001", "R-010", "R-017", "R-039"),
    "REQ-HF-001": ("R-005", "R-006", "R-007", "R-014", "R-020", "R-024", "R-025", "R-031", "R-033"),
    "REQ-HF-002": ("R-038",),
    "REQ-HMI-001": ("R-001", "R-020", "R-024"),
    "REQ-HMI-002": ("R-026",),
    "REQ-SAF-001": ("R-001", "R-002", "R-005", "R-007", "R-013", "R-015", "R-024", "R-025", "R-031", "R-032", "R-033"),
    "REQ-FOL-001": ("R-029", "R-030"),
    "REQ-FOL-002": ("R-027", "R-028", "R-029", "R-030", "R-031"),
    "REQ-FOL-003": ("R-001", "R-015", "R-017", "R-032"),
    "REQ-FOL-004": ("R-031",),
    "REQ-CAF-001": ("R-003", "R-005", "R-006", "R-033"),
    "REQ-CAF-002": ("R-006", "R-024", "R-033"),
    "REQ-SAF-002": ("R-014",),
    "REQ-MOB-001": ("R-001", "R-002", "R-003", "R-016"),
    "REQ-MOB-002": ("R-003", "R-004", "R-030"),
    "REQ-MOB-003": ("R-025",),
    "REQ-STR-001": ("R-004", "R-007", "R-009", "R-025", "R-033"),
    "REQ-STB-001": ("R-003", "R-008", "R-025", "R-033"),
    "REQ-PWR-001": ("R-010", "R-011", "R-012", "R-019"),
    "REQ-EMC-001": ("R-016",),
    "REQ-ENV-001": ("R-012", "R-019", "R-021", "R-026", "R-029"),
    "REQ-CYB-001": ("R-017", "R-027", "R-032", "R-035", "R-036", "R-037"),
    "REQ-PRI-001": ("R-017", "R-018", "R-036", "R-037"),
    "REQ-CTX-001": ("R-034", "R-036"),
    "REQ-CTX-002": ("R-015", "R-034", "R-035"),
    "REQ-CTX-003": ("R-017", "R-027", "R-036"),
    "REQ-CTX-004": ("R-018", "R-037"),
    "REQ-ID-001": ("R-005", "R-006", "R-020", "R-024", "R-025", "R-026", "R-033"),
    "REQ-CMF-001": ("R-012", "R-020", "R-021", "R-026", "R-029"),
    "REQ-DFM-001": ("R-004", "R-006", "R-007", "R-009", "R-013", "R-020", "R-025", "R-033"),
    "REQ-BOM-001": ("R-004", "R-010", "R-011", "R-012", "R-016", "R-019", "R-021", "R-026", "R-029", "R-030", "R-032"),
    "REQ-CFG-001": ("R-040",),
    "REQ-SVC-001": ("R-002", "R-004", "R-010", "R-011", "R-015", "R-017", "R-019", "R-023", "R-037"),
    "REQ-MFG-001": ("R-001", "R-002", "R-004", "R-007", "R-009", "R-011", "R-012", "R-013", "R-015", "R-016", "R-023", "R-025", "R-031", "R-032", "R-033"),
    "REQ-LBL-001": ("R-001", "R-002", "R-003", "R-010", "R-014", "R-017", "R-018", "R-022", "R-023", "R-025", "R-026", "R-027", "R-029", "R-031", "R-033", "R-037", "R-039"),
}


REQUIREMENT_TEST_LINKS: dict[str, tuple[str, ...]] = {
    "REQ-USE-001": ("DV-001", "DV-002", "DV-030", "DV-041", "DV-042"),
    "REQ-REG-001": ("DV-001",),
    "REQ-HF-001": ("DV-002", "DV-004", "DV-005", "DV-015", "DV-034", "DV-041", "DV-043"),
    "REQ-HF-002": ("DV-003",),
    "REQ-HMI-001": ("DV-005", "DV-034"),
    "REQ-HMI-002": ("DV-035",),
    "REQ-SAF-001": ("DV-024", "DV-040", "DV-043", "DV-048"),
    "REQ-FOL-001": ("DV-038", "DV-039"),
    "REQ-FOL-002": ("DV-036", "DV-037", "DV-038", "DV-039", "DV-048"),
    "REQ-FOL-003": ("DV-024", "DV-025", "DV-040"),
    "REQ-FOL-004": ("DV-048",),
    "REQ-CAF-001": ("DV-041", "DV-043"),
    "REQ-CAF-002": ("DV-013", "DV-043"),
    "REQ-SAF-002": ("DV-004", "DV-015", "DV-034"),
    "REQ-MOB-001": ("DV-006", "DV-007", "DV-008", "DV-009", "DV-023", "DV-037"),
    "REQ-MOB-002": ("DV-010", "DV-011", "DV-012"),
    "REQ-MOB-003": ("DV-033",),
    "REQ-STR-001": ("DV-011", "DV-012", "DV-013", "DV-015", "DV-033", "DV-043"),
    "REQ-STB-001": ("DV-006", "DV-007", "DV-010", "DV-016", "DV-033", "DV-043"),
    "REQ-PWR-001": ("DV-017", "DV-018", "DV-019", "DV-020"),
    "REQ-EMC-001": ("DV-023",),
    "REQ-ENV-001": ("DV-020", "DV-021", "DV-022", "DV-026", "DV-027", "DV-035", "DV-038"),
    "REQ-CYB-001": ("DV-023", "DV-024", "DV-025", "DV-036", "DV-040", "DV-045", "DV-046", "DV-047"),
    "REQ-PRI-001": ("DV-025", "DV-026", "DV-046", "DV-047"),
    "REQ-CTX-001": ("DV-044", "DV-046"),
    "REQ-CTX-002": ("DV-045",),
    "REQ-CTX-003": ("DV-036", "DV-046"),
    "REQ-CTX-004": ("DV-047",),
    "REQ-ID-001": ("DV-005", "DV-013", "DV-015", "DV-022", "DV-027", "DV-033", "DV-035", "DV-043"),
    "REQ-CMF-001": ("DV-022", "DV-027", "DV-035", "DV-038"),
    "REQ-DFM-001": ("DV-011", "DV-012", "DV-013", "DV-014", "DV-015", "DV-028", "DV-033", "DV-043"),
    "REQ-BOM-001": ("DV-017", "DV-018", "DV-019", "DV-020", "DV-021", "DV-023", "DV-025", "DV-027", "DV-028", "DV-032", "DV-035", "DV-038", "DV-039", "DV-040", "DV-049"),
    "REQ-CFG-001": ("DV-049",),
    "REQ-SVC-001": ("DV-025", "DV-029", "DV-030", "DV-031", "DV-032", "DV-047"),
    "REQ-MFG-001": ("DV-014", "DV-024", "DV-028", "DV-029", "DV-031", "DV-032"),
    "REQ-LBL-001": ("DV-001", "DV-002", "DV-004", "DV-005", "DV-019", "DV-021", "DV-022", "DV-025", "DV-026", "DV-030", "DV-033", "DV-035", "DV-036", "DV-037", "DV-038", "DV-039", "DV-041", "DV-043", "DV-047"),
}


RISK_TEST_LINKS: dict[str, tuple[str, ...]] = {
    "R-001": ("DV-008", "DV-009", "DV-024", "DV-029", "DV-040"),
    "R-002": ("DV-008", "DV-018", "DV-029", "DV-031", "DV-037"),
    "R-003": ("DV-006", "DV-007", "DV-009", "DV-010", "DV-016", "DV-033", "DV-041", "DV-043"),
    "R-004": ("DV-011", "DV-012", "DV-028", "DV-031", "DV-032", "DV-033"),
    "R-005": ("DV-010", "DV-011", "DV-024", "DV-041"),
    "R-006": ("DV-013", "DV-043"),
    "R-007": ("DV-015", "DV-024", "DV-028"),
    "R-008": ("DV-006", "DV-007", "DV-016"),
    "R-009": ("DV-011", "DV-016", "DV-028", "DV-032"),
    "R-010": ("DV-017", "DV-019", "DV-020", "DV-021", "DV-031"),
    "R-011": ("DV-018", "DV-019", "DV-029", "DV-031"),
    "R-012": ("DV-021", "DV-022", "DV-023", "DV-029"),
    "R-013": ("DV-014", "DV-021", "DV-024", "DV-028", "DV-032"),
    "R-014": ("DV-004", "DV-015", "DV-034"),
    "R-015": ("DV-024", "DV-029", "DV-040", "DV-045"),
    "R-016": ("DV-023", "DV-024", "DV-029", "DV-037", "DV-038", "DV-039"),
    "R-017": ("DV-025", "DV-036", "DV-040", "DV-045", "DV-046"),
    "R-018": ("DV-026", "DV-047"),
    "R-019": ("DV-020", "DV-021", "DV-029", "DV-032", "DV-042"),
    "R-020": ("DV-002", "DV-005", "DV-013", "DV-015", "DV-022", "DV-027", "DV-033", "DV-035", "DV-043"),
    "R-021": ("DV-022", "DV-027"),
    "R-022": ("DV-030", "DV-031"),
    "R-023": ("DV-018", "DV-029", "DV-031"),
    "R-024": ("DV-005", "DV-034"),
    "R-025": ("DV-011", "DV-024", "DV-028", "DV-033"),
    "R-026": ("DV-023", "DV-027", "DV-035"),
    "R-027": ("DV-025", "DV-036", "DV-046"),
    "R-028": ("DV-024", "DV-037", "DV-038"),
    "R-029": ("DV-021", "DV-023", "DV-038"),
    "R-030": ("DV-010", "DV-039"),
    "R-031": ("DV-024", "DV-048"),
    "R-032": ("DV-024", "DV-025", "DV-029", "DV-040"),
    "R-033": ("DV-013", "DV-024", "DV-028", "DV-041", "DV-043"),
    "R-034": ("DV-044", "DV-045"),
    "R-035": ("DV-024", "DV-045"),
    "R-036": ("DV-036", "DV-044", "DV-046"),
    "R-037": ("DV-025", "DV-047"),
    "R-038": ("DV-003",),
    "R-039": ("DV-001", "DV-030"),
    "R-040": ("DV-049",),
}


def _invert_links(links: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
    inverted: dict[str, set[str]] = defaultdict(set)
    for source_id, target_ids in links.items():
        for target_id in target_ids:
            inverted[target_id].add(source_id)
    return {key: tuple(sorted(values)) for key, values in inverted.items()}


def _join_ids(ids: tuple[str, ...] | list[str] | set[str]) -> str:
    return ";".join(sorted(set(ids)))


def _control_id(risk_id: str) -> str:
    return f"CTRL-{risk_id.removeprefix('R-')}"


RISK_REQUIREMENT_LINKS = _invert_links(REQUIREMENT_RISK_LINKS)
TEST_REQUIREMENT_LINKS = _invert_links(REQUIREMENT_TEST_LINKS)
TEST_RISK_LINKS = _invert_links(RISK_TEST_LINKS)


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    if not rows:
        return
    fields = fields or list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _canonical_name(name: str) -> str:
    canonical = re.sub(
        r"_(folded|stowed|follow|cafe|focus|deployed|seat|internal|transfer|desk|obstacle)(?=_|$)",
        "",
        name,
    )
    return re.sub(r"__+", "_", canonical).rstrip("_")


def write_production_bom(configs: dict, target: Path) -> dict:
    per_config: dict[str, Counter] = {}
    base_per_config: dict[str, Counter] = {}
    representatives = {}
    usage: dict[str, set[str]] = defaultdict(set)
    geometry_names: dict[str, set[str]] = defaultdict(set)
    conflicts: dict[str, set[tuple]] = defaultdict(set)
    option_usage: dict[str, set[str]] = defaultdict(set)
    identity_basis_counts: Counter = Counter()
    for config, parts in configs.items():
        counts = Counter()
        base_counts = Counter()
        for candidate in parts:
            if (
                candidate.maturity == "validation-envelope"
                or candidate.name.startswith("desk_bundle_stowed_")
                or not getattr(candidate, "include_in_ebom", True)
            ):
                continue
            occurrence_id = getattr(candidate, "physical_occurrence_id", "") or _canonical_name(candidate.name)
            option_code = getattr(candidate, "option_code", "BASE") or "BASE"
            identity_basis = getattr(candidate, "identity_basis", "LEGACY_NAME") or "LEGACY_NAME"
            counts[occurrence_id] += candidate.quantity
            if option_code == "BASE":
                base_counts[occurrence_id] += candidate.quantity
            representatives.setdefault(occurrence_id, candidate)
            usage[occurrence_id].add(config)
            geometry_names[occurrence_id].add(candidate.name)
            option_usage[option_code].add(occurrence_id)
            identity_basis_counts[identity_basis] += candidate.quantity
            conflicts[occurrence_id].add(
                (
                    candidate.material,
                    candidate.process,
                    candidate.vendor,
                    candidate.vendor_part_number,
                    candidate.maturity,
                    round(candidate.mass_kg, 6),
                    round(float(candidate.solid.Volume()), 3),
                    candidate.quantity,
                    candidate.source_url,
                    option_code,
                    getattr(candidate, "definition_revision", "UNCONTROLLED"),
                )
            )
        per_config[config] = counts
        base_per_config[config] = base_counts

    rows = []
    maturity = Counter()
    for index, occurrence_id in enumerate(sorted(representatives), 1):
        candidate = representatives[occurrence_id]
        bb = candidate.solid.BoundingBox()
        qty = max(counts.get(occurrence_id, 0) for counts in per_config.values())
        maturity[candidate.maturity] += 1
        rows.append(
            {
                "item_id": f"WC-E6-MFG-{index:03d}",
                "physical_occurrence_id": occurrence_id,
                "canonical_description": _canonical_name(candidate.name),
                "geometry_names": ";".join(sorted(geometry_names[occurrence_id])),
                "qty_per_unit": qty,
                "material": candidate.material,
                "process": candidate.process,
                "estimated_mass_each_kg": f"{candidate.mass_kg:.4f}",
                "estimated_mass_total_kg": f"{candidate.mass_kg * qty:.4f}",
                "envelope_x_mm": f"{bb.xlen:.3f}",
                "envelope_y_mm": f"{bb.ylen:.3f}",
                "envelope_z_mm": f"{bb.zlen:.3f}",
                "vendor": candidate.vendor,
                "vendor_part_number": candidate.vendor_part_number,
                "maturity": candidate.maturity,
                "source_url": candidate.source_url,
                "option_code": getattr(candidate, "option_code", "BASE"),
                "definition_revision": getattr(candidate, "definition_revision", "UNCONTROLLED"),
                "identity_basis": getattr(candidate, "identity_basis", "LEGACY_NAME"),
                "used_in_configurations": ";".join(sorted(usage[occurrence_id])),
                "definition_conflict": "YES" if len(conflicts[occurrence_id]) > 1 else "NO",
            }
        )
    _write_csv(target, rows)
    candidate_union_rollup_by_configuration = {
        config: round(
            sum(representatives[name].mass_kg * qty for name, qty in counts.items()),
            4,
        )
        for config, counts in per_config.items()
    }
    configured_cad_mass_estimates = {
        config: round(sum(candidate.mass_kg * candidate.quantity for candidate in parts), 4)
        for config, parts in configs.items()
    }
    base_pose_names = ("stowed", "follow", "obstacle", "seat", "cafe", "transfer", "desk")
    base_pose_masses = [
        configured_cad_mass_estimates[name]
        for name in base_pose_names
        if name in configured_cad_mass_estimates
    ]
    union_catalog_mass = round(
        sum(float(row["estimated_mass_total_kg"]) for row in rows), 4
    )
    base_pose_mass_spread = round(max(base_pose_masses) - min(base_pose_masses), 4) if base_pose_masses else 0.0
    reference_name = "stowed" if "stowed" in base_per_config else next(iter(base_per_config), None)
    reference_counts = base_per_config.get(reference_name, Counter())
    pose_deltas = {}
    for config in base_pose_names:
        if config not in base_per_config or config == reference_name:
            continue
        current = base_per_config[config]
        pose_deltas[config] = {
            "missing_occurrences": sorted((reference_counts - current).elements()),
            "added_occurrences": sorted((current - reference_counts).elements()),
            "quantity_mismatch_ids": sorted(
                occurrence_id
                for occurrence_id in set(reference_counts) | set(current)
                if occurrence_id in reference_counts
                and occurrence_id in current
                and reference_counts[occurrence_id] != current[occurrence_id]
            ),
        }
    pose_sets_invariant = all(
        not delta["missing_occurrences"]
        and not delta["added_occurrences"]
        and not delta["quantity_mismatch_ids"]
        for delta in pose_deltas.values()
    )
    identity_total = sum(identity_basis_counts.values())
    controlled_identity_count = identity_basis_counts.get("CONTROLLED_ID", 0)
    controlled_identity_percent = round(100.0 * controlled_identity_count / identity_total, 1) if identity_total else 0.0
    definition_conflict_count = sum(row["definition_conflict"] == "YES" for row in rows)
    pose_identity_demonstrated = (
        identity_total > 0
        and controlled_identity_count == identity_total
        and pose_sets_invariant
        and base_pose_mass_spread <= 0.001
        and definition_conflict_count == 0
    )
    return {
        "role": "candidate_configuration_union",
        "scope_note": "This is a configuration-aware candidate occurrence catalogue. Controlled occurrence IDs are required evidence, but this remains unreleased until pose-set identity, option effectivity, mass reconciliation and first-article measurement all close.",
        "rows": len(rows),
        "maturity_counts": dict(maturity),
        "definition_conflicts": definition_conflict_count,
        "supplier_named_rows": sum(bool(row["vendor"]) for row in rows),
        "part_number_defined_rows": sum(bool(row["vendor_part_number"]) for row in rows),
        "source_url_rows": sum(bool(row["source_url"]) for row in rows),
        "identity_basis_counts": dict(identity_basis_counts),
        "controlled_occurrence_identity_percent": controlled_identity_percent,
        "option_effectivity_occurrence_counts": {
            code: len(ids) for code, ids in sorted(option_usage.items())
        },
        "configuration_mass_estimates_kg": configured_cad_mass_estimates,
        "candidate_union_rollup_by_configuration_kg": candidate_union_rollup_by_configuration,
        "union_catalog_mass_kg": union_catalog_mass,
        "base_pose_scope": list(base_pose_names),
        "base_pose_reference": reference_name,
        "base_pose_occurrence_deltas": pose_deltas,
        "base_pose_occurrence_sets_invariant": pose_sets_invariant,
        "configuration_mass_spread_kg": base_pose_mass_spread,
        "pose_identity_status": "DEMONSTRATED" if pose_identity_demonstrated else "NOT_DEMONSTRATED",
        "pose_identity_warning": "Do not use these roll-ups for released unit cost, purchasing, mass properties or stability sign-off until every EBOM occurrence has a controlled identity, BASE occurrence counts are pose-invariant, option deltas are explicit, CAD mass spread is <=0.001 kg, and first articles are reconciled.",
    }


def requirements() -> list[dict]:
    data = [
        ("REQ-USE-001", "intended_use", "目标用户、家—社区—咖啡馆使用环境、禁忌和可预见误用必须形成受控预期用途", "P0", "产品定义", "文档审查+人在环", "docs/e6_product_definition_and_strategy.md", "partial"),
        ("REQ-REG-001", "regulatory", "冻结中国首发产品分类、注册路径、责任主体和目标市场", "P0", "法规策略", "法规机构书面确认", "未完成", "open"),
        ("REQ-HF-001", "human_factors", "覆盖东亚5F～95M、冬装及低握力/轻度活动受限用户；不作老人照护声明", "P0", "GB/T 10000-2023", "人体样本+模拟使用验证", "CAD保守包络，尚无人在环数据", "partial"),
        ("REQ-HF-002", "seating", "连续2小时坐姿不得产生不可接受压力、热湿和麻木风险", "P0", "ISO 16840系列", "压力映射+热湿+主观量表", "未完成", "open"),
        ("REQ-HMI-001", "controls", "右扶手摇杆/授权键与独立急停在桌板展开时不得被遮挡", "P0", "ISO 7176-14域", "几何+操作力+误触试验", "固定右侧HMI接口包络和桌板净距已建", "partial"),
        ("REQ-HMI-002", "controls", "左扶手保留小屏与15W Qi2区域，并具备FOD、温度和手机在位盖板互锁", "P1", "v37功能基线/Qi2", "几何+温升+异物+湿污+互锁", "显示、线圈、FOD/温度模块实体已建", "partial"),
        ("REQ-SAF-001", "motion_safety", "Follow/Ride/Café/Focus四态中，任何占用、桌板、脚踏、桅杆或锁位未知均撤销相应运动许可", "P0", "风险控制", "故障注入", "docs/safety_state_machine.md", "partial"),
        ("REQ-FOL-001", "restricted_follow", "原v37基座传感带必须在整机折叠后持续无遮挡工作", "P0", "v37功能基线", "几何+遮挡+污损+标定验证", "20个基座传感/天线包络已恢复并自动检查", "partial"),
        ("REQ-FOL-002", "restricted_follow", "随行仅限空载折叠、白名单私域路线、主人可见；最高0.8m/s，身份或感知失信即停车", "P0", "E6使用边界", "场景故障注入+制动距离+人在环", "参数与状态边界已定义，实车未验证", "partial"),
        ("REQ-FOL-003", "motion_safety", "AI计算域不得直接授权驱动；独立安全控制器负责目标丢失、STO和机械制动许可", "P0", "安全架构", "架构审查+故障注入+时序测量", "独立控制器接口包络已定义，硬件未实现", "partial"),
        ("REQ-FOL-004", "restricted_follow", "座椅占用信号不一致、未知、失效或无法完成自检时必须按有人处理并禁止Follow；不得以无人边界继续运动", "P0", "安全架构/风险R-031", "占用故障注入+硬件许可验证", "规则已加入追踪，硬件与实车验证未完成", "open"),
        ("REQ-CAF-001", "social_use", "咖啡驻停态必须驻车断驱动、桅杆低位，并允许单侧桌面展开且另一侧开放", "P1", "E6产品定义", "几何+场景人在环", "cafe构型和单侧桌面已建", "partial"),
        ("REQ-CAF-002", "work_surface", "标准版Café须先收纳右摇杆、桌板前移清空后绕质心旋转90度并回移正锁，形成430×270mm横向单桌；运动机构舱不得兼作用户仓", "P0", "E6R2机构定义", "扫掠+锁止+偏载+人在环", "横向终态、转盘/滑轨/锁销包络与自动扫掠已建，实体试验未完成", "partial"),
        ("REQ-SAF-002", "egress", "断电时乘员可在10秒目标内机械逃生", "P0", "风险控制", "5F～95M无电演练", "机械释放架构，尚未实测", "partial"),
        ("REQ-MOB-001", "mobility", "满载最高速度、加减速、制动和驻坡满足冻结边界", "P0", "GB/T 18029.2/.3/.6", "型式域物理测试", "计算报告通过，尚未实测", "partial"),
        ("REQ-MOB-002", "mobility", "额定50 mm越障不得以60 mm条件上限替代", "P0", "GB/T 18029.10域", "满载1000次+斜向/湿滑", "计算与几何通过，尚未实测", "partial"),
        ("REQ-MOB-003", "mobility", "后置双管越障拉杆仅允许在无人、靠背/桅杆/脚踏收纳且制动互锁状态伸出", "P0", "v37功能基线/风险控制", "互锁故障注入+操作力+疲劳+误用", "1350 mm操作高度和8度助攀构型已建", "partial"),
        ("REQ-STR-001", "structure", "150 kg乘员+25 kg载荷下满足静载、冲击和疲劳", "P0", "GB/T 18029.8-2024", "实验室静载/冲击/疲劳", "解析计算，尚无结构试验", "partial"),
        ("REQ-STB-001", "stability", "所有占用/桌板/顶棚/坡面工况满足稳定性要求", "P0", "GB/T 18029.1/.2", "标准测试平台", "解析计算，尚无标准测试", "partial"),
        ("REQ-PWR-001", "battery", "16S LFP满足120 A连续、200 A短时并受控泄压", "P0", "GB/T 18029.25/ISO 7176-31/UN 38.3", "电池鉴定+传播+运输", "电气包络完成，供应商未定", "partial"),
        ("REQ-EMC-001", "emc", "零转、无线通信、摄像和音频同时工作时无危险干扰", "P0", "GB/T 18029.21/ISO 7176-21:2025", "EMC实验室", "未完成", "open"),
        ("REQ-ENV-001", "environment", "雨淋、灰尘、冷凝、冷热循环后保持安全功能", "P0", "GB/T 18029.9域", "环境箱+淋雨+故障注入", "热架构完成，实测未完成", "partial"),
        ("REQ-CYB-001", "cybersecurity", "远程、无线和OTA不得获得未经授权的运动权限", "P0", "风险管理", "威胁建模+渗透+签名验证", "未完成", "open"),
        ("REQ-PRI-001", "privacy", "相机/麦克风提供物理可见状态、硬件静音和数据生命周期控制", "P1", "隐私设计", "UI/硬件/数据审计", "设备包络已建，隐私控制未建", "open"),
        ("REQ-CTX-001", "context_continuity", "任务快照必须绑定授权用户、物理构型、隐私状态和设备状态；恢复完成时间P95≤10秒，且恢复动作不得改变运动安全许可", "P0", "E5/E6 Context Continuity", "真实任务循环+时序+安全域审计", "参考策略与单元测试已建立；OS适配、时序和实测未完成", "partial"),
        ("REQ-CTX-002", "context_continuity", "离线、断网、云服务中断和主计算重启时，本地身份、构型、隐私与任务快照保持可恢复；任何状态不确定均不得授予运动或机构动作", "P0", "E5/E6 Context Continuity", "网络中断+掉电/重启+故障注入", "离线/未知状态参考策略已单测；持久化与实机故障注入未完成", "partial"),
        ("REQ-CTX-003", "context_continuity", "用户身份不一致、会话过期、设备转交或重放攻击时不得恢复其他用户上下文、暴露数据或执行自动动作", "P0", "E5/E6 Context Continuity", "多用户隔离+重放/转交+权限验证", "错误用户和过期状态参考策略已单测；身份实现与攻防验证未完成", "partial"),
        ("REQ-CTX-004", "privacy", "用户数据必须可导出和可验证删除；维修、转售、报废或密钥轮换时完成密钥退役并使残留密文不可恢复", "P1", "E5数据生命周期", "导出/删除审计+介质与密钥退役演练", "需求已建立，生命周期实现未完成", "open"),
        ("REQ-ID-001", "industrial_design", "所有可触表面无锐边、夹点、烫伤和不可清洁死角", "P0", "工业设计安全", "探棒+边缘+清洁验证", "护罩包络部分完成", "partial"),
        ("REQ-CMF-001", "cmf", "材料、纹理、光泽、色差、耐汗液/清洁剂/UV和阻燃冻结", "P1", "CMF规范", "材料试片+黄金样", "材料类别有，最终规范未完成", "partial"),
        ("REQ-DFM-001", "manufacturing", "所有承力件具备2D工程图、GD&T、材料/热处理和检验方法", "P0", "设计转移", "图纸审查+首件检验", "仅STEP与少量公差表", "open"),
        ("REQ-BOM-001", "supply", "生产BOM需有制造商料号、版本、寿命、替代策略和成本", "P0", "供应链", "BOM审核", "仅生成候选构型并集目录；姿态身份和大量料号未定", "partial"),
        ("REQ-CFG-001", "configuration", "基础SKU各姿态必须具有完全相同的物理件ID/数量并保持质量差≤0.001kg；选装件必须以独立effectivity和质量增量管理", "P0", "配置管理/质量属性", "物理件ID集合差异+质量对账+首件称重", "当前生成报告仍显示姿态物理件集合和质量不一致；以production_readiness_report.json实时值为准", "open"),
        ("REQ-SVC-001", "service", "易损件可安全更换，定义工时、工具、备件和维修后测试", "P1", "服务设计", "维修演练", "模块化原则有，服务手册未完成", "partial"),
        ("REQ-MFG-001", "quality", "生产线具备关键特性控制、EOL安全测试和序列号追溯", "P0", "质量计划", "PVT/过程能力/EOL MSA", "未完成", "open"),
        ("REQ-LBL-001", "labeling", "载荷、坡度、越障、充电、转运、隐私和禁用场景明确标识", "P0", "GB/T 18029.15域", "标签耐久+理解性", "未完成", "open"),
    ]
    keys = ("requirement_id", "domain", "requirement", "priority", "source", "verification", "current_evidence", "status")
    rows = [dict(zip(keys, row)) for row in data]
    for row in rows:
        risk_ids = REQUIREMENT_RISK_LINKS.get(row["requirement_id"], ())
        row["linked_risk_ids"] = _join_ids(risk_ids)
        row["linked_control_ids"] = _join_ids({_control_id(risk_id) for risk_id in risk_ids})
        row["linked_test_ids"] = _join_ids(REQUIREMENT_TEST_LINKS.get(row["requirement_id"], ()))
        row["owner"] = "TBD"
        row["revision"] = "E6-DFR3"
        row["approval"] = "NOT_APPROVED"
    return rows


def risks() -> list[dict]:
    data = [
        ("R-001", "非预期驱动/加速", "乘员或旁人被撞、跌落", 5, 3, "独立驱动许可链、急停、断电制动", "故障注入+单点故障", "open"),
        ("R-002", "制动失效或溜坡", "碰撞、夹压、跌落", 5, 3, "四轮弹簧制动、驻坡监控", "冷/热/湿/单路失效", "open"),
        ("R-003", "侧翻/前翻", "严重伤害", 5, 3, "速度坡度限制、低重心、稳定性控制", "GB/T 18029.1/.2域", "open"),
        ("R-004", "摇臂、轮毂或轴失效", "突然失稳", 5, 2, "解析强度、机械限位", "静载/冲击/疲劳", "open"),
        ("R-005", "脚踏解锁或足部卷入", "足部损伤、跌落", 4, 3, "双锁位、护罩、驱动许可", "探棒/污染/冲击", "open"),
        ("R-006", "桌板扫过乘员", "躯干/手臂夹伤", 4, 3, "先前移后展开、机械顺序槽", "假人扫掠+磨损", "partial"),
        ("R-007", "移乘扶手未锁而驱动", "侧向跌落", 5, 3, "双锁位+断接触器", "锁舌磨损/断线", "open"),
        ("R-008", "顶棚风载失稳或坍塌", "头部伤害、整机倾覆", 5, 3, "双风传感、7m/s回收、机械锁", "风洞/阵风/卡滞", "open"),
        ("R-009", "桅杆坠落", "头颈部伤害", 5, 2, "防坠、双锁销、张力诊断", "断绳/冲击", "open"),
        ("R-010", "电池热失控", "火灾、毒烟、烧伤", 5, 2, "隔离盒、后向泄压、双温度", "传播/过充/浸水/碰撞", "open"),
        ("R-011", "充电故障或接触器粘连", "触电、火灾、非预期上电", 5, 2, "外置充电、预充、双接触器", "异常充电/粘连", "open"),
        ("R-012", "进水/冷凝导致短路", "失控、火灾、失效", 5, 3, "分区、排水、露点控制", "雨淋/温循/盐雾", "open"),
        ("R-013", "抽屉行驶中打开或碰轮", "失控、物品抛出", 4, 3, "正锁、扫掠净距", "冲击台/偏载/结冰", "partial"),
        ("R-014", "约束带误用/无法释放", "抛出或逃生受阻", 5, 2, "骨盆带、单手机械释放", "误扣/冲击/10秒逃生", "open"),
        ("R-015", "控制器重启/状态丢失", "危险动作", 5, 3, "绝对位置输入、FAULT_SAFE", "掉电时序/通信故障", "open"),
        ("R-016", "EMC或传感共因失效", "制动/运动判断错误", 5, 3, "分区线束、独立安全线", "ISO 7176-21:2025域", "open"),
        ("R-017", "远程入侵或未授权控制", "非预期运动/隐私泄露", 5, 2, "运动域与联网域隔离（要求）", "威胁建模/渗透", "open"),
        ("R-018", "摄像/麦克风无感采集", "隐私伤害", 3, 4, "物理指示/静音（待实现）", "隐私用例审查", "open"),
        ("R-019", "设备仓过热", "烫伤、设备或电池起火", 5, 3, "100W闭仓降额、风扇/NTC", "40C堵转/单风扇故障", "open"),
        ("R-020", "锐边、夹点、外露运动件", "割伤/夹伤", 4, 3, "圆角、护罩、运动净距", "探棒/极限公差", "open"),
        ("R-021", "软包或塑料燃烧/有害物", "烧伤、烟气、皮肤反应", 5, 2, "材料选择原则", "阻燃/接触材料评价", "open"),
        ("R-022", "人工搬运整机", "腰背/挤压伤", 4, 4, "禁止徒手搬运、机械装载", "实车装载演练", "partial"),
        ("R-023", "维修时带电或误释制动", "触电、夹压、溜车", 5, 3, "可锁维修断电、双动作释制动", "LOTO维修演练", "open"),
        ("R-024", "急停被桌板/衣物遮挡或误触", "不能及时停车/突然停车", 5, 3, "独立前置急停与防护圈", "5F～95M操作力/误触", "open"),
        ("R-025", "越障拉杆未锁、回缩或在载人状态误伸出", "夹伤、跌落或整机失稳", 5, 3, "双正锁、无人互锁、折叠顺序和制动许可", "锁止疲劳/误用/单点故障/坡面操作", "open"),
        ("R-026", "无线充电异物、湿污或温控失效", "烫伤、起火或扶手表面损坏", 4, 3, "FOD、线圈温度、手机在位和独立断电", "全CMF组合温升/异物/液体污染", "open"),
        ("R-027", "随行绑定错误目标或身份被中继", "跟错人、碰撞或资产丢失", 5, 3, "配对UWB密钥+视觉一致性+本地授权", "多人交叉/遮挡/重放/中继攻击", "open"),
        ("R-028", "随行目标或视觉置信度丢失后继续运动", "碰撞行人或障碍", 5, 3, "独立超时、速度上限、机械制动", "0.8m/s全链路延迟/制动距离/坡面", "open"),
        ("R-029", "日照、雨雾或污损导致低位光学感知失效", "漏检或误停车", 5, 3, "质量诊断、多模态合理性、失信即停", "逆光/雨雾/泥点/镜面和黑色地面", "open"),
        ("R-030", "悬崖检测或触觉防撞膜共因失效", "跌落台阶或撞人", 5, 2, "四路向下感知、双通道触边、周期自检", "边缘材料/污染/机械冲击/断线", "open"),
        ("R-031", "乘员或重物在座却进入Follow", "跌落或失稳", 5, 2, "双区占用+重量趋势+构型互锁", "儿童/宠物/软包/局部载荷误判", "open"),
        ("R-032", "AI计算域越过独立运动许可", "非预期运动", 5, 2, "独立安全MCU、白名单意图、双通道STO/制动", "总线注入/重启/看门狗/时序竞争", "open"),
        ("R-033", "Café横向桌未清空即旋转、转盘/滑轨未正锁或偏载失效", "夹伤、物品甩落、桌面坠落或整机倾覆", 5, 3, "驻车断驱动、空桌顺序槽、0/90度止挡、双剪锁销、80mm滑轨正锁", "扫掠探棒+380Nm证明载荷+偏载/倚靠/疲劳/故障注入", "open"),
        ("R-034", "任务快照损坏、不完整或恢复超时", "工作丢失、错误恢复或用户在未确认状态下继续操作", 4, 3, "事务化快照、版本校验、超时回退、物理构型与隐私状态绑定（待实现）", "30次以上真实任务循环、掉电点注入和P95恢复时序", "open"),
        ("R-035", "断网、云服务中断或主计算重启导致本地核心状态失效", "任务中断、状态误判或安全域收到不完整意图", 5, 2, "本地最小功能、持久化安全边界、启动默认拒绝许可（待实现）", "断网/弱网/云停服/掉电重启与安全许可故障注入", "open"),
        ("R-036", "错误用户、过期会话或重放身份恢复他人上下文", "隐私泄露、错误自动动作或资产访问", 4, 3, "本地强身份、上下文绑定、会话新鲜度和动作再授权（待实现）", "多人交叉、设备转交、重放和权限降级测试", "open"),
        ("R-037", "导出/删除不完整或维修退役时密钥仍有效", "个人数据长期残留、转售/报废后泄露", 4, 2, "可审计导出删除、密钥轮换/吊销和介质退役流程（待实现）", "数据生命周期审计、密钥退役和残留恢复尝试", "open"),
        ("R-038", "连续坐姿压力、剪切或热湿超限", "麻木、疼痛、皮肤或组织损伤", 4, 3, "座垫分区、压力/热湿设计和使用时长限制（待验证）", "2小时压力映射、热湿和目标用户主观量表", "open"),
        ("R-039", "预期用途、法规分类、ODD或对外声明与实际能力不一致", "用户进入未验证场景并受伤、监管不合规或无法召回处置", 5, 3, "受控预期用途、禁忌、ODD、声明和条款级标准矩阵（待批准）", "法规书面结论、声明审查和真实运输/使用场景核验", "open"),
        ("R-040", "姿态或选装改变基础SKU物理件身份/质量", "稳定性、制动、续航、物流、成本和采购使用错误质量或漏件", 5, 4, "稳定物理件ID、版本、数量和选装effectivity；姿态仅改变变换", "构型集合差异、EBOM对账、各姿态质量恒定与首件称重", "open"),
    ]
    keys = ("risk_id", "hazard", "harm", "severity_1_5", "probability_1_5", "current_controls", "required_verification", "status")
    rows = [dict(zip(keys, row)) for row in data]
    for row in rows:
        row["control_id"] = _control_id(row["risk_id"])
        row["linked_requirement_ids"] = _join_ids(RISK_REQUIREMENT_LINKS.get(row["risk_id"], ()))
        row["linked_test_ids"] = _join_ids(RISK_TEST_LINKS.get(row["risk_id"], ()))
        row["initial_risk_index"] = row["severity_1_5"] * row["probability_1_5"]
        row["residual_acceptance"] = "由正式风险管理计划和法规分类冻结；不可仅凭计算关闭"
        row["owner"] = "TBD"
        row["revision"] = "E6-DFR3"
        row["approval"] = "NOT_APPROVED"
        row["residual_risk_status"] = "NOT_EVALUATED"
    return rows


def dvpr() -> list[dict]:
    data = [
        ("DV-001", "法规", "产品分类和标准适用性评审", "法规机构/NMPA路径", "G0", "1份书面结论", "范围、声明、市场和责任主体冻结"),
        ("DV-002", "人体", "5F～95M及老年人静态适配", "GB/T 10000-2023/IEC 62366-1原则", "EVT", "≥30人，老年/低活动度单列", "进出、桌板、急停、视野和触达满足预设标准"),
        ("DV-003", "人体", "2小时坐姿压力/热湿/主观舒适", "ISO 16840系列域", "DVT", "≥20人+压力垫", "无不可接受峰值、麻木、剪切和热不适"),
        ("DV-004", "逃生", "断电无电机械离开", "风险控制", "EVT", "5F/95M/老年各≥5次", "目标10秒；无工具；单手释放"),
        ("DV-005", "控制", "操纵力、急停力和误触", "ISO 7176-14域", "EVT", "3台×左右手", "力值和可达性按最终标准/风险文件冻结"),
        ("DV-006", "稳定性", "静态稳定", "GB/T 18029.1-2024", "DVT", "3台", "全部构型、载荷和坡向满足适用条款"),
        ("DV-007", "稳定性", "动态稳定", "GB/T 18029.2-2022", "DVT", "3台", "起步、制动、坡折和转向无不可接受失稳"),
        ("DV-008", "制动", "制动效率/停车距离/驻坡", "GB/T 18029.3域", "DVT", "3台", "冷热湿及单路故障满足冻结边界"),
        ("DV-009", "速度", "最高速度、加减速度", "GB/T 18029.6-2024", "DVT", "3台", "Ride与受限Follow构型均满足冻结速度、加速度和减速度边界"),
        ("DV-010", "越障", "50mm额定越障", "GB/T 18029.10域", "EVT/DVT", "3台×1000次", "满载正向通过；斜向/湿滑安全停止"),
        ("DV-011", "结构", "静载、冲击和疲劳", "GB/T 18029.8-2024", "DVT", "3台+破坏样", "无危险失效；关键尺寸保持"),
        ("DV-012", "轮系", "摇臂和轮端耐久", "载荷谱+GB/T 18029.32域", "DVT", "3套", "无裂纹、松脱、线束磨损和危险间隙变化"),
        ("DV-013", "桌板", "扫掠/锁止/偏载/疲劳", "内部规范", "EVT", "左右各20000次", "不侵入人体包络；锁止和盖板持续有效"),
        ("DV-014", "抽屉", "冲击、偏载、泥沙结冰和轮系动态间隙", "内部规范", "EVT", "3台", "不自开、不碰轮、锁扣可操作"),
        ("DV-015", "移乘", "扶手锁止/无电释放/疲劳", "IEC 62366-1原则", "EVT", "3台+人在环", "无跌落/夹伤；锁位诊断有效"),
        ("DV-016", "顶棚", "风载、阵风、回收、卡滞和防坠", "风险规范", "EVT/DVT", "3台", "7m/s触发；故障安全；无头部危险"),
        ("DV-017", "电池", "电池/BMS/过流/传播/泄压", "ISO 7176-31/适用电池标准", "DVT", "供应商鉴定+整包", "120A连续/200A短时；火焰烟气不进入乘员区"),
        ("DV-018", "充电", "正常/异常充电和接触器故障", "GB/T 18029.25域", "DVT", "3台", "无危险温升、触电或非预期驱动"),
        ("DV-019", "运输", "锂电运输鉴定和试验概要", "UN Manual 38.3", "DVT", "电池型号", "有效UN38.3报告及试验概要可追溯"),
        ("DV-020", "热", "40C满载热平衡", "内部热规范", "EVT", "3台", "电池/电子/仓内设备不越限；单风扇故障降额"),
        ("DV-021", "环境", "冷热循环、雨淋、冷凝、尘土", "GB/T 18029.9域", "DVT", "3台", "无危险功能、腐蚀或积水"),
        ("DV-022", "腐蚀", "盐雾/汗液/清洁剂/紫外", "材料规范", "DVT", "材料片+整机", "外观和安全功能满足黄金样/限度样"),
        ("DV-023", "EMC", "发射、抗扰、ESD、射频共存", "ISO 7176-21:2025/GB/T 18029.21", "DVT", "3台+充电器", "无危险运动；影像音频和通信可接受"),
        ("DV-024", "软件", "重启、看门狗、通信超时和传感故障注入", "安全需求", "EVT/DVT", "每版本自动回归", "所有单点故障进入定义安全状态"),
        ("DV-025", "网络", "安全启动、签名升级、权限和渗透", "威胁模型", "DVT", "发布固件", "联网域无法直接授权运动；日志可追溯"),
        ("DV-026", "隐私", "摄像/麦克风物理指示与硬件静音", "隐私需求", "EVT", "3台+人在环", "状态无歧义；断网/重启后保持用户选择"),
        ("DV-027", "CMF", "色差、光泽、纹理、刮擦和清洁", "CMF限度样", "DVT", "每供应商3批", "满足黄金样和限度样"),
        ("DV-028", "装配", "尺寸链、间隙齐平、扭矩和防错", "工程图/控制计划", "PVT", "≥30台", "关键特性Cpk目标由质量计划冻结；无返工装配"),
        ("DV-029", "生产", "EOL制动/急停/互锁/绝缘/充电/通信测试", "EOL规范", "PVT", "100%", "每台全通过并绑定序列号"),
        ("DV-030", "物流", "包装振动、跌落、堆码和实车装载", "运输规范", "DVT/PVT", "3套包装", "无功能/外观损伤；不可人工抬举风险受控"),
        ("DV-031", "服务", "电池、轮端、控制器、风扇和抽屉维修演练", "服务规范", "PVT", "3名技术员", "达到工时目标；维修后安全测试完整"),
        ("DV-032", "可靠性", "整车任务谱寿命与HALT问题发现", "可靠性计划", "DVT", "≥6台", "达到冻结寿命/可靠性目标且高风险失效为0"),
        ("DV-033", "越障拉杆", "伸缩、双锁、操作力、助攀和误用", "内部风险规范", "EVT/DVT", "3台×20000次", "仅在无人收纳态可伸出；1350mm操作高度；无回缩、弯曲、夹伤或失稳"),
        ("DV-034", "扶手HMI", "右摇杆/授权键与左屏可达性、辨识和误触", "IEC 62366-1原则", "EVT", "5F～95M及低握力用户", "桌板各状态可达且不遮挡；操作无歧义"),
        ("DV-035", "无线充电", "Qi2输出、FOD、温升、湿污与盖板互锁", "Qi2/内部热规范", "EVT/DVT", "全部CMF组合×3台", "15W目标下不越温；异物/湿污安全停机；手机在位拒绝开盖"),
        ("DV-036", "随行身份", "UWB主人绑定、多人交叉、遮挡、重放与中继攻击", "E6受限随行规范", "EVT/DVT", "3台×白名单场景", "只跟随授权主人；身份或方向不一致立即停车并记录"),
        ("DV-037", "随行停车", "0.8m/s目标/视觉丢失、通信超时与全链路制动距离", "E6安全需求", "EVT/DVT", "干湿平地/坡面×3台", "≤0.5s撤销许可；实测保护距离覆盖感知、控制、STO、机械制动和坡度"),
        ("DV-038", "低位感知", "v37基座感知遮挡、污损、逆光、雨雾、黑色/镜面地面", "内部感知规范", "EVT/DVT", "全部窗材与污染等级", "任一关键可信度不足进入安全停车；无盲区宣传"),
        ("DV-039", "悬崖/触边", "四路下视与双通道触觉膜故障注入", "内部安全规范", "EVT/DVT", "3台×边缘/断线/冲击", "单点故障不继续Follow；50mm障碍不先撞传感器"),
        ("DV-040", "AI隔离", "Jetson重启、总线注入、越权轨迹和安全MCU看门狗", "安全架构", "EVT/DVT", "每版本自动回归", "AI无法直接复位STO、释放制动或授予扭矩"),
        ("DV-041", "咖啡驻停", "单侧桌面、开放侧、脚踏靠桌与社交可用性", "IEC 62366-1原则", "EVT", "5F～95M×真实咖啡桌", "驻车断驱动；不围困用户；足部安全且可合理接近桌边"),
        ("DV-042", "仓位任务", "主电脑仓、通用扁平仓和4.9L日用仓的30天任务验证", "E6用户需求", "EVT", "≥20名目标用户", "双机兼容但日用物不被迫外置；舱门闭合、温升和取用满足目标"),
        ("DV-043", "Café横向桌", "前移—质心旋转90度—回移80mm全链、锁止、夹点、外缘偏载与倚靠", "内部风险/IEC 62366-1原则", "EVT/DVT", "左右镜像各3台×20000次+5F～95M", "扫掠净距满足冻结门槛；0/90度与滑轨双正锁；空桌才能旋转；机构按至少380Nm证明载荷无危险失效"),
        ("DV-044", "上下文连续", "授权用户任务快照、物理构型/隐私绑定与恢复P95时序", "Context Continuity需求", "EVT/DVT", "≥3台×30次真实任务循环×多构型", "完整快照恢复时间P95≤10秒；损坏/过期快照明确拒绝或回退；恢复过程不改变运动安全许可"),
        ("DV-045", "上下文连续", "离线、断网、云停服、掉电和主计算重启恢复", "Context Continuity/安全需求", "EVT/DVT", "每发布版本×网络/掉电矩阵", "本地身份、构型、隐私和最近有效快照可恢复；任一状态未知时运动及机构许可保持撤销"),
        ("DV-046", "上下文隔离", "错误用户、设备转交、会话过期、重放与权限降级", "Context Continuity/隐私需求", "EVT/DVT", "≥20组多用户交叉与攻击用例", "不恢复或暴露其他用户数据，不执行未重新授权动作；拒绝事件可审计"),
        ("DV-047", "数据生命周期", "数据导出、可验证删除、维修/转售/报废密钥退役", "隐私与服务生命周期需求", "DVT/PVT", "每存储介质/账户类型×3台", "导出完整可读；删除后常规与维修接口均不可恢复明文；退役密钥不可再解密历史介质且留有审计记录"),
        ("DV-048", "占用安全", "座椅占用不一致、未知、断线、卡死、儿童/宠物/软包和局部载荷故障注入", "REQ-FOL-004/R-031", "EVT/DVT", "3台×全部占用故障与误用组合", "任一占用信号不一致、未知或自检失败均按有人处理并禁止Follow；不得以无人稳定边界继续运动"),
        ("DV-049", "配置质量", "基础SKU物理件ID/数量、姿态质量、选装effectivity与首件质量对账", "配置管理/EBOM/质量属性", "EVT/DVT", "全部基础姿态×每个选装组合；首件≥3台", "基础姿态物理件ID/数量集合完全相同且计算质量差≤0.001kg；选装增量姿态不变；EBOM、CAD和首件实测差异经批准处置"),
    ]
    keys = ("test_id", "domain", "test", "reference", "stage", "sample_or_cycles", "acceptance")
    rows = [dict(zip(keys, row)) for row in data]
    for row in rows:
        risk_ids = TEST_RISK_LINKS.get(row["test_id"], ())
        row["linked_requirement_ids"] = _join_ids(TEST_REQUIREMENT_LINKS.get(row["test_id"], ()))
        row["linked_risk_ids"] = _join_ids(risk_ids)
        row["linked_control_ids"] = _join_ids({_control_id(risk_id) for risk_id in risk_ids})
        row["status"] = "PLANNED_NOT_EXECUTED"
        row["report_id"] = ""
        row["owner"] = "TBD"
        row["protocol_revision"] = "E6-DFR3"
        row["approval"] = "NOT_APPROVED"
        row["configuration_id"] = "TBD"
        row["result"] = "NOT_EXECUTED"
    return rows


def supplier_release_rows() -> list[dict]:
    data = [
        ("battery cells/pack", "P0", "cell+BMS exact PN; 120A/200A; propagation; UN38.3", "open"),
        ("external charger/dock", "P0", "58.4V profile; isolation; abnormal charge; certification", "open"),
        ("hub motors/controllers", "P0", "torque-speed-efficiency; thermal; encoder; EMC; life", "open"),
        ("power-off brakes", "P0", "30Nm holding; release; wear; manual release", "open"),
        ("joystick/emergency stop", "P0", "operating force; dual channel; diagnostics; ingress", "open"),
        ("armrest status display", "P1", "sunlight readability; viewing angle; glove use; ingress; EMC", "open"),
        ("Qi2 charging/FOD module", "P1", "15W interoperability; FOD; coil temperature; wet contamination; EMC", "open"),
        ("obstacle-assist telescopic handle", "P0", "tube/lock strength; backlash; corrosion; 20000-cycle life; misuse", "open"),
        ("PDU/contactors/fuses", "P0", "fault current; fuse curves; precharge; welded contact detection", "open"),
        ("DC/DC and optional dock AC", "P0", "isolation; derating; EMC; thermal; no onboard mains; dock interlock", "open"),
        ("wheels/tyres/bearings", "P0", "load; rolling radius; runout; pressure; wear; supply life", "open"),
        ("drawer slides/latches", "P1", "mobile-duty derating; slam; corrosion; 20k cycles", "partial"),
        ("mast actuator/reeving", "P0", "configured LA20 PN; speed/load/IP/life; anti-drop", "partial"),
        ("canopy motor/fabric/sensors", "P0", "torque; wind; waterproof; UV; fire; replacement", "open"),
        ("compute/comms/storage", "P1", "PN; lifecycle; security; thermal; software support", "open"),
        ("UWB owner ranging", "P0", "DWM3001C exact PN; antenna clearance; FiRa behavior; security; calibration", "open"),
        ("low-base 3D/ToF perception", "P0", "exact PN; IR window; sunlight/rain/soil; latency; calibration; second source", "open"),
        ("protective-field scanner", "P0", "indoor/outdoor use boundary; field geometry; response; contamination; application safety case", "open"),
        ("cliff sensors and tactile bumper", "P0", "fault coverage; optical materials; mechanical protection; dual-channel diagnostics", "open"),
        ("independent safety MCU/PMIC", "P0", "locked S32K3 PN; safety manual; watchdog; diagnostics; lifecycle", "open"),
        ("dual motor controllers/STO", "P0", "SBLMG2360T or production equivalent; thermal; regen; STO evidence; PCN", "open"),
        ("cameras/microphones/lights", "P1", "PN; privacy shutter; acoustic membrane; ingress; EMC; photobiological review", "open"),
        ("fans/heat exchanger/filters", "P0", "P-Q curve; acoustic; clogging; tach feedback; life", "open"),
        ("connectors/wire/cable chains", "P0", "pinout; derating; CPA; IP; flex life; second source", "open"),
        ("PC-ABS resin/color", "P1", "FR/UV/chemical/impact; texture; lot color control", "open"),
        ("foam/upholstery", "P0", "pressure; ignition; VOC; skin contact; cleanability", "open"),
        ("structural aluminium/steel", "P0", "grade cert; heat treatment; weldability; traceability", "partial"),
        ("fasteners/adhesives/seals", "P0", "grade; torque; locking; shelf life; compatibility", "open"),
    ]
    supplier_item_ids = {
        "battery cells/pack": "SUP-BATTERY-PACK",
        "external charger/dock": "SUP-CHARGER-DOCK",
        "hub motors/controllers": "SUP-TRACTION-DRIVE",
        "power-off brakes": "SUP-POWER-OFF-BRAKE",
        "joystick/emergency stop": "SUP-DRIVE-HMI",
        "armrest status display": "SUP-STATUS-DISPLAY",
        "Qi2 charging/FOD module": "SUP-QI2-MODULE",
        "obstacle-assist telescopic handle": "SUP-OBSTACLE-HANDLE",
        "PDU/contactors/fuses": "SUP-PDU-PROTECTION",
        "DC/DC and optional dock AC": "SUP-POWER-CONVERSION",
        "wheels/tyres/bearings": "SUP-WHEEL-END",
        "drawer slides/latches": "SUP-DRAWER-HARDWARE",
        "mast actuator/reeving": "SUP-MAST-ACTUATION",
        "canopy motor/fabric/sensors": "SUP-CANOPY-PACKAGE",
        "compute/comms/storage": "SUP-COMPUTE-COMMS",
        "UWB owner ranging": "SUP-UWB-RANGING",
        "low-base 3D/ToF perception": "SUP-BASE-PERCEPTION",
        "protective-field scanner": "SUP-PROTECTIVE-SCANNER",
        "cliff sensors and tactile bumper": "SUP-CLIFF-BUMPER",
        "independent safety MCU/PMIC": "SUP-SAFETY-CONTROLLER",
        "dual motor controllers/STO": "SUP-MOTOR-STO",
        "cameras/microphones/lights": "SUP-CREATOR-SENSORS",
        "fans/heat exchanger/filters": "SUP-THERMAL-HARDWARE",
        "connectors/wire/cable chains": "SUP-HARNESS-HARDWARE",
        "PC-ABS resin/color": "SUP-PCABS-CMF",
        "foam/upholstery": "SUP-SEATING-SOFTGOODS",
        "structural aluminium/steel": "SUP-STRUCTURAL-MATERIAL",
        "fasteners/adhesives/seals": "SUP-JOINING-SEALING",
    }
    keys = ("commodity", "priority", "release_requirements", "status")
    rows = [
        {"supplier_item_id": supplier_item_ids[row[0]], **dict(zip(keys, row))}
        for row in data
    ]
    for row in rows:
        row.update({"supplier": "TBD", "manufacturer_part_number": "TBD", "sample_approved": "NO", "quality_agreement": "NO", "second_source": "NO", "change_notification": "NO"})
    return rows


def readiness_gates() -> list[dict]:
    data = [
        ("G-001", "regulatory", "预期用途、禁忌和对外声明冻结", "P0", "partial", "产品定义存在；禁忌/误用未完整"),
        ("G-002", "regulatory", "目标市场、医疗器械分类和注册路径书面确认", "P0", "open", "无合格机构结论"),
        ("G-003", "regulatory", "现行标准适用性矩阵及偏离处理", "P0", "partial", "已映射GB/T 18029域，未形成条款级矩阵"),
        ("G-004", "quality", "QMS、设计开发计划、职责和设计历史文件", "P0", "open", "未见受控QMS证据"),
        ("G-005", "requirements", "需求追踪矩阵", "P0", "partial", "本轮生成初版，尚未评审签署"),
        ("G-006", "configuration", "版本、变更、偏差和问题闭环系统", "P0", "open", "文件未纳入受控发布流程"),
        ("G-007", "risk", "正式风险管理计划、可接受准则和风险管理报告", "P0", "open", "仅初步FMEA"),
        ("G-008", "risk", "系统危害分析、DFMEA、FTA和控制验证追踪", "P0", "partial", "有状态机和风险初表，未签署"),
        ("G-009", "safety", "独立安全架构、诊断覆盖和单点故障策略", "P0", "partial", "架构原则存在，硬件/软件未实现"),
        ("G-010", "software", "软件需求、架构、编码/评审/测试和发布流程", "P0", "open", "无固件工程交付物"),
        ("G-011", "cybersecurity", "威胁模型、安全启动、OTA、密钥和隐私生命周期", "P0", "open", "未定义"),
        ("G-012", "human_factors", "可用性工程计划、关键任务和使用错误分析", "P0", "partial", "产品优先级存在，未形成正式计划"),
        ("G-013", "human_factors", "东亚/老年人在环形成性和总结性验证", "P0", "open", "未执行"),
        ("G-014", "seating", "压力、热湿、泡棉、软包和接触材料冻结", "P0", "open", "只有外形包络"),
        ("G-015", "industrial_design", "CMF主规范、黄金样、限度样、清洁和老化", "P1", "partial", "材料方向存在，未冻结"),
        ("G-016", "industrial_design", "Class-A曲面、分件、拔模、筋柱、密封和装饰缝", "P1", "open", "当前壳体不可开模"),
        ("G-017", "mechanical", "参数CAD、关键运动和未分类干涉自动检查", "P0", "partial", "名义CAD自动回归通过；尚无制造公差包络、实物复测或受控签署，不构成设计冻结关闭"),
        ("G-018", "mechanical", "承力件2D图、GD&T、焊接/热处理和关键尺寸链", "P0", "open", "只有STEP和9项公差记录"),
        ("G-019", "mechanical", "紧固件、扭矩、锁固、粘接和防错规范", "P0", "open", "未定义"),
        ("G-020", "dfma", "正式DFM/DFA和维修可达性审查", "P1", "open", "仅原则性模块化"),
        ("G-021", "electrical", "功率/能量/热管理预算", "P0", "partial", "power_thermal_report.json仅为工程设计包络；供应商选型、保护协调、热实测和受控签署未完成"),
        ("G-022", "electrical", "原理图、线束图、针脚、接地、保护协调和降额", "P0", "open", "只有架构和线径包络"),
        ("G-023", "electrical", "电芯/BMS/充电器/接触器精确选型", "P0", "open", "均为供应商选择门"),
        ("G-024", "verification", "DVP&R批准、样本量、设备和接受准则冻结", "P0", "partial", "本轮生成计划，尚未签署"),
        ("G-025", "verification", "EVT无人/配重/人在环结果", "P0", "open", "未见物理报告"),
        ("G-026", "verification", "DVT法规、可靠性、环境、EMC和滥用结果", "P0", "open", "未执行"),
        ("G-027", "supply", "生产BOM、制造商料号、成本、寿命和替代策略", "P0", "partial", "仅有候选构型并集；物理件ID/姿态质量/选装effectivity未对账，绝大多数料号未定"),
        ("G-028", "supply", "供应商审核、质量协议、首件/PPAP和变更通知", "P0", "open", "未建立"),
        ("G-029", "manufacturing", "工艺流程、PFMEA、控制计划、工装和作业指导书", "P0", "open", "未建立"),
        ("G-030", "manufacturing", "量检具MSA、关键特性能力和限度样", "P0", "open", "未建立"),
        ("G-031", "manufacturing", "100% EOL安全测试和序列号追溯", "P0", "open", "未建立"),
        ("G-032", "logistics", "包装、危险品运输、UN38.3概要和实车装载", "P0", "open", "未建立"),
        ("G-033", "service", "维修手册、备件、工具、工时和维修后EOL", "P1", "open", "未建立"),
        ("G-034", "labeling", "铭牌、警告、IFU、训练和理解性验证", "P0", "open", "未建立"),
        ("G-035", "pilot", "PVT试产、良率、节拍、返工、能力和问题关闭", "P0", "open", "未执行"),
        ("G-036", "release", "设计转移、最终风险报告和量产放行签署", "P0", "open", "未满足前置条件"),
    ]
    keys = ("gate_id", "pillar", "deliverable", "priority", "status", "current_evidence")
    rows = [dict(zip(keys, row)) for row in data]
    for row in rows:
        row["exit_criterion"] = "受控文件已批准且引用的客观证据可追溯"
        row["owner"] = "TBD"
        row["approver"] = "TBD"
        row["approval"] = "NOT_APPROVED"
        row["objective_evidence_ids"] = ""
    return rows


def _split_ids(value: str) -> set[str]:
    return {item for item in value.split(";") if item}


def traceability_integrity(req: list[dict], risk: list[dict], tests: list[dict]) -> dict:
    """Check stable IDs, references, bidirectional links, and required coverage.

    This is a structural check only.  A passing result does not mean that a
    control is implemented, a test is executed, or residual risk is accepted.
    """

    requirement_id_list = [row["requirement_id"] for row in req]
    risk_id_list = [row["risk_id"] for row in risk]
    test_id_list = [row["test_id"] for row in tests]
    control_id_list = [row["control_id"] for row in risk]
    requirement_ids = set(requirement_id_list)
    risk_ids = set(risk_id_list)
    test_ids = set(test_id_list)
    control_ids = set(control_id_list)

    duplicates = {
        "requirement_ids": sorted(key for key, count in Counter(requirement_id_list).items() if count > 1),
        "risk_ids": sorted(key for key, count in Counter(risk_id_list).items() if count > 1),
        "test_ids": sorted(key for key, count in Counter(test_id_list).items() if count > 1),
        "control_ids": sorted(key for key, count in Counter(control_id_list).items() if count > 1),
    }

    invalid_references = {
        "requirement_to_risk": [],
        "requirement_to_control": [],
        "requirement_to_test": [],
        "risk_to_requirement": [],
        "risk_to_test": [],
        "test_to_requirement": [],
        "test_to_risk": [],
        "test_to_control": [],
        "mapping_source_ids": [],
    }
    requirement_by_id = {row["requirement_id"]: row for row in req}
    risk_by_id = {row["risk_id"]: row for row in risk}
    test_by_id = {row["test_id"]: row for row in tests}

    for row in req:
        source_id = row["requirement_id"]
        for target_id in _split_ids(row["linked_risk_ids"]) - risk_ids:
            invalid_references["requirement_to_risk"].append(f"{source_id}->{target_id}")
        for target_id in _split_ids(row["linked_control_ids"]) - control_ids:
            invalid_references["requirement_to_control"].append(f"{source_id}->{target_id}")
        for target_id in _split_ids(row["linked_test_ids"]) - test_ids:
            invalid_references["requirement_to_test"].append(f"{source_id}->{target_id}")
    for row in risk:
        source_id = row["risk_id"]
        for target_id in _split_ids(row["linked_requirement_ids"]) - requirement_ids:
            invalid_references["risk_to_requirement"].append(f"{source_id}->{target_id}")
        for target_id in _split_ids(row["linked_test_ids"]) - test_ids:
            invalid_references["risk_to_test"].append(f"{source_id}->{target_id}")
    for row in tests:
        source_id = row["test_id"]
        for target_id in _split_ids(row["linked_requirement_ids"]) - requirement_ids:
            invalid_references["test_to_requirement"].append(f"{source_id}->{target_id}")
        for target_id in _split_ids(row["linked_risk_ids"]) - risk_ids:
            invalid_references["test_to_risk"].append(f"{source_id}->{target_id}")
        for target_id in _split_ids(row["linked_control_ids"]) - control_ids:
            invalid_references["test_to_control"].append(f"{source_id}->{target_id}")

    for source_id in sorted((set(REQUIREMENT_RISK_LINKS) | set(REQUIREMENT_TEST_LINKS)) - requirement_ids):
        invalid_references["mapping_source_ids"].append(source_id)
    for source_id in sorted(set(RISK_TEST_LINKS) - risk_ids):
        invalid_references["mapping_source_ids"].append(source_id)

    bidirectional_mismatches = {
        "requirement_risk": [],
        "requirement_test": [],
        "risk_test": [],
        "control_derivation": [],
    }
    for requirement_id, row in requirement_by_id.items():
        row_risk_ids = _split_ids(row["linked_risk_ids"])
        for risk_id in row_risk_ids & risk_ids:
            if requirement_id not in _split_ids(risk_by_id[risk_id]["linked_requirement_ids"]):
                bidirectional_mismatches["requirement_risk"].append(f"{requirement_id}<->{risk_id}")
        row_test_ids = _split_ids(row["linked_test_ids"])
        for test_id in row_test_ids & test_ids:
            if requirement_id not in _split_ids(test_by_id[test_id]["linked_requirement_ids"]):
                bidirectional_mismatches["requirement_test"].append(f"{requirement_id}<->{test_id}")
        expected_controls = {_control_id(risk_id) for risk_id in row_risk_ids}
        if _split_ids(row["linked_control_ids"]) != expected_controls:
            bidirectional_mismatches["control_derivation"].append(requirement_id)
    for risk_id, row in risk_by_id.items():
        for test_id in _split_ids(row["linked_test_ids"]) & test_ids:
            if risk_id not in _split_ids(test_by_id[test_id]["linked_risk_ids"]):
                bidirectional_mismatches["risk_test"].append(f"{risk_id}<->{test_id}")
    for test_id, row in test_by_id.items():
        expected_controls = {_control_id(risk_id) for risk_id in _split_ids(row["linked_risk_ids"])}
        if _split_ids(row["linked_control_ids"]) != expected_controls:
            bidirectional_mismatches["control_derivation"].append(test_id)

    p0_requirements_missing_links = {
        "risk": sorted(row["requirement_id"] for row in req if row["priority"] == "P0" and not row["linked_risk_ids"]),
        "control": sorted(row["requirement_id"] for row in req if row["priority"] == "P0" and not row["linked_control_ids"]),
        "test": sorted(row["requirement_id"] for row in req if row["priority"] == "P0" and not row["linked_test_ids"]),
    }
    orphan_ids = {
        "requirements": sorted(
            row["requirement_id"]
            for row in req
            if not row["linked_risk_ids"] or not row["linked_control_ids"] or not row["linked_test_ids"]
        ),
        "risks": sorted(
            row["risk_id"]
            for row in risk
            if not row["linked_requirement_ids"] or not row["control_id"] or not row["linked_test_ids"]
        ),
        "tests": sorted(
            row["test_id"]
            for row in tests
            if not row["linked_requirement_ids"] or not row["linked_risk_ids"] or not row["linked_control_ids"]
        ),
    }
    problem_lists = [
        *duplicates.values(),
        *invalid_references.values(),
        *bidirectional_mismatches.values(),
        *p0_requirements_missing_links.values(),
        *orphan_ids.values(),
    ]
    passed = not any(problem_lists)
    return {
        "pass": passed,
        "scope_note": "Structural ID/link coverage only; it does not close implementation, execution, approval, or residual-risk evidence.",
        "counts": {
            "requirements": len(req),
            "p0_requirements": sum(row["priority"] == "P0" for row in req),
            "risks": len(risk),
            "controls": len(control_ids),
            "tests": len(tests),
        },
        "duplicates": duplicates,
        "invalid_references": invalid_references,
        "bidirectional_mismatches": bidirectional_mismatches,
        "p0_requirements_missing_links": p0_requirements_missing_links,
        "orphan_ids": orphan_ids,
    }


def analyze_and_write(configs: dict, reports: dict, build_dir: Path) -> dict:
    production_bom = write_production_bom(configs, build_dir / "production_bom.csv")
    req = requirements()
    risk = risks()
    tests = dvpr()
    suppliers = supplier_release_rows()
    gates = readiness_gates()
    traceability = traceability_integrity(req, risk, tests)
    if not traceability["pass"]:
        raise ValueError(
            "Readiness traceability integrity failed: "
            + json.dumps(traceability, ensure_ascii=False)
        )
    _write_csv(build_dir / "requirements_traceability.csv", req)
    _write_csv(build_dir / "risk_register.csv", risk)
    _write_csv(build_dir / "dvpr.csv", tests)
    _write_csv(build_dir / "supplier_release_register.csv", suppliers)
    _write_csv(build_dir / "production_gate_checklist.csv", gates)

    all_automated_checks = []
    for report in reports.values():
        all_automated_checks.extend(report.get("checks", []))
    failed_automated = [check for check in all_automated_checks if not check.get("pass", False)]
    geometry_failures = [check for check in reports.get("geometry", {}).get("checks", []) if not check.get("pass", False)]
    power_failures = [check for check in reports.get("power_thermal", {}).get("checks", []) if not check.get("pass", False)]
    gate_by_id = {row["gate_id"]: row for row in gates}
    if geometry_failures:
        gate_by_id["G-017"]["status"] = "open"
        gate_by_id["G-017"]["current_evidence"] = f"{len(geometry_failures)}项几何/干涉自动检查失败；不得沿用名义通过状态"
    if power_failures:
        gate_by_id["G-021"]["status"] = "open"
        gate_by_id["G-021"]["current_evidence"] = f"{len(power_failures)}项功率/能量/热自动检查失败；供应商和物理证据亦未完成"
    evidence_index = 100.0 * sum(STATUS_VALUE[row["status"]] for row in gates) / len(gates)
    p0_open = [row for row in gates if row["priority"] == "P0" and row["status"] != "closed"]
    status_counts = Counter(row["status"] for row in gates)
    report = {
        "revision": "E6-DFR3",
        "conclusion": "EVT engineering prototype input only; NOT READY for design freeze, DVT, PVT or mass production",
        "automated_model_checks": {
            "total": len(all_automated_checks),
            "failed": len(failed_automated),
            "scope_note": "Automated analytical checks do not close physical, regulatory, supplier or manufacturing gates.",
        },
        "production_evidence_index_percent": round(evidence_index, 1),
        "index_method": f"closed=1, partial=0.5, open=0 across {len(gates)} evidence gates; this is a completeness indicator, not certification probability",
        "gate_status_counts": dict(status_counts),
        "p0_not_closed": len(p0_open),
        "p0_not_closed_ids": [row["gate_id"] for row in p0_open],
        "traceability_integrity": traceability,
        "requirements": {
            "count": len(req),
            "status_counts": dict(Counter(row["status"] for row in req)),
            "p0_with_complete_structural_links": sum(
                row["priority"] == "P0"
                and bool(row["linked_risk_ids"])
                and bool(row["linked_control_ids"])
                and bool(row["linked_test_ids"])
                for row in req
            ),
            "scope_note": "Complete structural links do not mean that controls are implemented or tests executed.",
        },
        "risks": {
            "count": len(risk),
            "open_or_partial": sum(row["status"] != "closed" for row in risk),
            "with_requirement_control_test_links": sum(
                bool(row["linked_requirement_ids"])
                and bool(row["control_id"])
                and bool(row["linked_test_ids"])
                for row in risk
            ),
        },
        "dvpr": {
            "planned_tests": len(tests),
            "executed_tests": 0,
            "with_requirement_risk_control_links": sum(
                bool(row["linked_requirement_ids"])
                and bool(row["linked_risk_ids"])
                and bool(row["linked_control_ids"])
                for row in tests
            ),
        },
        "supplier_release": {
            "commodities": len(suppliers),
            "stable_supplier_item_ids": len({row["supplier_item_id"] for row in suppliers}),
            "fully_released": 0,
        },
        "production_bom": production_bom,
        "stage_decision": {
            "concept_architecture": "PASS_WITH_OPEN_ACTIONS",
            "EVT0_unoccupied_or_dummy_prototype": "CONDITIONAL_GO after lab safety plan and emergency-stop/remote-disable are implemented",
            "human_occupied_testing": "NO_GO until braking, stability, restraint, egress, electrical isolation and ethics/safety controls pass",
            "design_freeze_DVT": "NO_GO",
            "PVT_mass_production": "NO_GO",
        },
        "next_gate_sequence": [
            "G0 regulatory classification, intended use, risk acceptability and QMS ownership",
            "EVT0 unoccupied rolling chassis, brake, power and fault-safe rig",
            "EVT1 weighted dummy plus mechanisms, thermal, ingress and EMC pre-scan",
            "formative human-factors mockups followed by controlled low-speed occupied work",
            "DVT design-intent units for full DVP&R and compliance",
            "PVT production-intent tooling/process/EOL/traceability and capability",
            "final risk report, design transfer and signed release",
        ],
        "sources": {
            "gbt_18029_catalogue": "https://openstd.samr.gov.cn/bzgk/std/std_list?p.p1=0&p.p2=GB%2FT+18029&p.p90=circulation_date&p.p91=desc",
            "iso_wheelchair_guide_2025": "https://committee.iso.org/files/live/sites/tc173/files/Library/WC%20Standard%20Guide%202025.pdf",
            "iso_7176_14": "https://www.iso.org/standard/72408.html",
            "iso_7176_21_2025": "https://www.iso.org/standard/82763.html",
            "iso_14971": "https://www.iso.org/standard/72704.html",
            "iec_62366_1": "https://www.iso.org/standard/63179.html",
            "iso_13485": "https://www.iso.org/standard/59752.html",
            "un_38_3": "https://unece.org/transport/standards/transport/dangerous-goods/un-manual-tests-and-criteria-rev8-2023",
        },
        "gates": gates,
    }
    (build_dir / "production_readiness_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report

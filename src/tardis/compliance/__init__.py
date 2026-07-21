"""
Compliance & Governance Auto-Auditor

Real-time generation of audit trails mapping every AI decisions to safety
policies and regulations, automatically flagging violations of GDPR, HIPAA,
or EU AI Act requirements.

LEGAL DISCLAIMER: This tool provides automated compliance checking guidance
only. It is NOT legal advice. Compliance requirements vary by jurisdiction
and change over time. Always consult qualified legal counsel for compliance
decisions. This tool does not guarantee compliance with any regulation.
"""

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class Regulation(str, Enum):
    """Supported regulations and frameworks."""

    GDPR = "gdpr"  # EU General Data Protection Regulation
    HIPAA = "hipaa"  # US Health Insurance Portability and Accountability Act
    EU_AI_ACT = "eu_ai_act"  # EU Artificial Intelligence Act
    SOC2 = "soc2"  # Service Organization Control 2
    PCI_DSS = "pci_dss"  # Payment Card Industry Data Security Standard
    CCPA = "ccpa"  # California Consumer Privacy Act


class ViolationSeverity(str, Enum):
    """Severity levels for compliance violations."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ComplianceViolation:
    """Record of a compliance violation."""

    violation_id: str
    regulation: Regulation
    requirement: str
    severity: ViolationSeverity
    description: str
    evidence: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    remediation: str | None = None
    status: str = "open"  # open, acknowledged, resolved, false_positive

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "regulation": self.regulation.value,
            "requirement": self.requirement,
            "severity": self.severity.value,
            "description": self.description,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
            "remediation": self.remediation,
            "status": self.status,
        }


@dataclass
class AuditEntry:
    """Single entry in the audit trail."""

    entry_id: str
    trace_id: str
    step_id: str
    action_type: str
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    decision_rationale: str | None
    regulations_checked: list[Regulation]
    violations_found: list[str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "trace_id": self.trace_id,
            "step_id": self.step_id,
            "action_type": self.action_type,
            "input_data_hash": hashlib.sha256(
                json.dumps(self.input_data or {}, sort_keys=True).encode()
            ).hexdigest()[:16]
            if self.input_data
            else None,
            "output_data_hash": hashlib.sha256(
                json.dumps(self.output_data or {}, sort_keys=True).encode()
            ).hexdigest()[:16]
            if self.output_data
            else None,
            "decision_rationale": self.decision_rationale,
            "regulations_checked": [r.value for r in self.regulations_checked],
            "violations_found": self.violations_found,
            "timestamp": self.timestamp,
        }


class ComplianceChecker:
    """Checks actions against specific regulatory requirements."""

    def __init__(self):
        self.requirements = self._load_requirements()

    def _load_requirements(self) -> dict[Regulation, list[dict[str, Any]]]:
        """Load regulatory requirements."""
        return {
            Regulation.GDPR: [
                {
                    "id": "GDPR-Art5-1a",
                    "name": "Lawfulness, fairness, transparency",
                    "check": self._check_gdpr_transparency,
                },
                {
                    "id": "GDPR-Art5-1c",
                    "name": "Data minimization",
                    "check": self._check_gdpr_minimization,
                },
                {
                    "id": "GDPR-Art17",
                    "name": "Right to erasure",
                    "check": self._check_gdpr_erasure,
                },
                {
                    "id": "GDPR-Art22",
                    "name": "Automated decision-making",
                    "check": self._check_gdpr_automated_decision,
                },
            ],
            Regulation.HIPAA: [
                {
                    "id": "HIPAA-164.312(a)",
                    "name": "Access control",
                    "check": self._check_hipaa_access_control,
                },
                {
                    "id": "HIPAA-164.312(b)",
                    "name": "Audit controls",
                    "check": self._check_hipaa_audit_controls,
                },
                {
                    "id": "HIPAA-164.514",
                    "name": "De-identification",
                    "check": self._check_hipaa_deidentification,
                },
            ],
            Regulation.EU_AI_ACT: [
                {
                    "id": "EU-AI-Art15",
                    "name": "Human oversight",
                    "check": self._check_eu_ai_oversight,
                },
                {
                    "id": "EU-AI-Art10",
                    "name": "Data governance",
                    "check": self._check_eu_ai_governance,
                },
                {
                    "id": "EU-AI-Art13",
                    "name": "Transparency",
                    "check": self._check_eu_ai_transparency,
                },
            ],
            Regulation.SOC2: [
                {
                    "id": "SOC2-CC6.1",
                    "name": "Logical access controls",
                    "check": self._check_soc2_access_controls,
                },
                {
                    "id": "SOC2-CC7.2",
                    "name": "System monitoring",
                    "check": self._check_soc2_monitoring,
                },
                {
                    "id": "SOC2-CC8.1",
                    "name": "Change management",
                    "check": self._check_soc2_change_management,
                },
            ],
            Regulation.PCI_DSS: [
                {
                    "id": "PCI-DSS-3.4",
                    "name": "Cardholder data protection",
                    "check": self._check_pci_data_protection,
                },
                {
                    "id": "PCI-DSS-10.2",
                    "name": "Audit trail requirements",
                    "check": self._check_pci_audit_trail,
                },
                {
                    "id": "PCI-DSS-11.4",
                    "name": "Network segmentation",
                    "check": self._check_pci_network_segmentation,
                },
            ],
            Regulation.CCPA: [
                {
                    "id": "CCPA-1798.100",
                    "name": "Right to know",
                    "check": self._check_ccpa_right_to_know,
                },
                {
                    "id": "CCPA-1798.105",
                    "name": "Right to delete",
                    "check": self._check_ccpa_right_to_delete,
                },
                {
                    "id": "CCPA-1798.120",
                    "name": "Right to opt-out of sale",
                    "check": self._check_ccpa_opt_out,
                },
            ],
        }

    def check_action(
        self,
        action_type: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        regulations: list[Regulation],
    ) -> list[ComplianceViolation]:
        """Check an action against specified regulations."""
        violations = []

        for regulation in regulations:
            requirements = self.requirements.get(regulation, [])

            for req in requirements:
                try:
                    result = req["check"](action_type, input_data, output_data)

                    if result["violated"]:
                        violation = ComplianceViolation(
                            violation_id=f"{req['id']}_{int(time.time() * 1000)}",
                            regulation=regulation,
                            requirement=req["id"],
                            severity=result.get("severity", ViolationSeverity.MEDIUM),
                            description=result["description"],
                            evidence=result.get("evidence", {}),
                            remediation=result.get("remediation"),
                        )
                        violations.append(violation)

                except Exception:
                    # Log error but don't fail the entire check
                    pass

        return violations

    # GDPR checks
    def _check_gdpr_transparency(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check if processing is transparent to users."""
        # Simulated check - in production would verify consent records
        if "consent_id" not in input_data and action_type in [
            "process_personal_data",
            "profile_user",
        ]:
            return {
                "violated": True,
                "severity": ViolationSeverity.HIGH,
                "description": "Processing personal data without recorded consent",
                "evidence": {"action_type": action_type},
                "remediation": "Obtain and record user consent before processing",
            }
        return {"violated": False}

    def _check_gdpr_minimization(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check if data collection is minimized."""
        excessive_fields = ["ssn", "credit_card", "bank_account", "password"]
        collected_excessive = [f for f in excessive_fields if f in input_data]

        if collected_excessive and action_type not in [
            "authentication",
            "payment_processing",
        ]:
            return {
                "violated": True,
                "severity": ViolationSeverity.MEDIUM,
                "description": f"Collecting potentially excessive data: {collected_excessive}",
                "evidence": {"fields": collected_excessive},
                "remediation": "Review data collection necessity for this use case",
            }
        return {"violated": False}

    def _check_gdpr_erasure(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check if erasure requests are honored."""
        if input_data.get("erasure_request") and not output_data.get("erased"):
            return {
                "violated": True,
                "severity": ViolationSeverity.CRITICAL,
                "description": "Erasure request not fulfilled",
                "evidence": {"user_id": input_data.get("user_id")},
                "remediation": "Implement data erasure mechanism",
            }
        return {"violated": False}

    def _check_gdpr_automated_decision(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check automated decision-making compliance."""
        if action_type in ["credit_decision", "hiring_decision", "insurance_quote"]:
            if not input_data.get("human_review_available"):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.HIGH,
                    "description": "Automated decision without human review option",
                    "evidence": {"action_type": action_type},
                    "remediation": "Provide option for human review of automated decisions",
                }
        return {"violated": False}

    # HIPAA checks
    def _check_hipaa_access_control(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check access control compliance."""
        if "phi" in str(input_data).lower() or "health_record" in input_data:
            if not input_data.get("authorized_user"):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.CRITICAL,
                    "description": "PHI accessed without verified authorization",
                    "evidence": {"action_type": action_type},
                    "remediation": "Implement role-based access control for PHI",
                }
        return {"violated": False}

    def _check_hipaa_audit_controls(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check if audit logging is enabled."""
        if "phi" in str(input_data).lower() and not input_data.get("audit_logged"):
            return {
                "violated": True,
                "severity": ViolationSeverity.HIGH,
                "description": "PHI access not logged for audit",
                "evidence": {"action_type": action_type},
                "remediation": "Enable comprehensive audit logging for PHI access",
            }
        return {"violated": False}

    def _check_hipaa_deidentification(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check de-identification requirements."""
        identifiers = ["name", "address", "phone", "email", "ssn", "dob"]
        if output_data.get("export") or output_data.get("shared"):
            present_identifiers = [i for i in identifiers if i in output_data]
            if present_identifiers:
                return {
                    "violated": True,
                    "severity": ViolationSeverity.CRITICAL,
                    "description": f"Exporting data with PHI identifiers: {present_identifiers}",
                    "evidence": {"identifiers": present_identifiers},
                    "remediation": "Apply Safe Harbor de-identification before export",
                }
        return {"violated": False}

    # EU AI Act checks
    def _check_eu_ai_oversight(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check human oversight requirements."""
        high_risk_actions = [
            "medical_diagnosis",
            "recruitment",
            "credit_scoring",
            "law_enforcement",
        ]

        if action_type in high_risk_actions and not input_data.get("human_oversight"):
            return {
                "violated": True,
                "severity": ViolationSeverity.HIGH,
                "description": f"High-risk AI system operating without human oversight: {action_type}",
                "evidence": {"action_type": action_type},
                "remediation": "Implement human-in-the-loop for high-risk AI applications",
            }
        return {"violated": False}

    def _check_eu_ai_governance(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check data governance requirements."""
        if not input_data.get("data_quality_verified") and action_type in [
            "model_inference",
            "training",
        ]:
            return {
                "violated": True,
                "severity": ViolationSeverity.MEDIUM,
                "description": "AI system using unverified training/inference data",
                "evidence": {"action_type": action_type},
                "remediation": "Implement data quality verification processes",
            }
        return {"violated": False}

    def _check_eu_ai_transparency(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check transparency requirements."""
        if action_type == "ai_interaction" and not input_data.get("disclosed_as_ai"):
            return {
                "violated": True,
                "severity": ViolationSeverity.MEDIUM,
                "description": "AI interaction not disclosed to user",
                "evidence": {"action_type": action_type},
                "remediation": "Disclose AI nature of interaction to users",
            }
        return {"violated": False}

    # SOC2 checks
    def _check_soc2_access_controls(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check SOC2 logical access controls (CC6.1)."""
        sensitive_actions = [
            "database_write",
            "config_change",
            "user_management",
            "api_key_rotation",
        ]
        if action_type in sensitive_actions:
            if not input_data.get("authenticated") and not input_data.get("auth_token"):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.HIGH,
                    "description": f"Sensitive action '{action_type}' performed without authentication verification",
                    "evidence": {"action_type": action_type},
                    "remediation": "Require authenticated session for all sensitive operations",
                }
        return {"violated": False}

    def _check_soc2_monitoring(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check SOC2 system monitoring (CC7.2)."""
        if action_type in [
            "security_incident",
            "anomaly_detected",
            "unauthorized_access",
        ]:
            if not input_data.get("logged") and not output_data.get("alerted"):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.HIGH,
                    "description": f"Security event '{action_type}' not logged or alerted",
                    "evidence": {"action_type": action_type},
                    "remediation": "Ensure all security events are logged and trigger alerts",
                }
        return {"violated": False}

    def _check_soc2_change_management(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check SOC2 change management (CC8.1)."""
        if action_type in ["deploy", "config_change", "schema_migration"]:
            if not input_data.get("change_ticket") and not input_data.get(
                "approved_by"
            ):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.MEDIUM,
                    "description": f"Change '{action_type}' performed without change ticket or approval",
                    "evidence": {"action_type": action_type},
                    "remediation": "Require change tickets and approvals for production changes",
                }
        return {"violated": False}

    # PCI DSS checks
    def _check_pci_data_protection(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check PCI DSS cardholder data protection (3.4)."""
        card_data_fields = ["card_number", "pan", "cvv", "expiry", "track_data"]
        present_fields = [
            f for f in card_data_fields if f in input_data or f in output_data
        ]
        if present_fields:
            if not input_data.get("encrypted") and not output_data.get("encrypted"):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.CRITICAL,
                    "description": f"Cardholder data fields present without encryption: {present_fields}",
                    "evidence": {"fields": present_fields},
                    "remediation": "Encrypt all cardholder data at rest and in transit",
                }
        return {"violated": False}

    def _check_pci_audit_trail(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check PCI DSS audit trail requirements (10.2)."""
        if action_type in ["payment_processing", "card_access", "refund"]:
            if not input_data.get("audit_log") and not output_data.get("audit_log"):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.HIGH,
                    "description": f"Payment action '{action_type}' not included in audit trail",
                    "evidence": {"action_type": action_type},
                    "remediation": "Log all access to cardholder data with user ID, timestamp, and action",
                }
        return {"violated": False}

    def _check_pci_network_segmentation(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check PCI DSS network segmentation (11.4)."""
        if action_type in ["database_access", "payment_processing"]:
            source_ip = input_data.get("source_ip", "")
            if source_ip and not source_ip.startswith(("10.", "172.16.", "192.168.")):
                if not input_data.get("in_cde_network"):
                    return {
                        "violated": True,
                        "severity": ViolationSeverity.CRITICAL,
                        "description": f"Action '{action_type}' from non-CDE network segment: {source_ip}",
                        "evidence": {"source_ip": source_ip},
                        "remediation": "Ensure payment actions originate from within the Cardholder Data Environment",
                    }
        return {"violated": False}

    # CCPA checks
    def _check_ccpa_right_to_know(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check CCPA right to know (1798.100)."""
        if action_type == "data_collection" and input_data.get("california_consumer"):
            if not output_data.get("disclosure_provided") and not input_data.get(
                "notice_given"
            ):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.HIGH,
                    "description": "Data collected from CA consumer without notice of collection purpose",
                    "evidence": {"action_type": action_type},
                    "remediation": "Provide clear notice of data collection categories and purposes at point of collection",
                }
        return {"violated": False}

    def _check_ccpa_right_to_delete(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check CCPA right to delete (1798.105)."""
        if input_data.get("deletion_request") and input_data.get("california_consumer"):
            if not output_data.get("deleted") and not output_data.get(
                "deletion_scheduled"
            ):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.CRITICAL,
                    "description": "Consumer deletion request not fulfilled or scheduled",
                    "evidence": {"consumer_id": input_data.get("consumer_id")},
                    "remediation": "Process deletion requests within 45 days; maintain deletion log",
                }
        return {"violated": False}

    def _check_ccpa_opt_out(
        self, action_type: str, input_data: dict, output_data: dict
    ) -> dict[str, Any]:
        """Check CCPA right to opt-out of sale (1798.120)."""
        if action_type == "data_sale" and input_data.get("california_consumer"):
            if not input_data.get("opt_out_confirmed") and not input_data.get(
                "opt_out_check_done"
            ):
                return {
                    "violated": True,
                    "severity": ViolationSeverity.CRITICAL,
                    "description": "Consumer data sold without verifying opt-out status",
                    "evidence": {"action_type": action_type},
                    "remediation": "Check consumer opt-out status before selling personal information",
                }
        return {"violated": False}


class ComplianceAuditor:
    """Main compliance auditing system."""

    def __init__(self, storage_dir: str = ".tardis/compliance"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.checker = ComplianceChecker()
        self.audit_trail: list[AuditEntry] = []
        self.violations: list[ComplianceViolation] = []
        self.alert_callback: Callable | None = None

    def audit_step(
        self,
        trace_id: str,
        step_id: str,
        action_type: str,
        input_data: dict[str, Any] | None,
        output_data: dict[str, Any] | None,
        decision_rationale: str | None = None,
        regulations: list[Regulation] | None = None,
    ) -> AuditEntry:
        """Audit a single step/action."""
        if regulations is None:
            regulations = getattr(
                self,
                "_active_regulations",
                [Regulation.GDPR, Regulation.HIPAA, Regulation.EU_AI_ACT],
            )

        # Check for violations
        violations = self.checker.check_action(
            action_type,
            input_data or {},
            output_data or {},
            regulations,
        )

        # Create audit entry
        entry = AuditEntry(
            entry_id=f"audit_{int(time.time() * 1000)}",
            trace_id=trace_id,
            step_id=step_id,
            action_type=action_type,
            input_data=input_data,
            output_data=output_data,
            decision_rationale=decision_rationale,
            regulations_checked=regulations,
            violations_found=[v.violation_id for v in violations],
        )

        self.audit_trail.append(entry)

        # Record violations
        for violation in violations:
            self.violations.append(violation)

            if self.alert_callback and violation.severity in [
                ViolationSeverity.HIGH,
                ViolationSeverity.CRITICAL,
            ]:
                self.alert_callback(violation)

        return entry

    def get_violations_report(
        self,
        regulation: Regulation | None = None,
        severity: ViolationSeverity | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Generate violations report with filters."""
        filtered = self.violations

        if regulation:
            filtered = [v for v in filtered if v.regulation == regulation]
        if severity:
            filtered = [v for v in filtered if v.severity == severity]
        if status:
            filtered = [v for v in filtered if v.status == status]

        by_severity = {}
        by_regulation = {}
        by_status = {}

        for v in filtered:
            by_severity[v.severity.value] = by_severity.get(v.severity.value, 0) + 1
            by_regulation[v.regulation.value] = (
                by_regulation.get(v.regulation.value, 0) + 1
            )
            by_status[v.status] = by_status.get(v.status, 0) + 1

        return {
            "total_violations": len(filtered),
            "by_severity": by_severity,
            "by_regulation": by_regulation,
            "by_status": by_status,
            "critical_violations": [
                v.to_dict()
                for v in filtered
                if v.severity == ViolationSeverity.CRITICAL
            ],
            "generated_at": datetime.now().isoformat(),
        }

    def export_audit_trail(self, output_path: str, format: str = "json") -> Path:
        """Export audit trail for external review."""
        output_file = Path(output_path)

        if format == "json":
            data = [entry.to_dict() for entry in self.audit_trail]
            with open(output_file, "w") as f:
                json.dump(data, f, indent=2)
        elif format == "csv":
            import csv

            with open(output_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "entry_id",
                        "trace_id",
                        "step_id",
                        "action_type",
                        "timestamp",
                        "regulations",
                        "violations",
                    ]
                )
                for entry in self.audit_trail:
                    writer.writerow(
                        [
                            entry.entry_id,
                            entry.trace_id,
                            entry.step_id,
                            entry.action_type,
                            datetime.fromtimestamp(entry.timestamp).isoformat(),
                            "|".join(r.value for r in entry.regulations_checked),
                            "|".join(entry.violations_found),
                        ]
                    )

        return output_file

    def get_compliance_score(self) -> dict[str, Any]:
        """Calculate overall compliance score."""
        if not self.audit_trail:
            return {"status": "no_audits_performed"}

        total_checks = len(self.audit_trail)
        violations_count = len(self.violations)

        critical_count = sum(
            1 for v in self.violations if v.severity == ViolationSeverity.CRITICAL
        )
        high_count = sum(
            1 for v in self.violations if v.severity == ViolationSeverity.HIGH
        )

        # Score calculation (100 = perfect compliance)
        score = max(
            0, 100 - (critical_count * 20) - (high_count * 10) - (violations_count * 2)
        )

        return {
            "compliance_score": score,
            "grade": self._score_to_grade(score),
            "total_audits": total_checks,
            "total_violations": violations_count,
            "critical_issues": critical_count,
            "high_issues": high_count,
            "recommendation": self._get_recommendation(score),
        }

    def _score_to_grade(self, score: int) -> str:
        """Convert score to letter grade."""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"

    def _get_recommendation(self, score: int) -> str:
        """Get recommendation based on score."""
        if score >= 90:
            return "Excellent compliance posture. Continue monitoring."
        elif score >= 80:
            return "Good compliance. Address remaining issues promptly."
        elif score >= 70:
            return "Moderate compliance. Prioritize fixing high-severity issues."
        elif score >= 60:
            return "Poor compliance. Immediate action required."
        else:
            return "Critical compliance failures. Halt operations and remediate."


# Convenience functions
def enable_compliance_auditing(
    regulations: list[Regulation] | None = None,
    alert_callback: Callable | None = None,
) -> ComplianceAuditor:
    """Enable compliance auditing with specified regulations."""
    auditor = ComplianceAuditor()
    auditor.alert_callback = alert_callback
    auditor._active_regulations = regulations or [
        Regulation.GDPR,
        Regulation.HIPAA,
        Regulation.EU_AI_ACT,
    ]
    return auditor


def create_compliance_checker() -> ComplianceChecker:
    """Create a standalone compliance checker."""
    return ComplianceChecker()

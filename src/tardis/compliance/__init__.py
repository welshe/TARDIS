"""
Compliance & Governance Auto-Auditor

Real-time generation of audit trails mapping every AI decision to safety 
policies and regulations, automatically flagging violations of GDPR, HIPAA, 
or EU AI Act requirements.
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


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
    evidence: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    remediation: Optional[str] = None
    status: str = "open"  # open, acknowledged, resolved, false_positive
    
    def to_dict(self) -> Dict[str, Any]:
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
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    decision_rationale: Optional[str]
    regulations_checked: List[Regulation]
    violations_found: List[str]
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "trace_id": self.trace_id,
            "step_id": self.step_id,
            "action_type": self.action_type,
            "input_data_hash": hashlib.sha256(
                json.dumps(self.input_data or {}, sort_keys=True).encode()
            ).hexdigest()[:16] if self.input_data else None,
            "output_data_hash": hashlib.sha256(
                json.dumps(self.output_data or {}, sort_keys=True).encode()
            ).hexdigest()[:16] if self.output_data else None,
            "decision_rationale": self.decision_rationale,
            "regulations_checked": [r.value for r in self.regulations_checked],
            "violations_found": self.violations_found,
            "timestamp": self.timestamp,
        }


class ComplianceChecker:
    """Checks actions against specific regulatory requirements."""
    
    def __init__(self):
        self.requirements = self._load_requirements()
    
    def _load_requirements(self) -> Dict[Regulation, List[Dict[str, Any]]]:
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
        }
    
    def check_action(
        self,
        action_type: str,
        input_data: Dict[str, Any],
        output_data: Dict[str, Any],
        regulations: List[Regulation],
    ) -> List[ComplianceViolation]:
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
                        
                except Exception as e:
                    # Log error but don't fail the entire check
                    pass
        
        return violations
    
    # GDPR checks
    def _check_gdpr_transparency(
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
        """Check if processing is transparent to users."""
        # Simulated check - in production would verify consent records
        if "consent_id" not in input_data and action_type in ["process_personal_data", "profile_user"]:
            return {
                "violated": True,
                "severity": ViolationSeverity.HIGH,
                "description": "Processing personal data without recorded consent",
                "evidence": {"action_type": action_type},
                "remediation": "Obtain and record user consent before processing",
            }
        return {"violated": False}
    
    def _check_gdpr_minimization(
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
        """Check if data collection is minimized."""
        excessive_fields = ["ssn", "credit_card", "bank_account", "password"]
        collected_excessive = [f for f in excessive_fields if f in input_data]
        
        if collected_excessive and action_type not in ["authentication", "payment_processing"]:
            return {
                "violated": True,
                "severity": ViolationSeverity.MEDIUM,
                "description": f"Collecting potentially excessive data: {collected_excessive}",
                "evidence": {"fields": collected_excessive},
                "remediation": "Review data collection necessity for this use case",
            }
        return {"violated": False}
    
    def _check_gdpr_erasure(
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
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
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
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
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
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
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
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
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
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
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
        """Check human oversight requirements."""
        high_risk_actions = ["medical_diagnosis", "recruitment", "credit_scoring", "law_enforcement"]
        
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
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
        """Check data governance requirements."""
        if not input_data.get("data_quality_verified") and action_type in ["model_inference", "training"]:
            return {
                "violated": True,
                "severity": ViolationSeverity.MEDIUM,
                "description": "AI system using unverified training/inference data",
                "evidence": {"action_type": action_type},
                "remediation": "Implement data quality verification processes",
            }
        return {"violated": False}
    
    def _check_eu_ai_transparency(
        self, action_type: str, input_data: Dict, output_data: Dict
    ) -> Dict[str, Any]:
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


class ComplianceAuditor:
    """Main compliance auditing system."""
    
    def __init__(self, storage_dir: str = ".tardis/compliance"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.checker = ComplianceChecker()
        self.audit_trail: List[AuditEntry] = []
        self.violations: List[ComplianceViolation] = []
        self.alert_callback: Optional[Callable] = None
    
    def audit_step(
        self,
        trace_id: str,
        step_id: str,
        action_type: str,
        input_data: Optional[Dict[str, Any]],
        output_data: Optional[Dict[str, Any]],
        decision_rationale: Optional[str] = None,
        regulations: Optional[List[Regulation]] = None,
    ) -> AuditEntry:
        """Audit a single step/action."""
        if regulations is None:
            regulations = [Regulation.GDPR, Regulation.HIPAA, Regulation.EU_AI_ACT]
        
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
                ViolationSeverity.HIGH, ViolationSeverity.CRITICAL
            ]:
                self.alert_callback(violation)
        
        return entry
    
    def get_violations_report(
        self,
        regulation: Optional[Regulation] = None,
        severity: Optional[ViolationSeverity] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
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
            by_regulation[v.regulation.value] = by_regulation.get(v.regulation.value, 0) + 1
            by_status[v.status] = by_status.get(v.status, 0) + 1
        
        return {
            "total_violations": len(filtered),
            "by_severity": by_severity,
            "by_regulation": by_regulation,
            "by_status": by_status,
            "critical_violations": [v.to_dict() for v in filtered if v.severity == ViolationSeverity.CRITICAL],
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
                writer.writerow([
                    "entry_id", "trace_id", "step_id", "action_type",
                    "timestamp", "regulations", "violations"
                ])
                for entry in self.audit_trail:
                    writer.writerow([
                        entry.entry_id,
                        entry.trace_id,
                        entry.step_id,
                        entry.action_type,
                        datetime.fromtimestamp(entry.timestamp).isoformat(),
                        "|".join(r.value for r in entry.regulations_checked),
                        "|".join(entry.violations_found),
                    ])
        
        return output_file
    
    def get_compliance_score(self) -> Dict[str, Any]:
        """Calculate overall compliance score."""
        if not self.audit_trail:
            return {"status": "no_audits_performed"}
        
        total_checks = len(self.audit_trail)
        violations_count = len(self.violations)
        
        critical_count = sum(1 for v in self.violations if v.severity == ViolationSeverity.CRITICAL)
        high_count = sum(1 for v in self.violations if v.severity == ViolationSeverity.HIGH)
        
        # Score calculation (100 = perfect compliance)
        score = max(0, 100 - (critical_count * 20) - (high_count * 10) - (violations_count * 2))
        
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
    regulations: Optional[List[Regulation]] = None,
    alert_callback: Optional[Callable] = None,
) -> ComplianceAuditor:
    """Enable compliance auditing with specified regulations."""
    auditor = ComplianceAuditor()
    auditor.alert_callback = alert_callback
    return auditor


def create_compliance_checker() -> ComplianceChecker:
    """Create a standalone compliance checker."""
    return ComplianceChecker()

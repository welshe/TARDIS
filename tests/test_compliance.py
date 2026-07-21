"""Tests for the compliance auditor."""

from tardis.compliance import (
    ComplianceAuditor,
    ComplianceChecker,
    Regulation,
    enable_compliance_auditing,
)


class TestComplianceChecker:
    """Test individual compliance checks."""

    def setup_method(self):
        self.checker = ComplianceChecker()

    def test_gdpr_transparency_violation(self):
        """GDPR transparency check flags processing without consent."""
        violations = self.checker.check_action(
            "process_personal_data",
            {"user_id": "123"},
            {"result": "profiled"},
            [Regulation.GDPR],
        )
        assert len(violations) > 0
        assert violations[0].requirement == "GDPR-Art5-1a"

    def test_gdpr_transparency_no_violation(self):
        """GDPR transparency check passes with consent."""
        violations = self.checker.check_action(
            "process_personal_data",
            {"user_id": "123", "consent_id": "consent_abc"},
            {"result": "profiled"},
            [Regulation.GDPR],
        )
        assert len(violations) == 0

    def test_gdpr_minimization_violation(self):
        """GDPR minimization check flags excessive data collection."""
        violations = self.checker.check_action(
            "profile_user",
            {"ssn": "123-45-6789", "credit_card": "4111", "consent_id": "consent_123"},
            {"result": "done"},
            [Regulation.GDPR],
        )
        assert len(violations) > 0
        assert violations[0].requirement == "GDPR-Art5-1c"

    def test_hipaa_access_control_violation(self):
        """HIPAA access control flags PHI access without authorization."""
        violations = self.checker.check_action(
            "view_record",
            {"health_record": "patient_123"},
            {"data": "sensitive"},
            [Regulation.HIPAA],
        )
        assert len(violations) > 0
        assert violations[0].requirement == "HIPAA-164.312(a)"

    def test_hipaa_deidentification_violation(self):
        """HIPAA de-identification flags exports with identifiers."""
        violations = self.checker.check_action(
            "export",
            {"action": "export"},
            {"export": True, "name": "John", "address": "123 Main St"},
            [Regulation.HIPAA],
        )
        assert len(violations) > 0

    def test_eu_ai_oversight_violation(self):
        """EU AI Act oversight check flags high-risk actions without oversight."""
        violations = self.checker.check_action(
            "medical_diagnosis",
            {"patient_id": "p1"},
            {"diagnosis": "condition"},
            [Regulation.EU_AI_ACT],
        )
        assert len(violations) > 0
        assert violations[0].requirement == "EU-AI-Art15"

    def test_soc2_access_control_violation(self):
        """SOC2 access control flags unauthenticated sensitive actions."""
        violations = self.checker.check_action(
            "config_change",
            {"setting": "debug_mode"},
            {"changed": True},
            [Regulation.SOC2],
        )
        assert len(violations) > 0
        assert violations[0].requirement == "SOC2-CC6.1"

    def test_pci_data_protection_violation(self):
        """PCI DSS flags unencrypted cardholder data."""
        violations = self.checker.check_action(
            "payment_processing",
            {"card_number": "4111111111111111"},
            {"status": "processed"},
            [Regulation.PCI_DSS],
        )
        assert len(violations) > 0
        assert violations[0].requirement == "PCI-DSS-3.4"

    def test_ccpa_right_to_know_violation(self):
        """CCPA right-to-know flags collection without notice."""
        violations = self.checker.check_action(
            "data_collection",
            {"california_consumer": True, "data_type": "browsing_history"},
            {"collected": True},
            [Regulation.CCPA],
        )
        assert len(violations) > 0
        assert violations[0].requirement == "CCPA-1798.100"

    def test_no_violation_on_safe_action(self):
        """Safe action should not trigger violations."""
        violations = self.checker.check_action(
            "read_file",
            {"path": "data.txt"},
            {"content": "hello world"},
            [Regulation.GDPR, Regulation.HIPAA, Regulation.EU_AI_ACT],
        )
        assert len(violations) == 0


class TestComplianceAuditor:
    """Test the compliance auditor orchestration."""

    def setup_method(self):
        self.auditor = ComplianceAuditor()

    def test_audit_step_records_violations(self):
        """Verify audit_step records violations."""
        entry = self.auditor.audit_step(
            trace_id="trace_1",
            step_id="step_1",
            action_type="process_personal_data",
            input_data={"user_id": "123"},
            output_data={"result": "profiled"},
        )
        assert entry is not None
        assert len(entry.violations_found) > 0

    def test_compliance_score(self):
        """Verify compliance score calculation."""
        # Perform a clean audit
        self.auditor.audit_step(
            trace_id="trace_1",
            step_id="step_1",
            action_type="read_file",
            input_data={"path": "test.txt"},
            output_data={"content": "ok"},
        )
        score = self.auditor.get_compliance_score()
        assert "compliance_score" in score
        assert score["compliance_score"] >= 0

    def test_violations_report_filtering(self):
        """Verify violations report can be filtered."""
        self.auditor.audit_step(
            trace_id="trace_1",
            step_id="step_1",
            action_type="process_personal_data",
            input_data={"user_id": "123"},
            output_data={"result": "profiled"},
        )
        report = self.auditor.get_violations_report(regulation=Regulation.GDPR)
        assert "total_violations" in report


class TestEnableComplianceAuditing:
    """Test the convenience function passes regulations correctly."""

    def test_regulations_passthrough(self):
        """Verify enable_compliance_auditing passes regulations."""
        auditor = enable_compliance_auditing(
            regulations=[Regulation.GDPR],
        )
        assert hasattr(auditor, "_active_regulations")
        assert Regulation.GDPR in auditor._active_regulations
        assert Regulation.HIPAA not in auditor._active_regulations

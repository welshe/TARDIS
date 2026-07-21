"""Tests for the cost-aware model routing system."""

import pytest

from tardis.routing import (
    ComplexityAnalyzer,
    CostAwareRouter,
    ModelTier,
    create_router,
)


class TestComplexityAnalyzer:
    """Test query complexity analysis."""

    def setup_method(self):
        self.analyzer = ComplexityAnalyzer()

    def test_simple_query_low_score(self):
        """Short, simple queries should have low complexity."""
        score, breakdown = self.analyzer.analyze("hi")
        assert score < 0.3

    def test_complex_query_high_score(self):
        """Long, complex queries should have higher complexity."""
        score, breakdown = self.analyzer.analyze(
            "Analyze the performance of this algorithm, compare it with alternatives, "
            "evaluate the tradeoffs, synthesize findings, and optimize for production. "
            "Consider the following steps: first, benchmark. second, profile. third, refactor."
        )
        assert score > 0.3

    def test_keyword_detection(self):
        """Keywords should influence complexity score."""
        score_simple, _ = self.analyzer.analyze("hello")
        score_complex, _ = self.analyzer.analyze(
            "implement debug refactor optimize algorithm complexity data structure design pattern"
        )
        assert score_complex > score_simple

    def test_structure_detection(self):
        """Structural elements should influence complexity."""
        score, breakdown = self.analyzer.analyze(
            "step 1: do this\nstep 2: do that\nstep 3: done\nexample: yes"
        )
        assert breakdown["structure_score"] > 0


class TestCostAwareRouter:
    """Test the cost-aware routing system."""

    def setup_method(self):
        self.router = CostAwareRouter(budget_limit=1.0)

    def test_select_model_simple_query(self):
        """Simple queries should be routed to cheap models."""
        decision = self.router.select_model("hi")
        assert decision.tier == ModelTier.CHEAP

    def test_select_model_complex_query(self):
        """Complex queries should be routed to more expensive models."""
        decision = self.router.select_model(
            "Analyze, compare, evaluate, synthesize, and optimize this complex algorithm. "
            "Consider multiple approaches, debug edge cases, and implement a solution."
        )
        assert decision.tier in (ModelTier.MID, ModelTier.EXPENSIVE)

    def test_budget_enforcement(self):
        """Budget limit should be enforced."""
        import asyncio

        async def test():
            router = CostAwareRouter(budget_limit=0.000001)
            result = await router.route_and_execute("test query")
            assert "error" in result
            assert result["error"] == "budget_exceeded"

        asyncio.run(test())

    def test_statistics(self):
        """Statistics should be available."""
        self.router.select_model("test query")
        stats = self.router.get_statistics()
        assert stats["total_queries"] == 1
        assert "by_tier" in stats

    def test_savings_calculation(self):
        """Potential savings should be calculated."""
        self.router.select_model("simple test")
        self.router.select_model("another simple test")
        stats = self.router.get_statistics()
        assert "potential_savings" in stats

    def test_route_and_execute_requires_client(self):
        """route_and_execute must raise KeyError if no client registered."""
        import asyncio

        async def test():
            router = CostAwareRouter(budget_limit=100.0)
            with pytest.raises(KeyError, match="No client registered"):
                await router.route_and_execute("test query")

        asyncio.run(test())

    def test_route_and_execute_with_registered_client(self):
        """route_and_execute should execute with a registered client."""
        import asyncio

        async def test():
            def fake_client(query):
                class FakeResponse:
                    usage = {"total_tokens": 50}

                return FakeResponse()

            router = CostAwareRouter(budget_limit=100.0)
            # Register client on all models to ensure the selected model has one
            for model_name in list(router.models.keys()):
                router.register_model(
                    router.models[model_name],
                    client=fake_client,
                )
            result = await router.route_and_execute("test query")
            assert "cost" in result
            assert result["cost"] > 0

        asyncio.run(test())


class TestCreateRouter:
    """Test the convenience factory."""

    def test_create_router_default(self):
        """Default router should be created successfully."""
        router = create_router()
        assert isinstance(router, CostAwareRouter)
        assert router.budget_limit == 100.0

    def test_create_router_custom_budget(self):
        """Custom budget should be respected."""
        router = create_router(budget_limit=50.0)
        assert router.budget_limit == 50.0

import unittest

from salpy import SAL, SalNotFoundError, find_sal_dir
from salpy.sexpr import scheme_literal, sym


class SchemeLiteralTests(unittest.TestCase):
    def test_quotes_symbols_as_data(self):
        self.assertEqual(scheme_literal(sym("yices2")), "'yices2")
        self.assertEqual(scheme_literal(sym(":ltl?")), ":ltl?")


class SalIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.sal_dir = find_sal_dir()
        except SalNotFoundError as exc:
            raise unittest.SkipTest(str(exc)) from exc

    def test_terms_are_parsed_and_typechecked(self):
        with SAL(self.sal_dir, timeout=20) as sal:
            expr = sal.expr("1 + 2")
            self.assertEqual(expr.pp().strip(), "1 + 2")
            self.assertEqual(expr.type().pp().strip(), "nat")

    def test_builder_model_checks(self):
        with SAL(self.sal_dir, timeout=20) as sal:
            ctx = sal.builder("toggle_test")
            ctx.module("main").output("x", "BOOLEAN").init("x = FALSE").transition("x' = NOT x")
            ctx.theorem("safe", "main", "G(x = TRUE OR x = FALSE)")
            ctx.load(sal)
            result = sal.engines.smc("toggle_test!safe")
            self.assertEqual(result.status, "proved")
            self.assertTrue(result.ok)

    def test_smc_counterexample_path(self):
        with SAL(self.sal_dir, timeout=30) as sal:
            result = sal.engines.smc(
                "peterson!invalid",
                context=self.sal_dir / "examples" / "peterson" / "peterson.sal",
            )
            self.assertEqual(result.status, "counterexample")
            self.assertIsNotNone(result.counterexample)
            self.assertGreaterEqual(result.counterexample.length(), 1)


if __name__ == "__main__":
    unittest.main()


from app.services.alerts import evaluate_measure, evaluate_quality

# Brazil: ideal temperature 29 °C ±3 (tolerance) -> excellent <=0.75, good <=1.8,
# fair <=3 (= specification tolerance limit), low <=6, critical >6.


class TestEvaluateQuality:
    def test_excellent_close_to_ideal(self):
        anomalies = evaluate_quality(29.2, 55.1, "brazil")
        assert anomalies[0]["tier"] == "excellent"
        assert anomalies[1]["tier"] == "excellent"
        assert anomalies[0]["direction"] is None

    def test_good(self):
        anomalies = evaluate_quality(30.5, 55.0, "brazil")
        assert anomalies[0]["tier"] == "good"

    def test_fair_at_the_tolerance_limit(self):
        anomalies = evaluate_quality(31.5, 55.0, "brazil")
        assert anomalies[0]["tier"] == "fair"

    def test_low_out_of_tolerance(self):
        anomalies = evaluate_quality(33.0, 55.0, "brazil")
        assert anomalies[0]["tier"] == "low"
        assert anomalies[0]["direction"] == "too high"

    def test_critical_beyond_double_tolerance(self):
        anomalies = evaluate_quality(40.0, 55.0, "brazil")
        assert anomalies[0]["tier"] == "critical"
        assert anomalies[0]["direction"] == "too high"

    def test_too_low(self):
        anomalies = evaluate_quality(15.0, 55.0, "brazil")
        assert anomalies[0]["tier"] == "critical"
        assert anomalies[0]["direction"] == "too low"

    def test_evaluate_quality_always_returns_two_entries(self):
        assert len(evaluate_quality(29.0, 55.0, "brazil")) == 2
        assert len(evaluate_quality(99.0, 99.0, "brazil")) == 2


class TestEvaluateMeasure:
    def test_no_anomaly_if_everything_is_within_tolerance(self):
        # excellent, good and fair are all "compliant" -> evaluate_measure does not keep them.
        assert evaluate_measure(29.2, 55.1, "brazil") == []
        assert evaluate_measure(30.5, 55.0, "brazil") == []
        assert evaluate_measure(31.5, 55.0, "brazil") == []

    def test_low_anomaly_kept(self):
        anomalies = evaluate_measure(33.0, 55.0, "brazil")
        assert len(anomalies) == 1
        assert anomalies[0]["tier"] == "low"

    def test_critical_anomaly_kept(self):
        anomalies = evaluate_measure(40.0, 55.0, "brazil")
        assert len(anomalies) == 1
        assert anomalies[0]["tier"] == "critical"

    def test_two_metrics_out_of_range(self):
        anomalies = evaluate_measure(40.0, 40.0, "brazil")
        assert len(anomalies) == 2

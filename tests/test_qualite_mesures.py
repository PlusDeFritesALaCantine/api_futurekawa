from app.services.alertes import evaluer_mesure, evaluer_qualite

# Brésil : idéal température 29°C ±3 (tolérance) -> excellent <=0.75, bon <=1.8,
# correct <=3 (= limite de tolérance du cahier des charges), bas <=6, critique >6.


class TestEvaluerQualite:
    def test_excellent_proche_de_ideal(self):
        anomalies = evaluer_qualite(29.2, 55.1, "bresil")
        assert anomalies[0]["tier"] == "excellent"
        assert anomalies[1]["tier"] == "excellent"
        assert anomalies[0]["direction"] is None

    def test_bon(self):
        anomalies = evaluer_qualite(30.5, 55.0, "bresil")
        assert anomalies[0]["tier"] == "bon"

    def test_correct_a_la_limite_de_tolerance(self):
        anomalies = evaluer_qualite(31.5, 55.0, "bresil")
        assert anomalies[0]["tier"] == "correct"

    def test_bas_hors_tolerance(self):
        anomalies = evaluer_qualite(33.0, 55.0, "bresil")
        assert anomalies[0]["tier"] == "bas"
        assert anomalies[0]["direction"] == "trop élevée"

    def test_critique_au_dela_du_double_de_tolerance(self):
        anomalies = evaluer_qualite(40.0, 55.0, "bresil")
        assert anomalies[0]["tier"] == "critique"
        assert anomalies[0]["direction"] == "trop élevée"

    def test_trop_basse(self):
        anomalies = evaluer_qualite(15.0, 55.0, "bresil")
        assert anomalies[0]["tier"] == "critique"
        assert anomalies[0]["direction"] == "trop basse"

    def test_evaluer_qualite_retourne_toujours_deux_entrees(self):
        assert len(evaluer_qualite(29.0, 55.0, "bresil")) == 2
        assert len(evaluer_qualite(99.0, 99.0, "bresil")) == 2


class TestEvaluerMesure:
    def test_aucune_anomalie_si_tout_est_dans_la_tolerance(self):
        # excellent, bon et correct sont tous "conformes" -> evaluer_mesure ne les retient pas.
        assert evaluer_mesure(29.2, 55.1, "bresil") == []
        assert evaluer_mesure(30.5, 55.0, "bresil") == []
        assert evaluer_mesure(31.5, 55.0, "bresil") == []

    def test_anomalie_bas_retenue(self):
        anomalies = evaluer_mesure(33.0, 55.0, "bresil")
        assert len(anomalies) == 1
        assert anomalies[0]["tier"] == "bas"

    def test_anomalie_critique_retenue(self):
        anomalies = evaluer_mesure(40.0, 55.0, "bresil")
        assert len(anomalies) == 1
        assert anomalies[0]["tier"] == "critique"

    def test_deux_grandeurs_en_anomalie(self):
        anomalies = evaluer_mesure(40.0, 40.0, "bresil")
        assert len(anomalies) == 2

-- Seed FutureKawa — Brésil
-- LOT-BR-001 : conforme (10 jours)
-- LOT-BR-002 : conforme ou périmé selon la date courante (200 jours)
-- LOT-BR-003 : périmé (400 jours)

INSERT INTO lots (id, pays, exploitation, entrepot_id, date_stockage, statut) VALUES
  ('LOT-BR-001', 'bresil', 'Fazenda Santa Clara', 'entrepot-bresil-1', CURRENT_DATE - INTERVAL '10 days',  'conforme'),
  ('LOT-BR-002', 'bresil', 'Fazenda Rio Verde',   'entrepot-bresil-1', CURRENT_DATE - INTERVAL '200 days', 'conforme'),
  ('LOT-BR-003', 'bresil', 'Fazenda Boa Esperança','entrepot-bresil-1', CURRENT_DATE - INTERVAL '400 days', 'perime')
ON CONFLICT (id) DO NOTHING;

-- 50 mesures sur 7 jours pour entrepot-bresil-1
-- dont 5 mesures hors seuil (temp > 32°C ou humidité < 53%)
INSERT INTO mesures (id, entrepot_id, temperature, humidity, timestamp) VALUES
  -- Jour J-7
  ('M-001', 'entrepot-bresil-1', 28.5, 54.5, NOW() - INTERVAL '7 days'),
  ('M-002', 'entrepot-bresil-1', 29.1, 55.0, NOW() - INTERVAL '7 days' + INTERVAL '3 hours'),
  ('M-003', 'entrepot-bresil-1', 33.5, 55.0, NOW() - INTERVAL '7 days' + INTERVAL '6 hours'),  -- HORS SEUIL temp
  ('M-004', 'entrepot-bresil-1', 28.8, 54.8, NOW() - INTERVAL '7 days' + INTERVAL '9 hours'),
  ('M-005', 'entrepot-bresil-1', 29.3, 55.2, NOW() - INTERVAL '7 days' + INTERVAL '12 hours'),
  ('M-006', 'entrepot-bresil-1', 29.0, 55.5, NOW() - INTERVAL '7 days' + INTERVAL '15 hours'),
  ('M-007', 'entrepot-bresil-1', 28.7, 54.9, NOW() - INTERVAL '7 days' + INTERVAL '18 hours'),
  -- Jour J-6
  ('M-008', 'entrepot-bresil-1', 29.2, 55.1, NOW() - INTERVAL '6 days'),
  ('M-009', 'entrepot-bresil-1', 29.5, 52.0, NOW() - INTERVAL '6 days' + INTERVAL '3 hours'),  -- HORS SEUIL hum
  ('M-010', 'entrepot-bresil-1', 28.9, 55.3, NOW() - INTERVAL '6 days' + INTERVAL '6 hours'),
  ('M-011', 'entrepot-bresil-1', 29.1, 54.7, NOW() - INTERVAL '6 days' + INTERVAL '9 hours'),
  ('M-012', 'entrepot-bresil-1', 29.4, 55.0, NOW() - INTERVAL '6 days' + INTERVAL '12 hours'),
  ('M-013', 'entrepot-bresil-1', 28.6, 55.4, NOW() - INTERVAL '6 days' + INTERVAL '15 hours'),
  ('M-014', 'entrepot-bresil-1', 29.0, 54.6, NOW() - INTERVAL '6 days' + INTERVAL '18 hours'),
  -- Jour J-5
  ('M-015', 'entrepot-bresil-1', 34.0, 55.0, NOW() - INTERVAL '5 days'),                       -- HORS SEUIL temp
  ('M-016', 'entrepot-bresil-1', 29.2, 55.1, NOW() - INTERVAL '5 days' + INTERVAL '3 hours'),
  ('M-017', 'entrepot-bresil-1', 29.0, 54.8, NOW() - INTERVAL '5 days' + INTERVAL '6 hours'),
  ('M-018', 'entrepot-bresil-1', 28.8, 55.2, NOW() - INTERVAL '5 days' + INTERVAL '9 hours'),
  ('M-019', 'entrepot-bresil-1', 29.3, 54.9, NOW() - INTERVAL '5 days' + INTERVAL '12 hours'),
  ('M-020', 'entrepot-bresil-1', 29.1, 55.0, NOW() - INTERVAL '5 days' + INTERVAL '15 hours'),
  ('M-021', 'entrepot-bresil-1', 28.9, 55.3, NOW() - INTERVAL '5 days' + INTERVAL '18 hours'),
  -- Jour J-4
  ('M-022', 'entrepot-bresil-1', 29.0, 55.0, NOW() - INTERVAL '4 days'),
  ('M-023', 'entrepot-bresil-1', 29.2, 51.5, NOW() - INTERVAL '4 days' + INTERVAL '3 hours'),  -- HORS SEUIL hum
  ('M-024', 'entrepot-bresil-1', 28.7, 55.1, NOW() - INTERVAL '4 days' + INTERVAL '6 hours'),
  ('M-025', 'entrepot-bresil-1', 29.4, 54.8, NOW() - INTERVAL '4 days' + INTERVAL '9 hours'),
  ('M-026', 'entrepot-bresil-1', 29.1, 55.2, NOW() - INTERVAL '4 days' + INTERVAL '12 hours'),
  ('M-027', 'entrepot-bresil-1', 28.9, 55.0, NOW() - INTERVAL '4 days' + INTERVAL '15 hours'),
  ('M-028', 'entrepot-bresil-1', 29.3, 54.7, NOW() - INTERVAL '4 days' + INTERVAL '18 hours'),
  -- Jour J-3
  ('M-029', 'entrepot-bresil-1', 29.0, 55.1, NOW() - INTERVAL '3 days'),
  ('M-030', 'entrepot-bresil-1', 28.8, 54.9, NOW() - INTERVAL '3 days' + INTERVAL '3 hours'),
  ('M-031', 'entrepot-bresil-1', 29.2, 55.3, NOW() - INTERVAL '3 days' + INTERVAL '6 hours'),
  ('M-032', 'entrepot-bresil-1', 35.2, 55.0, NOW() - INTERVAL '3 days' + INTERVAL '9 hours'),  -- HORS SEUIL temp
  ('M-033', 'entrepot-bresil-1', 29.1, 54.8, NOW() - INTERVAL '3 days' + INTERVAL '12 hours'),
  ('M-034', 'entrepot-bresil-1', 28.9, 55.2, NOW() - INTERVAL '3 days' + INTERVAL '15 hours'),
  ('M-035', 'entrepot-bresil-1', 29.0, 55.0, NOW() - INTERVAL '3 days' + INTERVAL '18 hours'),
  -- Jour J-2
  ('M-036', 'entrepot-bresil-1', 29.1, 55.1, NOW() - INTERVAL '2 days'),
  ('M-037', 'entrepot-bresil-1', 28.8, 54.9, NOW() - INTERVAL '2 days' + INTERVAL '3 hours'),
  ('M-038', 'entrepot-bresil-1', 29.3, 55.2, NOW() - INTERVAL '2 days' + INTERVAL '6 hours'),
  ('M-039', 'entrepot-bresil-1', 29.0, 54.7, NOW() - INTERVAL '2 days' + INTERVAL '9 hours'),
  ('M-040', 'entrepot-bresil-1', 28.9, 55.0, NOW() - INTERVAL '2 days' + INTERVAL '12 hours'),
  ('M-041', 'entrepot-bresil-1', 29.2, 55.3, NOW() - INTERVAL '2 days' + INTERVAL '15 hours'),
  ('M-042', 'entrepot-bresil-1', 29.0, 54.8, NOW() - INTERVAL '2 days' + INTERVAL '18 hours'),
  -- Jour J-1
  ('M-043', 'entrepot-bresil-1', 29.1, 55.0, NOW() - INTERVAL '1 day'),
  ('M-044', 'entrepot-bresil-1', 28.9, 55.2, NOW() - INTERVAL '1 day' + INTERVAL '3 hours'),
  ('M-045', 'entrepot-bresil-1', 29.3, 54.9, NOW() - INTERVAL '1 day' + INTERVAL '6 hours'),
  ('M-046', 'entrepot-bresil-1', 29.0, 55.1, NOW() - INTERVAL '1 day' + INTERVAL '9 hours'),
  ('M-047', 'entrepot-bresil-1', 28.8, 54.8, NOW() - INTERVAL '1 day' + INTERVAL '12 hours'),
  ('M-048', 'entrepot-bresil-1', 29.2, 55.0, NOW() - INTERVAL '1 day' + INTERVAL '15 hours'),
  ('M-049', 'entrepot-bresil-1', 29.0, 55.3, NOW() - INTERVAL '1 day' + INTERVAL '18 hours'),
  -- Aujourd'hui
  ('M-050', 'entrepot-bresil-1', 29.1, 55.0, NOW())
ON CONFLICT (id) DO NOTHING;

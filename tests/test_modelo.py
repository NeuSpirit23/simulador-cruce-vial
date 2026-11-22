from simulador.datos import cargar_semaforos
from simulador.generador import GeneradorCongruencial
from simulador.modelo import Escenario, simular, sortear, tabla_intervalos
from simulador.pruebas import prueba_frecuencias, prueba_ks, prueba_promedios


def test_generador_repetible():
    assert GeneradorCongruencial(12345).lista(5) == GeneradorCongruencial(12345).lista(5)


def test_generador_pasa_pruebas_coss_bu():
    u = GeneradorCongruencial(12345).lista(1000)
    assert prueba_promedios(u)["no_se_rechaza"]
    assert prueba_frecuencias(u)["no_se_rechaza"]
    assert prueba_ks(u)["no_se_rechaza"]


def test_tabla_intervalos():
    t = tabla_intervalos([1, 1, 2, 3])
    assert abs(t["probabilidad"].sum() - 1) < 1e-9
    assert sortear(t, 0.10) == 1 and sortear(t, 0.60) == 2 and sortear(t, 0.99) == 3


def test_datos_y_balance():
    sem = cargar_semaforos()
    assert [s.verde for s in sem.values()] == [25, 30, 25, 35]
    det, res = simular(sem, Escenario(ciclos=50))
    assert (det["pasan"] <= det["capacidad"]).all()
    assert (det["en_espera"] == det["pasan"] + det["quedan"]).all()
    assert len(res) == 4


def test_simulacion_se_parece_a_lo_observado():
    sem = cargar_semaforos()
    for periodo in ("Valle", "Pico"):
        _, res = simular(sem, Escenario(periodo=periodo, ciclos=1000))
        for _, r in res.iterrows():
            obs = sem[r["semaforo"]].pasan[periodo]
            media = sum(obs) / len(obs)
            assert abs(r["pasan_prom"] - media) / media < 0.10


def test_prediccion_por_fechas_y_reportes():
    from datetime import datetime

    from simulador.datos import calcular_llegadas, leer_base
    from simulador.exportar import excel_paquete, pdf_paquete
    from simulador.paquete import construir
    from simulador.prediccion import EscenarioPrediccion, predecir
    from simulador.reportes import reporte_bloques, reporte_horas, reporte_valle_pico

    sem = cargar_semaforos()
    res = predecir(sem, EscenarioPrediccion(datetime(2026, 11, 23, 6), datetime(2026, 11, 23, 20),
                                            repeticiones=5))
    bloques = reporte_bloques(res, 2)
    assert len(bloques) == 7
    assert abs(bloques["pct_del_total"].sum() - 100) < 1e-6
    # pico del Excel: 12:00–13:00 y 17:00–18:30 → bloques 12–14, 16–18 y 18–20
    con_pico = bloques[bloques["en_pico"] > 0]["bloque_ini"].dt.hour.tolist()
    assert con_pico == [12, 16, 18]
    assert len(reporte_horas(res)) == 14
    vp = reporte_valle_pico(res).set_index("periodo")
    assert vp.loc["Pico", "prom_por_hora"] > vp.loc["Valle", "prom_por_hora"]
    pq = construir(res, sem, calcular_llegadas(leer_base()), 2, 10)
    sp = pq.tablas["Semáforo y periodo"]
    assert set(sp["Periodo"]) == {"Valle", "Pico"} and len(sp) == 8
    assert set(pq.tablas["Capacidad"]["Periodo"]) == {"Valle", "Pico"}
    assert excel_paquete(pq)[:2] == b"PK"
    assert pdf_paquete(pq)[:4] == b"%PDF"


def test_modos_y_restriccion_valle_pico():
    from datetime import datetime

    from simulador.prediccion import (EscenarioPrediccion, ciclos_por_numeros, cubre_valle_y_pico,
                                      predecir)
    from simulador.reportes import reporte_bloques_ciclos

    assert cubre_valle_y_pico(datetime(2026, 1, 1, 6), datetime(2026, 1, 1, 11)) == (True, False)
    assert cubre_valle_y_pico(datetime(2026, 1, 1, 11), datetime(2026, 1, 1, 13)) == (True, True)
    assert ciclos_por_numeros(80_000, 10) == 1000

    sem = cargar_semaforos()
    res = predecir(sem, EscenarioPrediccion(datetime(2026, 1, 1, 11), datetime(2026, 1, 1, 11),
                                            repeticiones=3, ciclos_por_semaforo=60))
    assert (res.info_semaforos["ciclos"] == 60).all()
    bc = reporte_bloques_ciclos(res, 10)
    assert len(bc) == 24 and abs(bc.groupby("semaforo")["pct_del_semaforo"].sum() - 100).max() < 1e-6


def test_horas_pico_salen_del_excel():
    from simulador.prediccion import VENTANAS_PICO, texto_horas_pico
    assert VENTANAS_PICO == [(12 * 60, 13 * 60), (17 * 60, 18 * 60 + 30)]
    assert texto_horas_pico() == "12:00–13:00 y 17:00–18:30"


def test_secuencia_de_numeros_coincide_con_el_generador():
    from datetime import datetime

    import numpy as np

    from simulador.paquete import secuencia_numeros
    from simulador.prediccion import EscenarioPrediccion, predecir

    sem = cargar_semaforos()
    res = predecir(sem, EscenarioPrediccion(datetime(2026, 11, 23, 11), datetime(2026, 11, 23, 13), repeticiones=2))
    d = secuencia_numeros(res, sem)
    assert len(d) == 2 * res.info_semaforos["ciclos"].sum()
    assert np.allclose(d["U = X(n) ÷ 2147483647"], GeneradorCongruencial(12345).lista(len(d)))
    assert (d["X anterior"].iloc[1:].to_numpy() == d["X(n) = 16807·X anterior mod 2147483647"].iloc[:-1].to_numpy()).all()


def test_explorador_suma_igual_que_la_simulacion():
    from datetime import datetime
    from simulador.datos import SEMAFOROS, cargar_semaforos
    from simulador.explorador import explorar
    from simulador.prediccion import EscenarioPrediccion, predecir
    r = predecir(cargar_semaforos(), EscenarioPrediccion(datetime(2026, 11, 22, 6), datetime(2026, 11, 22, 20), 3, 7))
    t, ind = explorar(r.ciclos, "horas", list(SEMAFOROS), desde=datetime(2026, 11, 22, 6),
                      hasta=datetime(2026, 11, 22, 20), frecuencia_min=120)
    assert list(t["Intervalo"]) == ["06:00–08:00", "08:00–10:00", "10:00–12:00", "12:00–14:00",
                                    "14:00–16:00", "16:00–18:00", "18:00–20:00"]
    assert abs(t["Pasan (veh)"].sum() - r.ciclos["pasan_prom"].sum()) < 1e-6
    assert t.loc[t["Intervalo"] == "10:00–12:00", "Pasan en pico"].iloc[0] == 0
    assert t.loc[t["Intervalo"] == "12:00–14:00", "Pasan en pico"].iloc[0] > 0
    tc, _ = explorar(r.ciclos, "ciclos", ["S1"], ciclo_desde=1, ciclo_hasta=25, cada_ciclos=10)
    assert list(tc["Ciclos"]) == [10, 10, 5]

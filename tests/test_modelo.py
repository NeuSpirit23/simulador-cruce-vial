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

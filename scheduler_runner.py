"""
Agendador em background:
- roda a varredura a cada N horas (config: agendamento.intervalo_horas)
- roda a varredura todo dia em um horário fixo (config: agendamento.horario_fixo)
- expõe rodar_agora() para disparo manual (botão "Atualizar" no Streamlit)
"""
import threading
import yaml
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from scraper import rodar_varredura

CONFIG_PATH = Path(__file__).parent / "sites_config.yaml"

_lock = threading.Lock()
_scheduler = None


def _job_varredura():
    with _lock:  # evita rodar duas varreduras ao mesmo tempo
        rodar_varredura(headless=True)


def iniciar_agendador():
    """Cria (uma única vez) o BackgroundScheduler com os dois gatilhos.
    Chame isso uma vez ao iniciar a aplicação (app.py cuida disso via
    st.cache_resource, então isso não duplica jobs em cada rerun)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    agendamento = cfg.get("agendamento", {})
    intervalo_horas = agendamento.get("intervalo_horas", 6)
    horario_fixo = agendamento.get("horario_fixo", "09:10")
    hora, minuto = [int(x) for x in horario_fixo.split(":")]

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _job_varredura,
        trigger=IntervalTrigger(hours=intervalo_horas),
        id="varredura_intervalo",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        _job_varredura,
        trigger=CronTrigger(hour=hora, minute=minuto),
        id="varredura_horario_fixo",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def rodar_agora_async():
    """Dispara uma varredura imediata em background, sem esperar o
    agendamento (usado pelo botão 'Atualizar agora')."""
    thread = threading.Thread(target=_job_varredura, daemon=True)
    thread.start()
    return thread


def proximas_execucoes():
    if _scheduler is None:
        return []
    return [
        (job.id, job.next_run_time)
        for job in _scheduler.get_jobs()
    ]

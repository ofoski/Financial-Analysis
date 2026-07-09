from pathlib import Path

from prefect import flow, task

from clean import create_clean_table
from collect_prices import collect_prices
from validate import run_validation
from src.analysis.metrics import create_metrics_table

DB_PATH = Path("data/financials.db")


@task
def clean_step():
    create_clean_table(DB_PATH)


@task
def prices_step():
    collect_prices(DB_PATH)


@task
def validate_step():
    run_validation(DB_PATH)


@task
def metrics_step():
    create_metrics_table(DB_PATH)


@flow(name="financial-data-pipeline")
def run_pipeline():
    clean  = clean_step()
    prices = prices_step()
    validate_step(wait_for=[clean])
    metrics_step(wait_for=[clean, prices])


if __name__ == "__main__":
    run_pipeline()

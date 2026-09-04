from typing import Sequence
import clickhouse_connect
from config import settings
import certifi
from clickhouse_connect.driver.summary import QuerySummary


client = clickhouse_connect.get_client(
    host=settings.CH_HOST,
    port=8443,
    username="default",
    password=settings.CH_PSW,
    database="default",
    secure=True,
    ca_cert=certifi.where(),
)


class Ch:

    @staticmethod
    def ping() -> bool:
        try:
            return client.ping()
        except Exception as e:
            print(f"Error pinging ClickHouse: {e}")
            return False

    @staticmethod
    def query(query: str) -> list[dict] | bool:
        try:
            result = client.query(query)
            return [
                dict(zip(result.column_names, row))
                for row in result.result_rows
            ]
        except Exception as e:
            print(f"Error executing query: {e}")
            return False

    @staticmethod
    def insert(table: str, data: list[dict]) -> QuerySummary | bool:
        try:
            result = client.insert(table, data).written_rows
            return result
        except Exception as e:
            print(f"Error inserting data: {e}")
            return False

    @staticmethod
    def execute(query: str) -> str | int | Sequence[str] | QuerySummary | bool:
        try:
            return client.command(query)
        except Exception as e:
            print(f"Error executing command: {e}")
            return False

"""Typed schemas for the AeroCore tables (M2).

aerocore/schemas.py only lists column names. Indexes need to know each
column's type (int / str / float) and the primary key, so the typed version
lives here and the original AIRLINE_SCHEMAS stays untouched.
"""
from dataclasses import dataclass

_TYPES = {"int": int, "str": str, "float": (int, float)}


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns: dict          # column name -> "int" | "str" | "float"
    primary_key: str

    def key_type(self, column):
        return self.columns[column]

    def validate(self, record):
        for col, typ in self.columns.items():
            if col in record and not isinstance(record[col], _TYPES[typ]):
                raise TypeError(f"{self.name}.{col} must be {typ}, got {record[col]!r}")


TABLE_SCHEMAS = {
    "airports": TableSchema("airports", {"airport_id": "int", "name": "str", "city": "str", "country": "str"}, "airport_id"),
    "flights": TableSchema("flights", {"flight_id": "int", "source_airport": "int", "destination_airport": "int", "departure_time": "str"}, "flight_id"),
    "seats": TableSchema("seats", {"seat_id": "int", "flight_id": "int", "seat_number": "str", "status": "str"}, "seat_id"),
    "passengers": TableSchema("passengers", {"passenger_id": "int", "name": "str", "email": "str", "passport_number": "str"}, "passenger_id"),
    "reservations": TableSchema("reservations", {"reservation_id": "int", "passenger_id": "int", "flight_id": "int", "seat_id": "int", "status": "str"}, "reservation_id"),
    "payments": TableSchema("payments", {"payment_id": "int", "reservation_id": "int", "amount": "float", "payment_status": "str"}, "payment_id"),
}
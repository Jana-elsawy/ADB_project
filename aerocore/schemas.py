AIRLINE_SCHEMAS = {
    "airports": ["airport_id", "name", "city", "country"],
    "flights": ["flight_id", "source_airport", "destination_airport", "departure_time"],
    "seats": ["seat_id", "flight_id", "seat_number", "status"],
    "passengers": ["passenger_id", "name", "email", "passport_number"],
    "reservations": ["reservation_id", "passenger_id", "flight_id", "seat_id", "status"],
    "payments": ["payment_id", "reservation_id", "amount", "payment_status"],
}

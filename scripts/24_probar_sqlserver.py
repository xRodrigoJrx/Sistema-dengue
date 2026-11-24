from sqlalchemy import text
from dengue_common import get_sql_engine


def main():
    engine = get_sql_engine()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT @@SERVERNAME AS servidor, DB_NAME() AS base_datos, GETDATE() AS fecha_servidor")).mappings().one()
        print("CONEXIÓN EXITOSA A SQL SERVER")
        print(f"Servidor: {row['servidor']}")
        print(f"Base de datos: {row['base_datos']}")
        print(f"Fecha del servidor: {row['fecha_servidor']}")
        tables = conn.execute(text("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='dbo' ORDER BY TABLE_NAME")).scalars().all()
        print("Tablas:")
        for name in tables:
            print(f" - {name}")


if __name__ == "__main__":
    main()

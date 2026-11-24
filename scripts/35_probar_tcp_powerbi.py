import pyodbc

connection_string = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=tcp:127.0.0.1,51433;"
    "DATABASE=dengue_analytics;"
    "Trusted_Connection=yes;"
    "Encrypt=yes;"
    "TrustServerCertificate=yes;"
    "Connection Timeout=10;"
)

with pyodbc.connect(connection_string) as conn:

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            CONVERT(varchar(128), @@SERVERNAME),
            CONVERT(varchar(128), DB_NAME()),
            CONVERT(varchar(20),
                CONNECTIONPROPERTY('net_transport'))
    """)

    row = cursor.fetchone()

    cursor.execute("""
        SELECT CAST(local_tcp_port AS int)
        FROM sys.dm_exec_connections
        WHERE session_id = @@SPID
    """)

    port = cursor.fetchone()[0]

    cursor.execute("""
        SELECT
            COUNT(*),
            COUNT(latitud),
            COUNT(longitud)
        FROM dbo.dim_distrito_geo
    """)

    geo = cursor.fetchone()

    print("=" * 55)
    print("VALIDACION FINAL SQL SERVER")
    print("=" * 55)

    print("Servidor:", row[0])
    print("Base:", row[1])
    print("Transporte:", row[2])
    print("Puerto TCP:", port)

    print("\nGeografia:")
    print("Distritos:", geo[0])
    print("Latitudes:", geo[1])
    print("Longitudes:", geo[2])

    assert row[2].upper() == "TCP"
    assert port == 51433
    assert geo[0] == 1891
    assert geo[1] == 1891
    assert geo[2] == 1891

    print("\nVALIDACION COMPLETADA CORRECTAMENTE")
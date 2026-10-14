import psycopg

DATABASE_URL = "postgresql://neondb_owner:npg_CIPauiVlt2d0@ep-icy-salad-b1y1q0je-pooler.c-5.eu-central-1.aws.neon.tech/neondb?sslmode=require"

print("Reading and cleaning full_farm_data.sql...")
with open("full_farm_data.sql", "r") as f:
    lines = f.readlines()

cleaned_lines = []
for line in lines:
    stripped = line.strip()
    # Skip psql meta-commands
    if stripped.startswith('\\'):
        continue
    # Make tenant insertions safe against duplicates
    if stripped.startswith("INSERT INTO tenants") and "VALUES (1" in stripped:
        line = line.replace("INSERT INTO tenants", "INSERT INTO tenants") + " ON CONFLICT (id) DO NOTHING;\n"
    cleaned_lines.append(line)

sql_script = "".join(cleaned_lines)

print("Connecting to Neon database and importing Kamau's farm data...")
with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute(sql_script)

print("Database data imported successfully!")

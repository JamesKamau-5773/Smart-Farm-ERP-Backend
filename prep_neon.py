with open("full_farm_data.sql", "r") as f:
    lines = f.readlines()

clean_lines = []
for line in lines:
    stripped = line.strip()
    # Skip psql terminal commands
    if stripped.startswith('\\'):
        continue
    # Make inserts safe against duplicate key errors
    if stripped.startswith("INSERT INTO") and not stripped.endswith("ON CONFLICT DO NOTHING;"):
        line = line.rstrip(";\n") + " ON CONFLICT DO NOTHING;\n"
    clean_lines.append(line)

with open("kamaus_farm_clean.sql", "w") as f:
    f.writelines(clean_lines)

print("Generated 'kamaus_farm_clean.sql' successfully!")

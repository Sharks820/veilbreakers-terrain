import csv, io

rows = []
with open('docs/aaa-audit/GRADES_VERIFIED.csv', encoding='utf-8-sig', newline='') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        if row.get('File','').strip() == 'procedural_meshes.py':
            # Mark as scope-exempt
            row['R8 Deep Dive Verdict'] = 'SCOPE_EXEMPT: procedural_meshes.py (22,607 lines) is scope contamination in terrain repo — flagged for relocation to separate assets module. Terrain pipeline grades not applicable until relocated.'
            row['FINAL GRADE'] = 'N/A (SCOPE)'
        rows.append(row)

with open('docs/aaa-audit/GRADES_VERIFIED.csv', 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
print('Done: marked procedural_meshes.py rows as SCOPE_EXEMPT')

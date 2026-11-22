import csv
import json
import os


def flatten_dict(d: dict, parent_key: str = "", sep: str = ".") -> dict:
  items = []
  for k, v in d.items():
    new_key = f"{parent_key}{sep}{k}" if parent_key else k
    if isinstance(v, dict):
      items.extend(flatten_dict(v, new_key, sep=sep).items())
    elif isinstance(v, list):
      items.append((new_key, ", ".join(str(x) for x in v)))
    else:
      items.append((new_key, v))
  return dict(items)


def export_tab(json_path: str, csv_path: str):
  if not os.path.exists(json_path):
    print(f"Skipping {json_path} (not found yet)")
    return
  with open(json_path, "r", encoding="utf-8") as f:
    records = json.load(f)
  if not records:
    print(f"Skipping {json_path} (empty list)")
    return

  flat_rows = [flatten_dict(r) for r in records]
  headers = list(flat_rows[0].keys())

  with open(csv_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=headers)
    writer.writeheader()
    writer.writerows(flat_rows)
  print(f"Exported {len(flat_rows)} rows -> {csv_path}")


def main():
  os.makedirs("data/csv", exist_ok=True)
  mapping = [
      ("data/startups.json", "data/csv/Startups.csv"),
      ("data/products.json", "data/csv/Products.csv"),
      ("data/papers.json", "data/csv/Research Papers.csv"),
      ("data/jobs.json", "data/csv/Jobs.csv"),
      ("data/news.json", "data/csv/News.csv"),
      ("data/entity_mapping_log.json", "data/csv/Entity Mapping Log.csv"),
  ]
  for src_file, dst_file in mapping:
    export_tab(src_file, dst_file)


if __name__ == "__main__":
  main()
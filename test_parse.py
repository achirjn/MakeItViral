import json


def analyze_payload():
    file_path = "payload_dump_1772106978263.json"
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    found_paths = []

    def find_keys(obj, target="shortcode", path=""):
        if len(found_paths) > 20:
            return

        if isinstance(obj, dict):
            for k, v in obj.items():
                new_path = f"{path}.{k}" if path else k
                if k == target or k == "video_view_count" or k == "play_count":
                    found_paths.append(f"FOUND {k} AT: {new_path}")
                elif k == "__typename":
                    if isinstance(v, str) and "Video" in v:
                        found_paths.append(f"TYPENAME {v} AT: {new_path}")
                find_keys(v, target, new_path)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                find_keys(item, target, f"{path}[{i}]")

    find_keys(data)

    with open("parse_results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(found_paths))


if __name__ == "__main__":
    analyze_payload()

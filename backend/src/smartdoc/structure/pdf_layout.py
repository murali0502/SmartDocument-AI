import re
from statistics import median

SECTION_NUMBER = re.compile(r"^(\d+(?:\.\d+)*)(?:[.)])?\s+\S")


def page_hints(text: str, lines: list[dict], boxes: list[tuple]) -> list[dict]:
    sizes = [
        float(char["size"]) for line in lines for char in line["chars"] if char["text"].strip()
    ]
    typical = median(sizes) if sizes else 0
    hints = []
    cursor = 0
    for line in lines:
        value = line["text"].strip()
        if not value:
            continue
        start = text.find(value, cursor)
        if start < 0:
            continue
        end = start + len(value)
        cursor = end
        table_number = next(
            (
                index
                for index, (left, top, right, bottom) in enumerate(boxes, 1)
                if left <= line["x0"]
                and line["x1"] <= right
                and top <= line["top"]
                and line["bottom"] <= bottom
            ),
            None,
        )
        if table_number is not None:
            hints.append(
                {"kind": "table", "start": start, "end": end, "table_number": table_number}
            )
            continue
        heights = [float(char["size"]) for char in line["chars"] if char["text"].strip()]
        if heights and len(value) < 140 and median(heights) >= max(typical + 2, typical * 1.18):
            number = SECTION_NUMBER.match(value)
            level = min(6, len(number[1].split("."))) if number else 1
            hints.append({"kind": "heading", "start": start, "end": end, "level": level})
    return hints
